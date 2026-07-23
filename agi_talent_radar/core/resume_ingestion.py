from __future__ import annotations

import re
from pathlib import Path

from agi_talent_radar.core.models import CandidateResume


MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_PDF_PAGES = 30
OCR_RENDER_DPI = 200
MIN_PAGE_TEXT_CHARS = 30

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
    return text_resume(raw_text, filename)


def text_resume(raw_text: str, filename: str) -> CandidateResume:
    return CandidateResume(
        id=_candidate_id(filename),
        source_format="pdf",
        raw_text=raw_text,
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
            if len(text) < MIN_PAGE_TEXT_CHARS:
                ocr_text = _ocr_page(page, scale)
                if ocr_text:
                    text = ocr_text
                    ocr_pages.append(index)
            if text:
                page_texts.append(f"[第 {index} 页]\n{text}")
        return "\n\n".join(page_texts), ocr_pages
    finally:
        document.close()


def _ocr_page(page, scale: float) -> str:
    import numpy as np

    import fitz

    engine = _get_ocr_engine()
    pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    image = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.height, pixmap.width, pixmap.n)
    result, _ = engine(image)
    if not result:
        return ""
    return "\n".join(str(line[1]) for line in result if len(line) >= 2)


def _get_ocr_engine():
    global _ocr_engine
    if _ocr_engine is None:
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError as exc:
            raise RuntimeError("扫描版 PDF 需要 OCR 依赖，请安装 rapidocr-onnxruntime。") from exc
        _ocr_engine = RapidOCR()
    return _ocr_engine


def _candidate_id(filename: str) -> str:
    stem = Path(filename).stem.strip() or "candidate"
    normalized = re.sub(r"[^0-9A-Za-z_-]+", "_", stem).strip("_")
    return (normalized or "candidate")[:32]
