"""评分 agent 工具层：list_files / read_file / verify_paper / web_search / submit_scores。

设计要点：
- read_file 是统一入口：文本→脱敏原文分页；图片/扫描件/视频→GLM 视觉
  转译成结构化文字描述，描述同样过 anonymize+check_leak 脱敏闸门——
  视觉模型是翻译官不是评审员，agent 全程只看脱敏文本，盲评红线不破。
- verify_paper 只回 venue/年份/引用（剥作者），身份不进 agent 循环。
- submit_scores 程序侧硬校验（维度齐全/分数范围/证据分级合法），
  不合格把错误作为工具结果回填，agent 必须重交。
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Callable

from agi_talent_radar.scholarship.anonymize import anonymize_text, build_identities, check_leak
from agi_talent_radar.scholarship.scoring import DIMENSIONS, EVIDENCE_LEVELS, RECOMMEND_TIERS

logger = logging.getLogger(__name__)

# 视觉转译模型：实测该 key 上 GLM-5.3-Flash 可用（驼峰名 1214 不存在），可 env 覆盖
_VISION_MODEL = os.getenv("SCORER_VISION_MODEL", "GLM-5.3-Flash")
PAGE_CHARS = 4000          # read_file 文本分页
TOOL_RESULT_MAX_CHARS = 6000
MAX_ROUNDS = 20

# 多模态格式：read_file 走视觉转译
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
_VIDEO_SUFFIXES = {".mp4", ".webm", ".mov", ".mkv"}
# 文字层可能很薄的文档（扫描件）也走视觉
_VISUAL_DOC_SUFFIXES = {".pdf"}


class ScorerContext:
    """一次评分的执行上下文：申请人材料、脱敏身份表、证据登记、终态。"""

    def __init__(self, app, materials, public_base_url: str = "") -> None:
        self.app = app
        self.materials = materials
        self.identities = build_identities(app)
        self.public_base_url = public_base_url.rstrip("/")
        self.final: dict[str, Any] | None = None
        self.read_ids: set[int] = set()


def _suffix(filename: str) -> str:
    return ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""


def _scrub(text: str, ctx: ScorerContext) -> str:
    """脱敏闸门：替换 + 泄漏残留抹除。所有喂给 agent 的文本必须过这里。"""
    out = anonymize_text(text or "", ctx.identities)
    for leak in check_leak(out, ctx.identities):
        out = out.replace(leak, "[已脱敏]")
    return out


def _fmt_material(m) -> dict[str, Any]:
    suffix = _suffix(m.filename or "")
    if suffix in _VIDEO_SUFFIXES:
        form = "视频"
    elif suffix in _IMAGE_SUFFIXES:
        form = "图片"
    elif suffix == ".docx":
        form = "文档(docx)"
    elif suffix == ".pdf":
        form = "PDF"
    else:
        form = "文本"
    return {
        "file_id": m.id,
        "kind": m.kind,               # form/resume/letter/achievement
        "filename": m.filename,
        "form": form,
        "chars": len(m.raw_text or ""),
    }


def _vision_describe(path: str, filename: str, ctx: ScorerContext) -> str:
    """图片/视频 → 视觉模型结构化文字描述（脱敏后）。失败返回错误占位。"""
    suffix = _suffix(filename)
    try:
        if suffix in _VIDEO_SUFFIXES:
            return _vision_video(path, filename)
        if suffix == ".pdf":
            return _vision_pdf(path)
        return _vision_image(path)
    except Exception as exc:  # noqa: BLE001 — 视觉失败不阻断，agent 会看到占位
        logger.warning("视觉转译失败 %s：%s", filename, exc)
        return f"[视觉转译失败：{exc}]"


def _vision_client():
    import zai

    api_key = (os.getenv("LLM_API_KEY") or os.getenv("Z_AI_API_KEY", "")).strip()
    if not api_key:
        raise RuntimeError("未配置 LLM_API_KEY，视觉转译不可用")
    return zai.ZhipuAiClient(api_key=api_key)


_VISION_PROMPT = (
    "你是评审材料的内容转译员。请把这份材料的内容客观转成文字描述，供后续匿名评审使用。"
    "要求：1) 描述材料类型与主要内容；2) 列出可核查的关键信息（论文标题/venue/数据指标/"
    "系统演示内容与效果/时间线）；3) 严禁输出任何真实人名、单位名、logo 文字——"
    "一律写成 [人名]/[单位]；4) 不做任何评价打分，只转述事实。"
)


def _vision_image(path: str) -> str:
    import base64

    with open(path, "rb") as fp:
        b64 = base64.b64encode(fp.read()).decode()
    resp = _vision_client().chat.completions.create(
        model=_VISION_MODEL,
        messages=[{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": b64}},
            {"type": "text", "text": _VISION_PROMPT},
        ]}],
        temperature=0.1,
    )
    return resp.choices[0].message.content or ""


def _vision_pdf(path: str) -> str:
    """PDF 文字层薄时整本转译：每页渲染成图逐页描述（页数多时采样）。"""
    import fitz

    doc = fitz.open(path)
    try:
        total = doc.page_count
        indices = list(range(total)) if total <= 8 else sorted(
            set([0, total // 4, total // 2, 3 * total // 4, total - 1] + list(range(0, total, 6)))
        )
        parts = []
        for i in indices:
            pixmap = doc[i].get_pixmap(matrix=fitz.Matrix(150 / 72, 150 / 72), alpha=False)
            b64 = pixmap.tobytes("png")
            import base64

            resp = _vision_client().chat.completions.create(
                model=_VISION_MODEL,
                messages=[{"role": "user", "content": [
                    {"type": "image_url", "image_url": {"url": base64.b64encode(b64).decode()}},
                    {"type": "text", "text": f"第 {i + 1}/{total} 页。{_VISION_PROMPT}"},
                ]}],
                temperature=0.1,
            )
            parts.append(f"[第 {i + 1} 页]\n" + (resp.choices[0].message.content or ""))
        return f"（共 {total} 页，转译其中 {len(indices)} 页）\n\n" + "\n\n".join(parts)
    finally:
        doc.close()


def _vision_video(path: str, filename: str) -> str:
    """视频 → 视觉模型 video_url。本机文件经签名临时 URL 供 API 拉取。"""
    url = _video_url(path)
    resp = _vision_client().chat.completions.create(
        model=_VISION_MODEL,
        messages=[{"role": "user", "content": [
            {"type": "video_url", "video_url": {"url": url}},
            {"type": "text", "text": _VISION_PROMPT},
        ]}],
        temperature=0.1,
    )
    return resp.choices[0].message.content or ""


def _video_url(path: str) -> str:
    """生成视频的公网可访问 URL（materials-file 端点 + webhook token 自证）。"""
    host = os.getenv("PUBLIC_VIDEO_HOST", "").strip()
    if not host:
        raise RuntimeError("视频转译需配置 PUBLIC_VIDEO_HOST（材料目录的公网可访问地址）")
    import urllib.parse

    name = os.path.basename(path)
    token = os.getenv("SCHOLARSHIP_WEBHOOK_TOKEN", "").strip()
    scheme = "https" if os.getenv("PUBLIC_VIDEO_HTTPS") else "http"
    return f"{scheme}://{host}/api/scholarship/materials-file/{urllib.parse.quote(name)}?token={urllib.parse.quote(token)}"


# ---------------------------------------------------------------------------
# 工具注册表（schema 与 knowledge_agent.tools 同构，方便前端复用渲染）
# ---------------------------------------------------------------------------


def tools_schema() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "list_files",
                "description": "列出申请人提交的全部材料文件（id/类型/文件名/形式/字数）。",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": (
                    "读取一份具体材料。文本材料返回脱敏原文（分页，每页约4000字）；"
                    "图片/扫描件/视频由视觉模型转译为内容描述。参数：file_id（来自 list_files），"
                    "page（可选，从0开始）。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_id": {"type": "integer"},
                        "page": {"type": "integer"},
                    },
                    "required": ["file_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "verify_paper",
                "description": (
                    "按论文标题在公开学术库查证（AMiner/arXiv）。返回 找到/未找到 + venue + 年份。"
                    "用于证据分级：查到=verified，未查到需看佐证材料定 supported/claimed。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {"title": {"type": "string"}},
                    "required": ["title"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": (
                    "全网检索（舆情/公开报道）。用于核查申请人与导师的公开负面信息及重大荣誉。"
                    "注意：结果只作风险标注，不直接改分。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "submit_scores",
                "description": (
                    "提交最终评分。每个维度：score(0-5) + reason（必须引用具体证据并标注证据分级"
                    "verified/supported/claimed）。另附 highlights/risks/recommend_tier/"
                    "reputation_findings（舆情发现，供人工参考）。提交前必须已读过全部材料。"
                ),
                "parameters": _submit_schema(),
            },
        },
    ]


def _submit_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "dimensions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},
                        "score": {"type": "number"},
                        "reason": {"type": "string"},
                        "evidence_level": {"type": "string", "enum": list(EVIDENCE_LEVELS)},
                    },
                    "required": ["key", "score", "reason"],
                },
            },
            "highlights": {"type": "array", "items": {"type": "string"}},
            "risks": {"type": "array", "items": {"type": "string"}},
            "recommend_tier": {"type": "string", "enum": RECOMMEND_TIERS},
            "reputation_findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "subject": {"type": "string"},
                        "sentiment": {"type": "string"},
                        "title": {"type": "string"},
                        "url": {"type": "string"},
                        "note": {"type": "string"},
                    },
                    "required": ["subject", "sentiment", "title", "url"],
                },
            },
        },
        "required": ["dimensions", "recommend_tier"],
    }


def execute_tool(ctx: ScorerContext, name: str, args: dict[str, Any]) -> dict[str, Any]:
    """执行一个工具，返回 {summary, detail}（detail 截断后喂回 LLM）。"""
    if name == "list_files":
        files = [_fmt_material(m) for m in ctx.materials]
        return {"summary": f"{len(files)} 份材料", "detail": {"files": files}}
    if name == "read_file":
        return _tool_read_file(ctx, args)
    if name == "verify_paper":
        return _tool_verify_paper(args)
    if name == "web_search":
        return _tool_web_search(ctx, args)
    if name == "submit_scores":
        return _tool_submit(ctx, args)
    return {"summary": f"未知工具 {name}", "detail": {}}


def _tool_read_file(ctx: ScorerContext, args: dict[str, Any]) -> dict[str, Any]:
    try:
        file_id = int(args.get("file_id"))
    except (TypeError, ValueError):
        return {"summary": "file_id 无效", "detail": {"error": "file_id 必须是整数"}}
    m = next((x for x in ctx.materials if x.id == file_id), None)
    if m is None:
        return {"summary": f"文件 {file_id} 不存在", "detail": {"error": "file_id 不在 list_files 结果里"}}
    ctx.read_ids.add(file_id)
    suffix = _suffix(m.filename or "")
    page = int(args.get("page") or 0)
    raw = m.raw_text or ""
    if suffix in _VIDEO_SUFFIXES or (suffix in _IMAGE_SUFFIXES) or (
        suffix in _VISUAL_DOC_SUFFIXES and len(raw.strip()) < 120
    ):
        path = (m.file_path or "").strip()
        if not path or not os.path.isfile(path):
            return {"summary": "原始文件缺失", "detail": {"error": "该材料没有原始文件，仅有提取文本", "text": _scrub(raw, ctx)[:PAGE_CHARS]}}
        described = _scrub(_vision_describe(path, m.filename or "", ctx), ctx)
        return {
            "summary": f"{m.filename}（视觉转译）",
            "detail": {"kind": m.kind, "filename": m.filename, "vision_description": described[:TOOL_RESULT_MAX_CHARS]},
        }
    text = _scrub(raw, ctx)
    start = page * PAGE_CHARS
    chunk = text[start:start + PAGE_CHARS]
    if not chunk:
        return {"summary": f"{m.filename} 第 {page} 页为空", "detail": {"kind": m.kind, "filename": m.filename, "text": ""}}
    return {
        "summary": f"{m.filename} 第 {page + 1} 页（{len(chunk)} 字）",
        "detail": {
            "kind": m.kind, "filename": m.filename,
            "page": page, "total_pages": max(1, (len(text) + PAGE_CHARS - 1) // PAGE_CHARS),
            "text": chunk,
        },
    }


def _tool_verify_paper(args: dict[str, Any]) -> dict[str, Any]:
    title = str(args.get("title") or "").strip()
    if not title:
        return {"summary": "标题为空", "detail": {"found": False, "note": "title 不能为空"}}
    try:
        from agi_talent_radar.core.connectors.paper_search import search_papers_federated_merged

        results = search_papers_federated_merged(title, count=5) or []
    except Exception as exc:  # noqa: BLE001 — 查证失败按未找到处理，不阻断
        logger.warning("论文查证失败：%s", exc)
        return {"summary": "查证服务异常", "detail": {"found": False, "note": f"检索失败：{exc}"[:200]}}
    # 已按标题相似度排序，首位即最佳候选；剥作者不返回
    facts = [
        {
            "title": str((f.payload or {}).get("title") or ""),
            "venue": str((f.payload or {}).get("venue") or (f.payload or {}).get("source") or ""),
            "year": (f.payload or {}).get("year"),
            "citations": (f.payload or {}).get("citations"),
        }
        for f in results
    ]
    best = next((f for f in facts if f["title"]), None)
    if best is None:
        return {"summary": "未找到", "detail": {"found": False, "query": title}}
    title_low = re.sub(r"\s+", " ", title.lower())
    best_low = re.sub(r"\s+", " ", best["title"].lower())
    similar = title_low in best_low or best_low in title_low
    return {
        "summary": f"{'找到' if similar else '仅相似匹配'}：{best['venue'] or '未知来源'}",
        "detail": {
            "found": True,
            "best": best,
            "similar": similar,
            "other_candidates": facts[1:3],
            "note": "" if similar else "标题不完全一致，请核对是否同一篇",
        },
    }


def _tool_web_search(ctx: ScorerContext, args: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get("query") or "").strip()
    if not query:
        return {"summary": "查询为空", "detail": {"results": []}}
    try:
        from agi_talent_radar.core.connectors.web_search import search_web

        facts = search_web(query, count=5) or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("舆情检索失败：%s", exc)
        return {"summary": "检索失败", "detail": {"results": [], "error": str(exc)[:200]}}
    items = [
        {"title": str((f.payload or {}).get("title") or ""), "url": f.source_url or "",
         "snippet": str((f.payload or {}).get("content") or "")[:200]}
        for f in facts
    ]
    # 检索词与结果同样过脱敏闸门：query 含申请人/导师姓名，trace 是可展示物
    safe_query = _scrub(query, ctx)
    safe_items = [{"title": _scrub(i["title"], ctx), "url": i["url"], "snippet": _scrub(i["snippet"], ctx)} for i in items]
    return {"summary": f"{len(safe_items)} 条结果", "detail": {"query": safe_query, "results": safe_items}}


def _tool_submit(ctx: ScorerContext, args: dict[str, Any]) -> dict[str, Any]:
    error = _validate_final(ctx, args)
    if error:
        return {"summary": "提交被驳回，需修正后重交", "detail": {"error": error}}
    ctx.final = {
        "dimensions": args.get("dimensions") or [],
        "highlights": [str(x) for x in (args.get("highlights") or [])][:8],
        "risks": [str(x) for x in (args.get("risks") or [])][:8],
        "recommend_tier": str(args.get("recommend_tier") or ""),
        "reputation_findings": args.get("reputation_findings") or [],
    }
    return {"summary": "评分已受理", "detail": {"accepted": True}}



def _coerce_score(raw: Any) -> float | None:
    """LLM 有时把 score 写成字符串或带回车等脏字符；容错转 float，失败 None。"""
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw or "").strip()
    text = "".join(text.split())  # 去掉所有空白（含 \r\n\t）
    try:
        return float(text)
    except ValueError:
        return None

def _validate_final(ctx: ScorerContext, data: dict[str, Any]) -> str:
    """终态硬校验：返回错误文案（空串=通过）。"""
    dims = data.get("dimensions") or []
    by_key = {}
    for d in dims:
        key = str(d.get("key") or "")
        spec = next((x for x in DIMENSIONS if x["key"] == key), None)
        score = _coerce_score(d.get("score"))
        if score is None:
            return f"维度 {key} 的 score 不是数字（收到 {d.get('score')!r}，请提交纯数字如 4.5）"
        d["score"] = score  # 回写清洗后的值，_finalize 直接可用
        # 诚信维度按锚点用 0-10，其余 0-5
        hi = 10.0 if spec and spec["key"] == "integrity_risk" else 5.0
        if not 0 <= score <= hi:
            return f"维度 {key} 的 score 超出 0-{hi:.0f}：{score}"
        reason = str(d.get("reason") or "")
        if len(reason) < 8:
            return f"维度 {key} 的 reason 过短，必须引用具体证据"
        level = str(d.get("evidence_level") or "")
        if level and level not in EVIDENCE_LEVELS:
            return f"维度 {key} 的 evidence_level 非法：{level}"
        by_key[key] = d
    missing = [d["key"] for d in DIMENSIONS if d["key"] not in by_key]
    if missing:
        return f"缺少维度：{', '.join(missing)}"
    tier = str(data.get("recommend_tier") or "")
    if tier not in RECOMMEND_TIERS:
        return f"recommend_tier 非法：{tier}"
    unread = [m.filename for m in ctx.materials if m.id not in ctx.read_ids]
    if unread:
        return "以下材料尚未读取，读完才能提交：" + "、".join(unread[:6]) + ("等" if len(unread) > 6 else "")
    return ""
