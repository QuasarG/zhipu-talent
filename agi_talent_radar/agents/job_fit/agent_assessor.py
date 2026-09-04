"""JD×候选人 评估 agent loop：读本人真实材料 + 督导，产出 job_fit_raw。

替换的是 jd_fit_assessor 的证据采集方式（旧链路是单次模型调用只看结构化
简历，从不读原始材料）；decision_guard（硬门槛确定性裁决）与结果组装
完全不变——评分模式不变。

双 agent 回合结构（编排为确定性代码，两个 LLM 互不直接对话）：
- 评估 agent：每 turn ≤5 轮工具调用；工具=包内文件系统（限量读取）+
  视觉转译 + 论文查证/全网检索 + submit_assessments（终点合同）
- 观察 agent：每 turn 边界必跑（过程台账），action=guide/phase/wrap/silent；
  指导以 [督导] user input 注入
- 硬护栏：MAX_TURNS / 预算耗尽 → 强制收尾 turn（只给 submit_assessments）
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Generator

from agi_talent_radar.agents.job_fit.evaluator import DIMENSIONS
from agi_talent_radar.core.llm_client import call_llm_json, call_llm_tools

logger = logging.getLogger(__name__)

TURN_ROUNDS = int(os.getenv("EVAL_AGENT_TURN_ROUNDS", "5"))
MAX_TURNS = int(os.getenv("EVAL_AGENT_MAX_TURNS", "10"))
PAGE_CHARS = 4000
TOOL_RESULT_MAX_CHARS = 6000

_TOOL_LABELS = {
    "list_files": "盘点材料",
    "read_text": "读取文本",
    "read_pages": "视觉转译",
    "search_text": "检索内容",
    "verify_paper": "论文查证",
    "web_search": "全网检索",
    "submit_assessments": "提交评估",
}


class MaterialsContext:
    """候选人材料目录访问：root + 可选白名单（存量候选人是单一简历原件）。"""

    def __init__(self, root: str, allowed: set[str] | None = None) -> None:
        self.root = os.path.abspath(root)
        self.allowed = {a.replace(os.sep, "/") for a in allowed} if allowed else None
        self.text_cache: dict[str, str] = {}
        self.vision_cache: dict[str, str] = {}

    def resolve(self, rel: str) -> str | None:
        clean = (rel or "").replace("\\", "/").lstrip("/")
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
        out = []
        for root, _dirs, files in os.walk(self.root):
            for f in files:
                out.append(os.path.relpath(os.path.join(root, f), self.root).replace(os.sep, "/"))
        return sorted(out)[:500]


def _suffix(name: str) -> str:
    return ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""


def _system_prompt(resume_dump: dict, jobs: list, ctx: MaterialsContext, academic_report: dict | None) -> str:
    dims = "\n".join(f"- {key}｜{label}｜权重 {weight}%" for key, label, weight in DIMENSIONS)
    jd_list = "\n".join(f"- jd_id={j.id}｜{j.title}\n---- JD 原文 ----\n{j.raw_text[:2000]}" for j in jobs)
    academic = json.dumps(academic_report or {}, ensure_ascii=False)[:1500]
    files = "\n".join(f"- {rel}" for rel in ctx.walk()) or "（无原始材料文件，仅结构化简历可用）"
    return f"""你是人才评估 agent。任务：读取候选人「本人目录」下的真实材料，对照 JD 完成逐岗评估，
最后调用 submit_assessments 提交。证据只能来自材料原文或公开查证，禁止编造。

# 候选人结构化简历（导入时解析，供快速定位；评估依据仍以下方材料为准）
{json.dumps({k: resume_dump.get(k) for k in ("name", "target_role", "stage", "education", "directions", "experiences", "projects", "publications", "skills")}, ensure_ascii=False)[:3000]}

# 论文核验报告（已有）
{academic}

# 候选人材料目录（read_text/read_pages 的 file 参数取这里的相对路径）
{files}

# 目标 JD（每个 jd_id 都必须出现在 submit_assessments.assessments 里）
{jd_list}

# 评估维度（score 0-5，rationale 必须引用具体证据：文件名 第N页/章节）
{dims}

# 工作方式
0. 每次调工具前先用一两句话说明目的（给评审看的）。
1. list_files 盘点 → 逐份 read_text（分页）读关键材料；扫描件/图片用 read_pages 视觉转译；
   大文件先 search_text 定位再精读。
2. 代表作论文可用 verify_paper 查证公开收录情况；必要时 web_search 核查公开信息。
3. 材料读完或督导示意收尾后，为每个 JD 提交：硬性门槛逐条判定（从 JD 原文提取，
   status=met/unmet/unknown + 证据）+ 六维评分（含理由与证据）+ 亮点/风险/面试问题/缺漏信息。
4. 收到 [督导] 开头的 user 消息是评审督导的方向性指令，优先服从。
5. 决策（面试/hold/拒绝）由系统按硬门槛与分数确定性计算，你不提交决策结论。"""


_OBSERVER_PROMPT = """你是人才评估的评审督导 agent。你看到的是评估 agent 的工作过程台账
（读了哪些文件哪些页、查证了什么、处于哪个阶段、剩余预算），看不到原文——职责是审慎观察、把控流程。

# 决策规则（默认 silent）
仅以下情况出手：
- guide：重复读取已读内容 / 漏读关键材料（简历、代表作、成绩单、推荐信）/ 单文件过度逗留 / 前后矛盾
- phase：各 JD 的证据已足够，提示提交
- wrap：剩余轮数不足，要求基于已有信息立即提交
- silent：一切正常
guidance 严禁包含任何具体分数或录用结论。

# 输出 JSON
{"action": "guide|phase|wrap|silent", "guidance": "简短指令（silent 留空）", "reason": "一句话依据"}"""


def run_agent_assessments_stream(
    resume_dump: dict[str, Any],
    jobs: list,
    academic_report: dict[str, Any] | None,
    ctx: MaterialsContext | None,
) -> Generator[dict[str, Any], None, dict[str, Any]]:
    """双 agent 评估循环（生成器）：yield jd_fit_assessor 节点进度事件，
    return 与旧 _request_assessments 同构的 job_fit_raw（供 yield from 捕获）。"""

    system_prompt = _system_prompt(resume_dump, jobs, ctx, academic_report)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "开始评估。先盘点并读取本人材料，逐 JD 完成证据对照后调用 submit_assessments。"},
    ]
    ledger: list[dict[str, str]] = []
    submitted: dict[str, Any] | None = None
    submit_rejections = 0

    def observe(event: dict[str, str]) -> None:
        ledger.append(event)
        if len(ledger) > 120:
            del ledger[:20]

    def _assessments_items_schema() -> dict[str, Any]:
        """submit_assessments.assessments 数组的 item schema（每个 JD 一项）。"""
        return {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "jd_id": {"type": "string"},
                    "hard_requirements": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "requirement": {"type": "string"},
                                "status": {"type": "string", "enum": ["met", "unmet", "unknown"]},
                                "evidence": {"type": "array", "items": {"type": "string"}},
                                "rationale": {"type": "string"},
                            },
                            "required": ["requirement", "status"],
                        },
                    },
                    "dimensions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "key": {"type": "string"},
                                "score": {"type": "number"},
                                "rationale": {"type": "string"},
                                "evidence": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["key", "score", "rationale"],
                        },
                    },
                    "confidence": {"type": "number"},
                    "strengths": {"type": "array", "items": {"type": "string"}},
                    "risks": {"type": "array", "items": {"type": "string"}},
                    "interview_questions": {"type": "array", "items": {"type": "string"}},
                    "missing_information": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["jd_id", "dimensions"],
            },
        }

    def execute_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
        nonlocal submitted, submit_rejections
        if name == "list_files":
            files = ctx.walk()
            return {"summary": f"{len(files)} 个文件", "detail": {"files": files}}
        if name == "read_text":
            rel = str(args.get("file") or "")
            text = ctx.text_cache.get(rel)
            if text is None:
                text = _extract_text_layer(ctx, rel)
            page = max(0, int(args.get("page") or 0))
            chunk = text[page * PAGE_CHARS:(page + 1) * PAGE_CHARS]
            if not chunk:
                return {"summary": f"{rel} 无文本层", "detail": {"error": "无文本层（扫描件/图片用 read_pages 视觉转译）或超出范围"}}
            return {
                "summary": f"{rel} 第 {page + 1}/{max(1, (len(text) + PAGE_CHARS - 1) // PAGE_CHARS)} 段（{len(chunk)} 字）",
                "detail": {"file": rel, "page": page, "total_pages": max(1, (len(text) + PAGE_CHARS - 1) // PAGE_CHARS), "text": chunk},
            }
        if name == "read_pages":
            return _tool_read_pages(ctx, args)
        if name == "search_text":
            return _tool_search_text(ctx, args)
        if name == "verify_paper":
            from agi_talent_radar.scholarship.scorer_tools import _tool_verify_paper

            out = _tool_verify_paper(args)
            return {"summary": out.get("summary", ""), "detail": out.get("detail", {})}
        if name == "web_search":
            query = str(args.get("query") or "").strip()
            if not query:
                return {"summary": "查询为空", "detail": {"results": []}}
            try:
                from agi_talent_radar.core.connectors.web_search import search_web

                facts = search_web(query, count=5) or []
            except Exception as exc:  # noqa: BLE001
                return {"summary": "检索失败", "detail": {"error": str(exc)[:200]}}
            items = [{"title": str((f.payload or {}).get("title") or ""), "url": f.source_url or "",
                      "snippet": str((f.payload or {}).get("content") or "")[:200]} for f in facts]
            return {"summary": f"{len(items)} 条结果", "detail": {"query": query, "results": items}}
        if name == "submit_assessments":
            error = _validate_assessments(jobs, args)
            if error:
                submit_rejections += 1
                return {"summary": "提交被驳回，需修正后重交", "detail": {"error": error}}
            submitted = {"assessments": args.get("assessments") or []}
            return {"summary": "评估已受理", "detail": {"accepted": True}}
        return {"summary": f"未知工具 {name}", "detail": {"error": "当前不可用"}}

    def tools_schema() -> list[dict[str, Any]]:
        def _fn(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
            return {"type": "function", "function": {
                "name": name, "description": description,
                "parameters": {"type": "object", "properties": properties, "required": required},
            }}

        tools = [
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
            _fn("submit_assessments", "提交逐 JD 评估（终点合同，所有 jd_id 必须齐全）。",
                {"type": "object", "properties": {"assessments": _assessments_items_schema()},
                 "required": ["assessments"]}, ["assessments"]),
        ]
        return tools

    try:
        forced = False
        for turn_no in range(1, MAX_TURNS + 1):
            for _round in range(TURN_ROUNDS):
                result = call_llm_tools(
                    messages, tools_schema(), temperature=0.2,
                    reasoning_effort=os.getenv("OPENAI_EFFORT_SCORING", "high"),
                )
                text = (result.get("text") or "").strip()
                tool_calls = result.get("tool_calls") or []
                if not tool_calls and not text:
                    break
                messages.append({
                    "role": "assistant",
                    "content": result.get("text") or "",
                    "tool_calls": [
                        {"id": tc["id"], "type": "function",
                         "function": {"name": tc["name"], "arguments": tc["arguments"]}}
                        for tc in tool_calls
                    ],
                })
                for tc in tool_calls:
                    try:
                        args = json.loads(tc.get("arguments") or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    label = _TOOL_LABELS.get(tc["name"], tc["name"])
                    output = execute_tool(tc["name"], args)
                    summary = str(output.get("summary") or "完成")
                    detail = json.dumps(output.get("detail"), ensure_ascii=False, default=str)
                    yield {"type": "node", "node": "jd_fit_assessor", "label": "逐 JD 证据对照",
                           "status": "running", "phase": "assessment", "message": f"{label}：{summary}"}
                    observe({"kind": "tool", "tool": tc["name"], "args": json.dumps(args, ensure_ascii=False)[:120], "summary": summary})
                    messages.append({"role": "tool", "tool_call_id": tc["id"], "content": detail[:TOOL_RESULT_MAX_CHARS]})
                    if submitted is not None:
                        break
                if submitted is not None:
                    break
                if not tool_calls:
                    break

            if submitted is not None:
                break
            if submit_rejections >= 3:
                raise RuntimeError("submit_assessments 连续驳回超过 3 次")

            # ---- 观察 agent 决策 ----
            decision: dict[str, Any] = {"action": "silent"}
            try:
                decision = call_llm_json(_OBSERVER_PROMPT, {
                    "turn": f"{turn_no}/{MAX_TURNS}",
                    "read_files": {k: sorted(v)[:12] for k, v in list(ctx.vision_cache.items())[:0]} or {
                        rel: True for rel in list(ctx.text_cache)[:40]},
                    "extract_rounds": ctx.extract_rounds if hasattr(ctx, "extract_rounds") else 0,
                    "ledger": ledger[-80:],
                }, temperature=0.1)
            except Exception as exc:  # noqa: BLE001 — 观察者失败降级为继续
                logger.warning("评估督导 agent 失败：%s", exc)
            action = str(decision.get("action") or "silent")
            guidance = str(decision.get("guidance") or "").strip()
            observe({"kind": "observer", "action": action, "guidance": guidance[:200],
                     "reason": str(decision.get("reason") or "")[:200]})

            if forced or turn_no >= MAX_TURNS - 1 or action == "wrap":
                messages.append({"role": "user",
                                 "content": "[系统] 预算即将耗尽。不要再调用其他工具，立即基于已收集信息调用 submit_assessments（未覆盖部分在 evidence/rationale 注明依据不足）。"})
                forced = True
            elif action in ("guide", "phase") and guidance:
                messages.append({"role": "user", "content": f"[督导] {guidance}"})
            else:
                messages.append({"role": "user", "content": "继续。"})

        if submitted is None:
            raise RuntimeError(f"评估 agent 未能在预算内提交（{MAX_TURNS} turns）")
        return submitted
    except Exception:
        raise


def _validate_assessments(jobs: list, data: dict[str, Any]) -> str:
    """终点硬校验：所有 jd_id 齐全、六维齐全且 0-5。错误文案回填给 agent 重交。"""
    items = data.get("assessments") or []
    by_id = {str(i.get("jd_id") or ""): i for i in items if isinstance(i, dict)}
    missing = [j.id for j in jobs if j.id not in by_id]
    if missing:
        return f"缺少 JD 评估：{', '.join(missing)}"
    extra = [k for k in by_id if k not in {j.id for j in jobs}]
    if extra:
        return f"存在未知 jd_id：{', '.join(extra)}"
    dim_keys = {key for key, _label, _weight in DIMENSIONS}
    for j in jobs:
        item = by_id[j.id]
        dims = {str(d.get("key") or ""): d for d in item.get("dimensions") or [] if isinstance(d, dict)}
        miss = [k for k in dim_keys if k not in dims]
        if miss:
            return f"JD {j.id} 缺少维度：{', '.join(miss)}"
        for key, dim in dims.items():
            raw_score = dim.get("score")
            try:
                score = float(raw_score)
            except (TypeError, ValueError):
                return f"JD {j.id} 维度 {key} 的 score 不是数字（收到 {raw_score!r}）"
            if not 0 <= score <= 5:
                return f"JD {j.id} 维度 {key} 的 score 超出 0-5：{score}"
            if len(str(dim.get("rationale") or "")) < 8:
                return f"JD {j.id} 维度 {key} 的 rationale 过短，必须引用具体材料证据"
    return ""


def _extract_text_layer(ctx: MaterialsContext, rel: str) -> str:
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
            elif suffix in {".txt", ".md", ".csv", ".json", ".log", ".html"}:
                with open(path, "rb") as fp:
                    text = fp.read(2_000_000).decode("utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001
            logger.warning("材料文字层提取失败 %s：%s", rel, exc)
    ctx.text_cache[rel] = text
    return text


def _tool_read_pages(ctx: MaterialsContext, args: dict[str, Any]) -> dict[str, Any]:
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


def _tool_search_text(ctx: MaterialsContext, args: dict[str, Any]) -> dict[str, Any]:
    import re

    pattern = str(args.get("pattern") or "").strip()
    if not pattern:
        return {"summary": "pattern 为空", "detail": {"hits": []}}
    scoped = str(args.get("file") or "").strip()
    targets = [scoped] if scoped else ctx.walk()
    try:
        rx = re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        return {"summary": "正则非法", "detail": {"error": str(exc)[:200]}}
    hits = []
    for rel in targets:
        text = ctx.text_cache.get(rel)
        if text is None:
            text = _extract_text_layer(ctx, rel)
        if not text:
            continue
        for m in rx.finditer(text):
            if len(hits) >= 40:
                break
            hits.append({"file": rel, "context": text[max(0, m.start() - 60):m.end() + 60]})
        if len(hits) >= 40:
            break
    return {"summary": f"{len(hits)} 处命中", "detail": {"pattern": pattern, "hits": hits}}
