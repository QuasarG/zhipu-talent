"""候选人本人材料的共享访问层：目录沙箱、文本层提取、视觉转译、检索、JSON 解析。

评审团（panel.py）与工具 schema 共用这一层；文件访问全部收敛在
MaterialsContext 的白名单 + 路径规范化约束内，禁止越出候选人目录。
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

PAGE_CHARS = 4000
TOOL_RESULT_MAX_CHARS = 6000


class MaterialsContext:
    """候选人材料目录访问：root + 可选白名单（存量候选人是单一简历原件）。"""

    def __init__(self, root: str, allowed: set[str] | None = None) -> None:
        self.root = os.path.abspath(root)
        self.allowed = {a.replace(os.sep, "/") for a in allowed} if allowed else None
        self.text_cache: dict[str, str] = {}
        self.vision_cache: dict[str, str] = {}

    def resolve(self, rel: str) -> str | None:
        clean = (rel or "").replace("\\", "/").lstrip("/")
        if ".." in clean.split("/"):
            return None
        parts = [p for p in clean.split("/") if p not in ("", ".", "..")]
        if not parts:
            return None
        rel_norm = "/".join(parts)
        if self.allowed is not None and rel_norm not in self.allowed:
            return None
        target = os.path.join(self.root, *parts)
        if not os.path.abspath(target).startswith(os.path.abspath(self.root) + os.sep):
            return None
        return target if os.path.isfile(target) else None

    def walk(self) -> list[str]:
        if self.allowed is not None:
            return sorted(self.allowed)
        out: list[str] = []
        for root, _dirs, files in os.walk(self.root):
            for f in files:
                out.append(os.path.relpath(os.path.join(root, f), self.root).replace(os.sep, "/"))
        return sorted(out)[:500]


def _suffix(name: str) -> str:
    return ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""


def extract_text_layer(ctx: MaterialsContext, rel: str) -> str:
    """惰性提取文字层（pdf 文字层/docx/txt），按文件缓存；扫描件留空走 read_pages。"""
    if rel in ctx.text_cache:
        return ctx.text_cache[rel]
    path = ctx.resolve(rel)
    text = ""
    if path:
        suffix = _suffix(rel)
        try:
            if suffix == ".pdf":
                import fitz

                doc = fitz.open(path)
                try:
                    pages = []
                    for index, page in enumerate(doc, start=1):
                        part = page.get_text("text").strip()
                        if part:
                            pages.append(f"[第 {index} 页]\n{part}")
                    text = "\n\n".join(pages)
                finally:
                    doc.close()
            elif suffix == ".docx":
                import mammoth

                with open(path, "rb") as fp:
                    text = str(mammoth.extract_raw_text(fp).value or "")
            elif suffix in {".txt", ".md", ".csv", ".json", ".jsonl", ".log", ".html"}:
                with open(path, "rb") as fp:
                    text = fp.read(2_000_000).decode("utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001
            logger.warning("材料文字层提取失败 %s：%s", rel, exc)
    ctx.text_cache[rel] = text
    return text


def tools_schema() -> list[dict[str, Any]]:
    def _fn(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
        return {"type": "function", "function": {
            "name": name, "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        }}

    return [
        _fn("list_files", "列出本人材料目录全部文件（相对路径/大小）。", {}, []),
        _fn("read_text", f"按段读取文件可提取文本（每段约{PAGE_CHARS}字）。参数：file, page(0基)。",
            {"file": {"type": "string"}, "page": {"type": "integer"}}, ["file"]),
        _fn("read_pages", "视觉转译读取扫描件 PDF/图片（无文本层时用）。参数：file, start(0基), count(≤5)。",
            {"file": {"type": "string"}, "start": {"type": "integer"}, "count": {"type": "integer"}}, ["file"]),
        _fn("search_text", "在已提取文本中正则检索。参数：pattern, file(可选)。",
            {"pattern": {"type": "string"}, "file": {"type": "string"}}, ["pattern"]),
        _fn("verify_paper", "按标题在公开学术库查证论文。参数：title。",
            {"title": {"type": "string"}}, ["title"]),
        _fn("web_search", "全网检索公开信息。参数：query。",
            {"query": {"type": "string"}}, ["query"]),
    ]


def tool_read_pages(ctx: MaterialsContext | None, args: dict[str, Any]) -> dict[str, Any]:
    if ctx is None:
        return {"summary": "无材料目录", "detail": {"error": "该候选人没有原始材料文件"}}
    rel = str(args.get("file") or "")
    path = ctx.resolve(rel)
    if not path or not os.path.isfile(path):
        return {"summary": f"{rel} 不存在", "detail": {"error": "file 不在 list_files 结果里"}}
    suffix = _suffix(rel)
    from agi_talent_radar.scholarship.scorer_tools import _VISION_MODEL, _vision_client

    transcribe = "请把这一页的内容客观转成文字，列出可核查的关键信息（人名/机构/指标/结论/时间线），不要评价。"
    try:
        if suffix == ".pdf":
            import base64

            import fitz

            doc = fitz.open(path)
            try:
                total = doc.page_count
                start = max(0, int(args.get("start") or 0))
                count = min(5, max(1, int(args.get("count") or 3)))
                parts = []
                for index in range(start, min(total, start + count)):
                    pixmap = doc[index].get_pixmap(matrix=fitz.Matrix(150 / 72, 150 / 72), alpha=False)
                    resp = _vision_client().chat.completions.create(
                        model=_VISION_MODEL,
                        messages=[{"role": "user", "content": [
                            {"type": "image_url", "image_url": {"url": base64.b64encode(pixmap.tobytes("png")).decode()}},
                            {"type": "text", "text": f"第 {index + 1}/{total} 页。{transcribe}"},
                        ]}],
                        temperature=0.1,
                        timeout=120,
                    )
                    parts.append(f"[第 {index + 1} 页]\n" + (resp.choices[0].message.content or ""))
                text = "\n\n".join(parts)
            finally:
                doc.close()
        elif suffix in {".png", ".jpg", ".jpeg", ".webp"}:
            import base64

            with open(path, "rb") as fp:
                b64 = base64.b64encode(fp.read()).decode()
            resp = _vision_client().chat.completions.create(
                model=_VISION_MODEL,
                messages=[{"role": "user", "content": [
                    {"type": "image_url", "image_url": {"url": b64}},
                    {"type": "text", "text": transcribe},
                ]}],
                temperature=0.1,
                timeout=120,
            )
            text = resp.choices[0].message.content or ""
        else:
            return {"summary": "不支持视觉读取", "detail": {"error": "read_pages 仅用于扫描件 PDF 与图片"}}
    except Exception as exc:  # noqa: BLE001
        return {"summary": "视觉转译失败", "detail": {"error": str(exc)[:300]}}
    ctx.vision_cache[rel] = ctx.vision_cache.get(rel, "") + text
    ctx.text_cache[rel] = ctx.text_cache.get(rel, "") + text
    return {"summary": f"{rel} 视觉转译 {len(text)} 字", "detail": {"file": rel, "text": text[:TOOL_RESULT_MAX_CHARS]}}


def tool_search_text(ctx: MaterialsContext | None, args: dict[str, Any]) -> dict[str, Any]:
    pattern = str(args.get("pattern") or "").strip()
    if not pattern or ctx is None:
        return {"summary": "pattern 为空", "detail": {"hits": []}}
    scoped = str(args.get("file") or "").strip()
    targets = [scoped] if scoped else ctx.walk()
    try:
        rx = re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        return {"summary": "正则非法", "detail": {"error": str(exc)[:200]}}
    hits = []
    for rel in targets:
        text = extract_text_layer(ctx, rel)
        if not text:
            continue
        for m in rx.finditer(text):
            if len(hits) >= 40:
                break
            hits.append({"file": rel, "context": text[max(0, m.start() - 60):m.end() + 60]})
        if len(hits) >= 40:
            break
    return {"summary": f"{len(hits)} 处命中", "detail": {"pattern": pattern, "hits": hits}}


def parse_json_block(text: str) -> dict[str, Any] | None:
    """解析 LLM 输出的 JSON 对象：剥 markdown 围栏 + json_repair 兜底。"""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```$", "", cleaned).strip()
    try:
        data = json.loads(cleaned)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass
    try:
        from json_repair import loads as repair_loads

        data = repair_loads(cleaned)
        return data if isinstance(data, dict) else None
    except Exception:  # noqa: BLE001
        return None
