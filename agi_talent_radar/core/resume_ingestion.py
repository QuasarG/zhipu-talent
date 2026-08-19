from __future__ import annotations

import hashlib
import re
from pathlib import Path

from agi_talent_radar.core.models import CandidateResume


MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_PDF_PAGES = 30
OCR_RENDER_DPI = 200
MIN_PAGE_TEXT_CHARS = 30
# 混合页：文本层有一点内容（如几个链接）但关键信息在图片里，也补 OCR
MIXED_PAGE_TEXT_CHARS = 200

_ocr_engine = None


def load_pdf_resume(file_bytes: bytes, filename: str) -> CandidateResume:
    """PDF 提取为纯文本简历，结构化交给下游文本 LLM（ensure_structured_resume）。"""
    if not file_bytes:
        raise ValueError("PDF 文件为空。")
    if len(file_bytes) > MAX_PDF_BYTES:
        raise ValueError(f"PDF 超过 {MAX_PDF_BYTES // 1024 // 1024} MB 限制。")
    raw_text, ocr_pages = extract_pdf_text(file_bytes)
    if not raw_text.strip():
        raise ValueError("PDF 未能提取到任何文字内容。")
    return text_resume(raw_text, filename, ocr_pages=ocr_pages)


def text_resume(raw_text: str, filename: str, ocr_pages: list[int] | None = None) -> CandidateResume:
    return CandidateResume(
        id=_candidate_id(filename),
        source_format="pdf",
        raw_text=raw_text,
        ocr_pages=ocr_pages or [],
    )


def extract_pdf_text(file_bytes: bytes) -> tuple[str, list[int]]:
    """优先读文本层；字符过少的页面视为扫描件，用本地 RapidOCR 兜底。返回 (全文, OCR 页码)。"""
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("PDF 解析依赖缺失，请安装 pymupdf。") from exc

    document = fitz.open(stream=file_bytes, filetype="pdf")
    try:
        if document.needs_pass:
            raise ValueError("暂不支持加密 PDF。")
        if document.page_count > MAX_PDF_PAGES:
            raise ValueError(f"PDF 页数超过 {MAX_PDF_PAGES} 页限制。")
        scale = OCR_RENDER_DPI / 72
        page_texts = []
        ocr_pages = []
        for index, page in enumerate(document, start=1):
            text = page.get_text("text").strip()
            # 纯扫描页必 OCR；文本层稀疏且带图片的混合页也补 OCR（姓名/教育常在图片里）
            need_ocr = len(text) < MIN_PAGE_TEXT_CHARS or (
                len(text) < MIXED_PAGE_TEXT_CHARS and page.get_images()
            )
            if need_ocr:
                ocr_text = _ocr_page(page, scale)
                if ocr_text:
                    # 文本层与 OCR 结果合并而非覆盖，混合页两类内容都保留
                    text = f"{text}\n{ocr_text}".strip() if text else ocr_text
                    ocr_pages.append(index)
            if text:
                page_texts.append(f"[第 {index} 页]\n{text}")
        return "\n\n".join(page_texts), ocr_pages
    finally:
        document.close()


def _ocr_page(page, scale: float) -> str:
    import fitz

    pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    return _recognize_pixmap(pixmap)


def extract_image_text(file_bytes: bytes) -> str:
    """图片简历（png/jpg/webp）整图 OCR 提取。"""
    import fitz

    try:
        pixmap = fitz.Pixmap(file_bytes)
    except Exception as exc:
        raise ValueError("图片文件无法解码。") from exc
    return _recognize_pixmap(pixmap)


# 智谱云端 OCR 客户端（GLM-5V-Turbo，复用 LLM_API_KEY），失败回退本地 RapidOCR
_ocr_client = None


def _cloud_ocr_client():
    global _ocr_client
    if _ocr_client is None:
        import os

        api_key = (os.getenv("LLM_API_KEY") or os.getenv("Z_AI_API_KEY", "")).strip()
        if not api_key:
            return None
        import zai

        _ocr_client = zai.ZhipuAiClient(api_key=api_key)
    return _ocr_client


def _recognize_pixmap(pixmap) -> str:
    """统一 OCR：优先云端（快、准、免本地依赖），失败回退本地 RapidOCR。"""
    img_bytes = _pixmap_to_jpeg(pixmap)
    text = _recognize_via_cloud(img_bytes)
    if text is not None:
        return text
    return _recognize_via_local(pixmap)


def _pixmap_to_jpeg(pixmap) -> bytes:
    """PyMuPDF Pixmap → JPEG bytes（云端只收 png/jpg/bmp）。"""
    import io

    from PIL import Image

    mode = "RGB" if pixmap.alpha == 0 else "RGBA"
    img = Image.frombytes(mode, [pixmap.width, pixmap.height], pixmap.samples)
    if img.mode == "RGBA":
        img = img.convert("RGB")
    bio = io.BytesIO()
    img.save(bio, format="JPEG", quality=85)
    return bio.getvalue()


OCR_PROMPT = "逐行提取图片中的全部文字，保持原始行序，不要添加任何解释。"

# 结构化变体：识别的同时按语义分节（与下游 reorganize 节点同构），命中时下游可跳过重组
OCR_SECTIONS_PROMPT = """提取图片简历的全部内容并直接组织成 JSON。只输出 JSON 对象，顶层字段必须是 sections，不要任何解释。
按语义分节，每节 {"name": "节名", "text": "该节完整文字"}；节名从这些里选：基本信息 / 教育 / 经历 / 论文 / 项目 / 技能 / 其他。
内容只能重组排版，不得增删编造；保持原文顺序。"""

# 模块级缓存：本进程内最近一次结构化 OCR 的分节结果（ocr_pages 只带页码，分节挂这里）
_last_ocr_sections: list[dict[str, str]] | None = None


def take_last_ocr_sections() -> list[dict[str, str]] | None:
    """取走最近一次云端结构化 OCR 的分节（一次性消费，防串页）。"""
    global _last_ocr_sections
    sections, _last_ocr_sections = _last_ocr_sections, None
    return sections


def _recognize_via_cloud(img_bytes: bytes) -> str | None:
    """智谱 GLM-5V-Turbo 视觉模型 OCR（实测 1-3s/页、限流宽）；失败/未配置返回 None。

    单页简历直接走结构化（分节挂全局待取）；多页只首页结构化、其余页纯文本，
    避免多页 JSON 合并的复杂度——多页重组仍交下游 reorganize。
    """
    import base64
    import json as _json

    client = _cloud_ocr_client()
    if client is None:
        return None
    global _last_ocr_sections
    structured = _last_ocr_sections is None  # 每份简历首页做一次结构化
    prompt = OCR_SECTIONS_PROMPT if structured else OCR_PROMPT
    try:
        kwargs: dict = {}
        if structured:
            kwargs["response_format"] = {"type": "json_object"}
        resp = client.chat.completions.create(
            model="glm-5v-turbo",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": base64.b64encode(img_bytes).decode()}},
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
            thinking={"type": "disabled"},
            temperature=0.1,
            **kwargs,
        )
    except Exception:
        return None  # 静默回退本地 RapidOCR
    text = (resp.choices[0].message.content or "").strip()
    if not text:
        return None
    if structured:
        try:
            sections = _json.loads(text).get("sections") or []
            if isinstance(sections, list) and sections:
                _last_ocr_sections = [
                    {"name": str(s.get("name", "")), "text": str(s.get("text", ""))}
                    for s in sections
                    if str(s.get("text", "")).strip()
                ]
                # raw_text 用分节拼回（保序全文），下游仍有完整文本
                return "\n\n".join(f"{s['name']}\n{s['text']}" for s in _last_ocr_sections)
        except (ValueError, AttributeError):
            pass  # JSON 失败当纯文本用
    return text


def _recognize_via_local(pixmap) -> str:
    """回退方案：本地 RapidOCR（onnxruntime）。"""
    import fitz
    import numpy as np

    image = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.height, pixmap.width, pixmap.n)
    engine = _get_ocr_engine()
    if engine is None:
        return ""
    result, _ = engine(image)
    if not result:
        return ""
    return "\n".join(str(line[1]) for line in result if len(line) >= 2)


def _get_ocr_engine():
    global _ocr_engine
    if _ocr_engine is None:
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError:
            return None  # 本地兜底可选，云端可用时不需要
        _ocr_engine = RapidOCR()
    return _ocr_engine


def _candidate_id(filename: str) -> str:
    stem = Path(filename).stem.strip() or "candidate"
    normalized = re.sub(r"[^0-9A-Za-z_-]+", "_", stem)
    if normalized == stem:
        return normalized[:32]  # 纯 ASCII 文件名原样使用（含历史 id 兼容）
    # 含非 ASCII（如纯中文名）：归一化 + 原 stem 短哈希，
    # 保证不同文件名永不撞 id（撞了会互相覆盖候选人），且同一文件重导 id 稳定
    suffix = hashlib.sha256(stem.encode("utf-8")).hexdigest()[:8]
    base = normalized.strip("_-")
    base = base if re.search(r"[0-9A-Za-z]", base or "") else "candidate"
    return f"{base}_{suffix}"[:32]
