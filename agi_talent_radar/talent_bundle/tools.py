"""材料包 agent 工具层：文件系统操作（coding agent 式，全部限量）+ submit_profile。

- list_files / read_text / read_pages / search_text / extract_archive
- 所有读取分页限量（PAGE_CHARS），视觉模型只做"转译官"（复用奖学金的视觉客户端），
  不做 OCR 兜底——按用户决策：有便宜视觉模型，不再走本地 OCR。
- extract_archive 只能解包工作区内的内层压缩包到工作区，zip-slip/炸弹/深度全护栏。
- submit_profile 硬校验后构建 CandidateResume，进档路径与既有导入完全一致。
"""
from __future__ import annotations

import json
import logging
import os
import re
import tarfile
import zipfile
from typing import Any

logger = logging.getLogger(__name__)

PAGE_CHARS = 4000
TOOL_RESULT_MAX_CHARS = 6000
MAX_LIST_ENTRIES = 500
MAX_READ_PAGES = 5                 # read_pages 单次页数上限
MAX_EXTRACT_ROUNDS = 10            # 每包解压次数上限（等价深度/数量双护栏）
MAX_EXTRACT_BYTES = 500 * 1024 * 1024
TEXT_SUFFIXES = {".txt", ".md", ".csv", ".json", ".log", ".py", ".ts", ".tex", ".html", ".xml", ".yaml", ".yml"}
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
_ARCHIVE_SUFFIXES = {".zip", ".tar", ".gz", ".tgz"}

EVIDENCE_HINT = "（每个字段标注来源：文件名 第N页）"


class BundleContext:
    """一次解析的执行上下文：工作区根、文本缓存、已读台账、解压计数、终态。"""

    def __init__(self, bundle_id: str) -> None:
        from agi_talent_radar.talent_bundle.ingest import workspace_root

        self.bundle_id = bundle_id
        self.ws = workspace_root(bundle_id)
        self.text_cache: dict[str, str] = {}       # relpath → 全文（惰性提取）
        self.read_pages: dict[str, set[int]] = {}  # relpath → 已读页
        self.extract_rounds = 0
        self.profile: dict[str, Any] | None = None

    # ---- 路径安全 ----
    def resolve(self, rel: str) -> str | None:
        """工作区内相对路径 → 绝对路径；越界/不存在返回 None（zip-slip 防护）。"""
        clean = (rel or "").replace("\\", "/").lstrip("/")
        parts = [p for p in clean.split("/") if p not in ("", ".", "..")]
        if not parts:
            return None
        target = os.path.join(self.ws, *parts)
        if os.path.commonpath([os.path.abspath(target), os.path.abspath(self.ws)]) != os.path.abspath(self.ws):
            return None
        return target


def _rel(ctx: BundleContext, path: str) -> str:
    return os.path.relpath(path, ctx.ws).replace(os.sep, "/")


def _suffix(name: str) -> str:
    return ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""


def _walk(ctx: BundleContext) -> list[str]:
    out: list[str] = []
    for root, _dirs, files in os.walk(ctx.ws):
        for f in files:
            out.append(_rel(ctx, os.path.join(root, f)))
    return sorted(out)[:MAX_LIST_ENTRIES]


def _brief_file(ctx: BundleContext, rel: str) -> dict[str, Any]:
    path = ctx.resolve(rel)
    stat = os.stat(path) if path and os.path.isfile(path) else None
    suffix = _suffix(rel)
    kind = "archive" if suffix in _ARCHIVE_SUFFIXES else (
        "image" if suffix in _IMAGE_SUFFIXES else (
            "text" if suffix in TEXT_SUFFIXES or suffix == ".pdf" or suffix == ".docx" else "binary"))
    cached = len(ctx.text_cache.get(rel, ""))
    return {
        "file": rel,
        "kind": kind,
        "size_kb": max(1, (stat.st_size or 0) // 1024) if stat else 0,
        "cached_chars": cached or None,
    }


def _ensure_text(ctx: BundleContext, rel: str) -> str:
    """惰性提取全文并缓存：pdf 走文本层；docx 走 mammoth；纯文本直读。"""
    if rel in ctx.text_cache:
        return ctx.text_cache[rel]
    path = ctx.resolve(rel)
    if not path or not os.path.isfile(path):
        ctx.text_cache[rel] = ""
        return ""
    suffix = _suffix(rel)
    text = ""
    try:
        if suffix in TEXT_SUFFIXES:
            with open(path, "rb") as fp:
                text = fp.read(2_000_000).decode("utf-8", errors="replace")
        elif suffix == ".docx":
            import mammoth

            with open(path, "rb") as fp:
                text = str(mammoth.extract_raw_text(fp).value or "")
        elif suffix == ".pdf":
            import fitz

            doc = fitz.open(path)
            try:
                pages = []
                for i, page in enumerate(doc, start=1):
                    t = page.get_text("text").strip()
                    if t:
                        pages.append(f"[第 {i} 页]\n{t}")
                text = "\n\n".join(pages)
            finally:
                doc.close()
    except Exception as exc:  # noqa: BLE001 — 提取失败不阻断，agent 可改走 read_pages 视觉
        logger.warning("文本提取失败 %s：%s", rel, exc)
        text = ""
    ctx.text_cache[rel] = text
    return text


# ---- 工具实现 ----

def _tool_list_files(ctx: BundleContext, args: dict[str, Any]) -> dict[str, Any]:
    rels = _walk(ctx)
    files = [_brief_file(ctx, r) for r in rels]
    return {"summary": f"{len(files)} 个文件", "detail": {"files": files}}


def _tool_read_text(ctx: BundleContext, args: dict[str, Any]) -> dict[str, Any]:
    rel = str(args.get("file") or "")
    text = _ensure_text(ctx, rel)
    if not text:
        suffix = _suffix(rel)
        hint = "该文件无可提取文本层（扫描件/图片/视频），请改用 read_pages 走视觉转译。" if suffix in {
            ".pdf", ".docx", ".png", ".jpg", ".jpeg", ".webp"} else "文件为空或不存在。"
        return {"summary": f"{rel} 无文本", "detail": {"error": hint}}
    page = max(0, int(args.get("page") or 0))
    chunk = text[page * PAGE_CHARS:(page + 1) * PAGE_CHARS]
    total = max(1, (len(text) + PAGE_CHARS - 1) // PAGE_CHARS)
    ctx.read_pages.setdefault(rel, set()).update(range(page * PAGE_CHARS, (page + 1) * PAGE_CHARS))
    return {
        "summary": f"{rel} 第 {page + 1}/{total} 段（{len(chunk)} 字）",
        "detail": {"file": rel, "page": page, "total_pages": total, "text": chunk},
    }


def _tool_read_pages(ctx: BundleContext, args: dict[str, Any]) -> dict[str, Any]:
    """视觉转译读取：扫描件/图片/薄文本层 PDF。复用奖学金视觉客户端，按页缓存进 text_cache。"""
    rel = str(args.get("file") or "")
    path = ctx.resolve(rel)
    if not path or not os.path.isfile(path):
        return {"summary": f"{rel} 不存在", "detail": {"error": "file 不在 list_files 结果里"}}
    from agi_talent_radar.scholarship.scorer_tools import _VISION_PROMPT, _VISION_MODEL, _vision_client

    suffix = _suffix(rel)
    try:
        if suffix == ".pdf":
            import base64

            import fitz

            doc = fitz.open(path)
            try:
                total = doc.page_count
                start = max(0, int(args.get("start") or 0))
                count = min(MAX_READ_PAGES, max(1, int(args.get("count") or 3)))
                indices = range(start, min(total, start + count))
                parts = []
                for i in indices:
                    pixmap = doc[i].get_pixmap(matrix=fitz.Matrix(150 / 72, 150 / 72), alpha=False)
                    resp = _vision_client().chat.completions.create(
                        model=_VISION_MODEL,
                        messages=[{"role": "user", "content": [
                            {"type": "image_url", "image_url": {"url": base64.b64encode(pixmap.tobytes("png")).decode()}},
                            {"type": "text", "text": f"第 {i + 1}/{total} 页。{_VISION_PROMPT}"},
                        ]}],
                        temperature=0.1,
                    )
                    parts.append(f"[第 {i + 1} 页]\n" + (resp.choices[0].message.content or ""))
                    ctx.read_pages.setdefault(rel, set()).add(i)
                text = "\n\n".join(parts)
            finally:
                doc.close()
        elif suffix in _IMAGE_SUFFIXES:
            from agi_talent_radar.scholarship.scorer_tools import _vision_image

            text = _vision_image(path)
            ctx.read_pages.setdefault(rel, set()).add(0)
        else:
            return {"summary": "不支持视觉读取", "detail": {"error": "read_pages 仅用于扫描件 PDF 与图片；文本文档用 read_text。"}}
    except Exception as exc:  # noqa: BLE001
        return {"summary": "视觉转译失败", "detail": {"error": str(exc)[:300]}}
    ctx.text_cache[rel] = ctx.text_cache.get(rel, "") + text  # 缓存供 search_text 复用
    return {"summary": f"{rel} 视觉转译 {len(text)} 字", "detail": {"file": rel, "text": text[:TOOL_RESULT_MAX_CHARS]}}


def _tool_search_text(ctx: BundleContext, args: dict[str, Any]) -> dict[str, Any]:
    pattern = str(args.get("pattern") or "").strip()
    if not pattern:
        return {"summary": "pattern 为空", "detail": {"hits": []}}
    scoped = str(args.get("file") or "").strip()
    targets = [scoped] if scoped else _walk(ctx)
    hits: list[dict[str, Any]] = []
    try:
        rx = re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        return {"summary": "正则非法", "detail": {"error": str(exc)[:200]}}
    for rel in targets:
        text = _ensure_text(ctx, rel)
        if not text:
            continue
        for m in rx.finditer(text):
            if len(hits) >= 40:
                break
            page = text.count("\n", 0, m.start()) // 60  # 粗定位到"屏"而非行，够导航用
            hits.append({"file": rel, "approx_block": page, "context": text[max(0, m.start() - 60):m.end() + 60]})
        if len(hits) >= 40:
            break
    return {"summary": f"{len(hits)} 处命中", "detail": {"pattern": pattern, "hits": hits}}


def _tool_extract_archive(ctx: BundleContext, args: dict[str, Any]) -> dict[str, Any]:
    rel = str(args.get("file") or "")
    path = ctx.resolve(rel)
    if not path or not os.path.isfile(path):
        return {"summary": f"{rel} 不存在", "detail": {"error": "file 不在 list_files 结果里"}}
    suffix = _suffix(rel)
    if suffix not in _ARCHIVE_SUFFIXES:
        return {"summary": "非压缩包", "detail": {"error": "仅支持 zip/tar/tar.gz"}}
    if ctx.extract_rounds >= MAX_EXTRACT_ROUNDS:
        return {"summary": "解压次数已达上限", "detail": {"error": f"每包最多解压 {MAX_EXTRACT_ROUNDS} 次（防嵌套炸弹）"}}
    dest_rel = f"_extracted/{ctx.extract_rounds}_{os.path.basename(rel)[:64]}"
    dest = ctx.resolve(dest_rel) or os.path.join(ctx.ws, "_extracted", "x")
    os.makedirs(dest, exist_ok=True)
    count = 0
    total = 0
    try:
        if suffix == ".zip":
            with zipfile.ZipFile(path) as zf:
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    name = _safe_member(info.filename)
                    if name is None:
                        continue
                    data = zf.read(info)
                    count += _write_member(ctx, dest, name, data)
                    total += len(data)
        else:
            with tarfile.open(path, "r:*") as tf:
                for member in tf.getmembers():
                    if not member.isfile():
                        continue
                    name = _safe_member(member.name)
                    if name is None:
                        continue
                    member_fp = tf.extractfile(member)
                    data = member_fp.read() if member_fp else b""
                    count += _write_member(ctx, dest, name, data)
                    total += len(data)
    except Exception as exc:  # noqa: BLE001
        return {"summary": "解压失败", "detail": {"error": str(exc)[:300]}}
    if total > MAX_EXTRACT_BYTES:
        return {"summary": "解压内容超限", "detail": {"error": f"解压后 {total // 1024 // 1024} MB 超过上限"}}
    ctx.extract_rounds += 1
    return {"summary": f"解出 {count} 个文件 → {dest_rel}/", "detail": {"dest": dest_rel, "count": count, "total_bytes": total}}


def _write_member(ctx: BundleContext, dest: str, name: str, data: bytes) -> int:
    target = os.path.join(dest, *name.split("/"))
    if os.path.commonpath([os.path.abspath(target), os.path.abspath(ctx.ws)]) != os.path.abspath(ctx.ws):
        return 0  # zip-slip 条目直接丢弃
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "wb") as fp:
        fp.write(data)
    if len(data) > MAX_EXTRACT_BYTES:
        raise ValueError("解压后总大小超限")
    return 1


def _safe_member(name: str) -> str | None:
    normalized = name.replace("\\", "/").lstrip("/")
    parts = [p for p in normalized.split("/") if p not in ("", ".", "..")]
    if not parts or parts[0] == "__MACOSX" or any(p.startswith("._") for p in parts):
        return None
    return "/".join(parts)


# ---- 终点合同 ----

_PROFILE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "姓名（必填，来自材料原文）"},
        "name_en": {"type": "string"},
        "target_role": {"type": "string", "description": "目标岗位/申请方向"},
        "stage": {"type": "string", "description": "按系统时间换算的实际年级，如 博三"},
        "directions": {"type": "array", "items": {"type": "string"}},
        "education": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "school": {"type": "string"}, "degree": {"type": "string"},
                    "major": {"type": "string"}, "period": {"type": "string"},
                    "source": {"type": "string", "description": "来源：文件名 第N页"},
                },
                "required": ["school"],
            },
        },
        "experiences": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "organization": {"type": "string"}, "role": {"type": "string"},
                    "period": {"type": "string"}, "details": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["organization"],
            },
        },
        "projects": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "details": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["name"],
            },
        },
        "publications": {"type": "array", "items": {"type": "string"}, "description": "论文标题列表"},
        "skills": {"type": "array", "items": {"type": "string"}},
        "notes": {"type": "string", "description": "解析过程说明/存疑点，供人工抽查"},
    },
    "required": ["name"],
}


def tools_schema(stage: str) -> list[dict[str, Any]]:
    """阶段门：profiling 只给 FS 工具 + submit_profile；scoring 阶段再加 verify/web（评分 v2 接入）。"""

    def _fn(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": {"type": "object", "properties": properties, "required": required},
            },
        }

    tools = [
        _fn("list_files", "列出材料包内全部文件（相对路径/类型/大小）。包内嵌套压缩包显示为 archive，可用 extract_archive 解开。", {}, []),
        _fn("read_text", f"按段读取文件的可提取文本（每段约{PAGE_CHARS}字）。参数：file, page(从0开始)。",
            {"file": {"type": "string"}, "page": {"type": "integer"}}, ["file"]),
        _fn("read_pages", "视觉转译读取扫描件 PDF / 图片（无文本层时用）。参数：file, start(起始页0基), count(≤5)。",
            {"file": {"type": "string"}, "start": {"type": "integer"}, "count": {"type": "integer"}}, ["file"]),
        _fn("search_text", "在已提取文本中正则检索（首次调用会自动提取全部文本层）。参数：pattern, file(可选限定)。",
            {"pattern": {"type": "string"}, "file": {"type": "string"}}, ["pattern"]),
        _fn("extract_archive", "解压包内嵌套压缩包（zip/tar.gz）到 _extracted/ 目录，解完 list_files 可见。参数：file。",
            {"file": {"type": "string"}}, ["file"]),
    ]
    if stage == "profiling":
        tools.append(_fn(
            "submit_profile",
            "提交结构化档案（直接入档）。要求：1) 姓名取自材料原文；2) 每条教育/经历/论文尽量给出"
            " source（来源文件+页码）；3) 材料没覆盖的字段留空，不要编造；4) 关键结论在 notes 里写明存疑点。",
            _PROFILE_SCHEMA["properties"],
            _PROFILE_SCHEMA["required"],
        ))
    return tools


