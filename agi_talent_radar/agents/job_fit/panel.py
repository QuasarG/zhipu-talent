"""评审团（panel）评估：主席动态派 mission + 类型化评审员，产出 job_fit_raw。

三段结构（docs/design/panel-evaluation.md）：
- 整备（确定性）：案卷目录 dossier + 文本层预热缓存
- 评审循环：主席每轮 call_llm_json 二选一——dispatch（派 1..N 个 mission）/
  synthesize（收队交逐 JD 定性字段）；mission 由类型化评审员执行（新 context
  或按 mission_id 续派暂存会话），findings 走独立 JSON 通道 + 引文反查
- 装配（确定性）：findings 按 jd_id/维度归并成 job_fit_raw；分数只来自
  mission，主席碰不了分。decision_guard / formatter 复用原节点——评分合同不变。

GLM 1210 规避：主席不用 function-calling（纯 JSON 决策）；评审员工具轮只用
简单 schema；提交全部走 JSON 通道。
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Generator

from agi_talent_radar.agents.job_fit.agent_assessor import (
    PAGE_CHARS,
    MaterialsContext,
    _extract_text_layer,
    _parse_json_block,
    _tool_read_pages,
    _tool_search_text,
    tools_schema,
)
from agi_talent_radar.agents.job_fit.evaluator import DIMENSIONS

logger = logging.getLogger(__name__)

FILE_LIST_MAX = 500
DIGEST_CHARS = 300          # 主席看到的单 mission findings 摘要上限
LEAD_RETRIES = 2            # 主席非法 JSON 重试
FINDINGS_RETRIES = 2        # 评审员 findings 打回重试

EVIDENCE_WEIGHTS = {"verified": 1.0, "supported": 0.6, "claimed": 0.2, "unverifiable": 0.1}
MISSING_DIM_SCORE = 2.0     # 缺维保守缺省（绝不补 0——0 分会把人错误推向 reject）
NO_VERIFY_SCORE = 2.5       # 简历有论文/奖项但未派 verify 的缺省

# ---------------------------------------------------------------------------
# mission 类型注册表：类型 = 工具白名单 + 轮数预算 + 提示词模板 + findings 合同。
# 加工种 = 加一个条目，执行循环零改动。
# ---------------------------------------------------------------------------

_SCHEMA_DIMS = '{"key": "维度key", "score": 0-5, "rationale": "引用具体证据", "evidence": ["文件名 第N页: 原文"]}'
_SCHEMA_HARD_REQ = '{"requirement": "JD 明确必备条件", "status": "met|unmet|unknown", "evidence": ["结构化简历原文"], "rationale": "判断理由"}'

TYPE_REGISTRY: dict[str, dict[str, Any]] = {
    "verify": {
        "tools": ("read_text", "read_pages", "verify_paper", "web_search"),
        "rounds": 6,
        "role": "证据查证评审员。只负责核真伪：对主席给出的待核验 claims（论文/奖项/录用等）逐条查证。",
        "findings_schema": '{"claims": [{"claim": "待核验主张", "verdict": "verified|supported|claimed|unverifiable", "source": "公开库名/URL 或材料文件名", "quote": "支撑该结论的原文引句"}]}',
        "findings_rules": "verdict 判据：公开学术库/权威源可检索=verified；有材料佐证但无公开源=supported；仅自述或截图=claimed；无法判断=unverifiable。查不到只能标 claimed/unverifiable，禁止推测。",
    },
    "deep_read": {
        "tools": ("read_text", "read_pages", "search_text"),
        "rounds": 8,
        "role": "深读评审员。分页精读主席指定的材料，对指定维度给出评分与证据。",
        "findings_schema": '{"assessments": [{"jd_id": "原样返回", "dimensions": [' + _SCHEMA_DIMS + ']}]}',
        "findings_rules": "只评主席指定的维度 key；引文必须落到「文件名 第N页」；各 JD 独立打分，禁止互相平均。",
    },
    "jd_match": {
        "tools": ("read_text", "search_text"),
        "rounds": 6,
        "role": "岗位对照评审员。把候选人对照一个 JD 判硬门槛并给直接匹配类维度分。",
        "findings_schema": '{"assessments": [{"jd_id": "原样返回", "hard_requirements": [' + _SCHEMA_HARD_REQ + '], "dimensions": [' + _SCHEMA_DIMS + ']}]}',
        "findings_rules": "事实纪律：met 的 evidence 必须是结构化简历原文（系统会做语料反查，编造引文会被降级）；简历没写的事实标 unknown，不能标 unmet；unmet 仅用于简历有相反事实；「优先/加分」不得列入 hard_requirements；spec 评分点的 evidence_rule 是找证据的导航，评分仍按固定维度输出。",
    },
    "cross_check": {
        "tools": ("read_text", "search_text"),
        "rounds": 4,
        "role": "仲裁评审员。只回答主席指出的 findings 间矛盾点，不扩展新话题。",
        "findings_schema": '{"arbitrations": [{"question": "主席指出的问题", "conclusion": "基于材料的结论", "quotes": ["文件名 第N页: 原文"]}]}',
        "findings_rules": "结论只能基于材料原文，引文到页。",
    },
    "generic": {
        "tools": ("list_files", "read_text", "read_pages", "search_text", "verify_paper", "web_search"),
        "rounds": 6,
        "role": "通用评审员。主席没有更合适工种时的兜底。",
        "findings_schema": '{"assessments": [{"jd_id": "原样返回", "dimensions": [' + _SCHEMA_DIMS + ']}]}',
        "findings_rules": "按主席指定的维度评分，引文必须来自材料。",
    },
}

_GLOBAL_DIMS = ("technical_depth", "ownership", "engineering_scale")
_MATCH_DIMS = ("direct_task_match", "transferability")
_TOOL_LABELS = {
    "list_files": "盘点材料", "read_text": "读取文本", "read_pages": "视觉转译",
    "search_text": "检索内容", "verify_paper": "论文查证", "web_search": "全网检索",
}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


# ---------------------------------------------------------------------------
# S0 整备
# ---------------------------------------------------------------------------


def build_dossier(
    resume_dump: dict[str, Any],
    jobs: list,
    academic_report: dict[str, Any] | None,
    ctx: MaterialsContext | None,
) -> dict[str, Any]:
    """案卷目录：主席的全局视图。顺带预热文本层缓存（全 pipeline 共享）。"""
    files = []
    for rel in (ctx.walk() if ctx else [])[:FILE_LIST_MAX]:
        text = _extract_text_layer(ctx, rel) if ctx else ""
        files.append({
            "file": rel,
            "segments": max(1, (len(text) + PAGE_CHARS - 1) // PAGE_CHARS) if text else 0,
            "text_layer": bool(text),
        })
    jd_entries = []
    for job in jobs:
        spec = job.spec if isinstance(job.spec, dict) else {}
        jd_entries.append({
            "jd_id": job.id,
            "title": job.title,
            "spec": spec or None,
            "raw_excerpt": (job.raw_text or "")[:400],
            "has_spec": bool(spec),
        })
    return {
        "resume": resume_dump,
        "academic_report": academic_report or {},
        "files": files,
        "jobs": jd_entries,
        # JD 全文只给评审员（jd_match 简报用），不进主席 payload（_lead_payload 按字段挑选）
        "jd_raw_map": {job.id: (job.raw_text or "")[:6000] for job in jobs},
    }


# ---------------------------------------------------------------------------
# 工具执行（委托 agent_assessor / scorer_tools 的现成实现）
# ---------------------------------------------------------------------------


def _execute_tool(ctx: MaterialsContext | None, name: str, args: dict[str, Any]) -> dict[str, Any]:
    if name == "list_files":
        files = ctx.walk() if ctx else []
        return {"summary": f"{len(files)} 个文件", "detail": {"files": files[:FILE_LIST_MAX]}}
    if name == "read_text":
        rel = str(args.get("file") or "")
        text = _extract_text_layer(ctx, rel) if ctx else ""
        page = max(0, int(args.get("page") or 0))
        chunk = text[page * PAGE_CHARS:(page + 1) * PAGE_CHARS]
        if not chunk:
            return {"summary": f"{rel} 无文本层", "detail": {"error": "无文本层（扫描件/图片用 read_pages 视觉转译）或超出范围"}}
        total = max(1, (len(text) + PAGE_CHARS - 1) // PAGE_CHARS)
        return {"summary": f"{rel} 第 {page + 1}/{total} 段（{len(chunk)} 字）",
                "detail": {"file": rel, "page": page, "total_pages": total, "text": chunk}}
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
    return {"summary": f"未知工具 {name}", "detail": {"error": "当前不可用"}}


# ---------------------------------------------------------------------------
# mission runner（类型化评审员 + 会话暂存续派）
# ---------------------------------------------------------------------------


def _worker_system(mission: dict[str, Any], dossier: dict[str, Any], type_spec: dict[str, Any]) -> str:
    files = "\n".join(f"- {f['file']}（{f['segments']} 段{'' if f['text_layer'] else '，扫描件需视觉转译'}）"
                      for f in dossier["files"]) or "（无原始材料文件）"
    parts = [
        f"你是人才评估评审团的{type_spec['role']}",
        f"# 你的任务\n{mission.get('goal', '')}",
        f"# 案卷目录（read_text/read_pages 的 file 取这里的相对路径）\n{files}",
    ]
    if mission.get("files"):
        parts.append(f"# 主席指定材料（优先读这些）\n" + "\n".join(f"- {f}" for f in mission["files"]))
    if mission.get("questions"):
        parts.append("# 要回答的问题\n" + "\n".join(f"- {q}" for q in mission["questions"]))
    if mission.get("resume_claims"):
        parts.append("# 待核验主张（逐条给结论）\n" + "\n".join(f"- {c}" for c in mission["resume_claims"]))
    if mission.get("dimensions"):
        parts.append("# 需要评分的维度 key\n" + "、".join(mission["dimensions"]))
    if mission.get("jd_id"):
        job = next((j for j in dossier["jobs"] if j["jd_id"] == mission["jd_id"]), None)
        if job:
            spec_text = json.dumps(job.get("spec") or {}, ensure_ascii=False)[:1500]
            raw = dossier.get("jd_raw_map", {}).get(job["jd_id"]) or job.get("raw_excerpt", "")
            parts.append(
                f"# 目标 JD：{job['jd_id']}｜{job['title']}\n## 拆解评分点（导航）\n{spec_text}\n"
                f"## JD 原文（硬门槛须逐条对照此措辞）\n{raw}"
            )
    elif dossier["jobs"] and mission["type"] in ("deep_read", "generic"):
        jd_list = "\n".join(f"- jd_id={j['jd_id']}｜{j['title']}" for j in dossier["jobs"])
        parts.append(f"# JD 清单（assessments 的 jd_id 必须从这里原样复制，每个 JD 独立评分一条）\n{jd_list}")
    parts.append(f"# 工作纪律\n{type_spec['findings_rules']}\n"
                 "每次调工具前先用一两句话说明目的。材料读完（或预算将尽）就停止调用工具。")
    return "\n\n".join(parts)


def _validate_findings(mission: dict[str, Any], data: dict[str, Any]) -> str:
    mtype = mission["type"]
    if mtype == "verify":
        claims = data.get("claims")
        if not isinstance(claims, list) or not claims:
            return "claims 必须是非空数组"
        for c in claims:
            if not isinstance(c, dict) or not str(c.get("claim") or "").strip():
                return "每条 claim 必须非空"
            if str(c.get("verdict") or "") not in EVIDENCE_WEIGHTS:
                return f"verdict 非法：{c.get('verdict')!r}（只允许 verified/supported/claimed/unverifiable）"
        return ""
    if mtype == "cross_check":
        items = data.get("arbitrations")
        if not isinstance(items, list) or not items:
            return "arbitrations 必须是非空数组"
        for item in items:
            if not isinstance(item, dict) or len(str(item.get("conclusion") or "").strip()) < 4:
                return "每条 arbitration 必须有 conclusion"
        return ""
    assessments = data.get("assessments")
    if not isinstance(assessments, list) or not assessments:
        return "assessments 必须是非空数组"
    want_jd = mission.get("jd_id")
    dim_keys = set(_MATCH_DIMS if mtype == "jd_match" else mission.get("dimensions") or [])
    for a in assessments:
        if not isinstance(a, dict) or not str(a.get("jd_id") or "").strip():
            return "每个 assessment 必须带 jd_id"
        if want_jd and str(a.get("jd_id")) != want_jd:
            return f"jd_id 必须是 {want_jd}"
        dims = a.get("dimensions")
        if not isinstance(dims, list) or not dims:
            return "dimensions 必须是非空数组"
        for d in dims:
            if not isinstance(d, dict) or str(d.get("key") or "") not in {k for k, _l, _w in DIMENSIONS}:
                return f"维度 key 非法：{d.get('key')!r}"
            if dim_keys and str(d.get("key")) not in dim_keys:
                return f"维度 {d.get('key')} 不在主席指定的范围内"
            try:
                score = float(d.get("score"))
            except (TypeError, ValueError):
                return f"维度 {d.get('key')} 的 score 不是数字"
            if not 0 <= score <= 5:
                return f"维度 {d.get('key')} 的 score 超出 0-5"
            if len(str(d.get("rationale") or "").strip()) < 8:
                return f"维度 {d.get('key')} 的 rationale 过短"
        if mtype == "jd_match":
            reqs = a.get("hard_requirements")
            if not isinstance(reqs, list) or not reqs:
                return "jd_match 必须输出 hard_requirements（没有明确必备条件时输出空要求的说明不成立，可给 unknown 状态条目）"
            for r in reqs:
                if not isinstance(r, dict) or str(r.get("status") or "") not in {"met", "unmet", "unknown"}:
                    return "hard_requirements 每条 status 必须是 met|unmet|unknown"
    return ""


def _quote_tail(quote: str) -> str:
    return quote.split(":")[-1].strip()


def _scrub_findings(mission: dict[str, Any], data: dict[str, Any], corpus: str, resume_corpus: str) -> dict[str, Any]:
    """引文反查：查不到的条目剔除（schema 校验已过，这里只做防幻觉）。

    jd_match 的 evidence 基准是结构化简历语料（与下游 _normalize_requirement 同一门槛），
    其余工种基准是本次评估读过的材料文本。
    """
    base = resume_corpus if mission["type"] == "jd_match" else corpus

    def hit(quote: str) -> bool:
        q = str(quote or "").strip()
        tail = _quote_tail(q)
        return bool(q) and (q in base or (bool(tail) and tail in base))

    dropped = 0
    if mission["type"] == "verify":
        kept = []
        for c in data.get("claims") or []:
            if hit(c.get("quote")) or str(c.get("verdict")) in {"verified", "unverifiable"}:
                kept.append(c)
            else:
                dropped += 1
        data["claims"] = kept
    elif mission["type"] == "cross_check":
        for item in data.get("arbitrations") or []:
            quotes = item.get("quotes")
            if isinstance(quotes, list):
                item["quotes"] = [q for q in quotes if hit(q)]
    else:
        for a in data.get("assessments") or []:
            for section in ("dimensions", "hard_requirements"):
                for item in a.get(section) or []:
                    ev = item.get("evidence")
                    if isinstance(ev, list):
                        kept = [q for q in ev if hit(q)]
                        dropped += len(ev) - len(kept)
                        item["evidence"] = kept
    if dropped:
        data["dropped_quotes"] = dropped
    return data


def run_mission(
    mission: dict[str, Any],
    dossier: dict[str, Any],
    ctx: MaterialsContext | None,
    sessions: dict[str, list],
    lifetime: dict[str, int],
) -> Generator[dict[str, Any], None, dict[str, Any]]:
    """执行一个 mission：新开或续派暂存会话。return {"status", "findings", "summary"}。"""
    from agi_talent_radar.core.llm_client import call_llm_tools

    mission_id = str(mission.get("mission_id") or f"m{len(sessions) + 1}")
    type_spec = TYPE_REGISTRY.get(str(mission.get("type") or "generic")) or TYPE_REGISTRY["generic"]
    label = f"任务[{mission_id}] {mission.get('goal', mission.get('type', 'generic'))}"

    def node(message: str, status: str = "running", **activity: Any) -> dict[str, Any]:
        return {"type": "node", "node": "panel_lead", "label": "评审团", "status": status,
                "phase": "assessment", "message": f"{label}：{message}",
                "mission_id": mission_id, "mission_type": mission.get("type", "generic"),
                "mission_goal": mission.get("goal", ""), "mission_status": status,
                "agent_id": mission_id, "agent_type": mission.get("type", "generic"),
                "event_kind": "status", **activity}

    rounds_budget = type_spec["rounds"]
    lifetime_budget = _env_int("PANEL_MISSION_LIFETIME_ROUNDS", 10)
    schema = [t for t in tools_schema() if t["function"]["name"] in type_spec["tools"]]

    if mission_id in sessions:
        messages = sessions[mission_id]
        note = mission.get("note_to_worker") or "主席要求你在已有工作基础上继续。"
        extra = "\n".join(f"- {q}" for q in mission.get("questions") or [])
        messages.append({"role": "user", "content": f"[主席] {note}" + (f"\n新问题：\n{extra}" if extra else "")})
        yield node("续派：复用已有上下文继续", detail={"指令": note, "问题": mission.get("questions", [])})
    else:
        messages = [
            {"role": "system", "content": _worker_system(mission, dossier, type_spec)},
            {"role": "user", "content": "开始执行任务。先读材料，完成后停止调用工具等待输出 findings。"},
        ]
    sessions[mission_id] = messages
    used = lifetime.get(mission_id, 0)
    yield node("正在读取任务简报，准备执行", event_kind="request")

    for _round in range(min(rounds_budget, max(0, lifetime_budget - used))):
        result = call_llm_tools(messages, schema, temperature=0.2,
                                reasoning_effort=os.getenv("OPENAI_EFFORT_SCORING", "high"))
        tool_calls = result.get("tool_calls") or []
        if not tool_calls and not (result.get("text") or "").strip():
            break
        messages.append({"role": "assistant", "content": result.get("text") or "",
                         "tool_calls": [{"id": tc["id"], "type": "function",
                                         "function": {"name": tc["name"], "arguments": tc["arguments"]}}
                                        for tc in tool_calls]})
        if result.get("text"):
            yield node(str(result["text"]), event_kind="message")
        if not tool_calls:
            break
        for tc in tool_calls:
            try:
                args = json.loads(tc.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            yield node(f"正在{_TOOL_LABELS.get(tc['name'], tc['name'])}", event_kind="tool_call",
                       tool=tc["name"], call_id=tc["id"], detail={"输入": args})
            if tc["name"] not in type_spec["tools"]:  # 白名单是硬约束，不靠提示词
                output = {"summary": "工具未授权", "detail": {"error": f"{tc['name']} 不属于工种 {mission.get('type')}"}}
            else:
                output = _execute_tool(ctx, tc["name"], args)
            summary = str(output.get("summary") or "完成")
            yield node(f"{_TOOL_LABELS.get(tc['name'], tc['name'])}：{summary}",
                       event_kind="tool_result", tool=tc["name"], call_id=tc["id"],
                       detail={"输入": args, "返回摘要": summary})
            messages.append({"role": "tool", "tool_call_id": tc["id"],
                             "content": json.dumps(output.get("detail"), ensure_ascii=False, default=str)[:6000]})
        used += 1
        lifetime[mission_id] = used
    lifetime.setdefault(mission_id, used)  # 零工具轮（直接交 findings）也要入账

    # ---- 独立 JSON 通道提交 findings（校验不过带错误重试）----
    final_prompt = ("材料阅读结束。基于以上全部工作，只输出一个 JSON 对象（不要 markdown、不要解释）：\n"
                    + type_spec["findings_schema"]
                    + "\n要求：" + type_spec["findings_rules"])
    last_error = ""
    for attempt in range(FINDINGS_RETRIES + 1):
        yield node("汇总 findings…" if attempt == 0 else f"findings 校验未过，重试（{attempt}/{FINDINGS_RETRIES}）")
        messages.append({"role": "user", "content": final_prompt if attempt == 0
                         else f"[系统] 上次输出校验未通过：{last_error}。请修正后重新只输出 JSON。"})
        result = call_llm_tools(messages, tools=[], temperature=0.2,
                                reasoning_effort=os.getenv("OPENAI_EFFORT_SCORING", "high"))
        text = (result.get("text") or "").strip()
        messages.append({"role": "assistant", "content": text})
        parsed = _parse_json_block(text)
        if parsed is None:
            last_error = "输出不是合法 JSON"
            continue
        error = _validate_findings(mission, parsed)
        if not error:
            corpus = "\n".join(ctx.text_cache.values()) if ctx else ""
            resume_corpus = json.dumps(dossier["resume"], ensure_ascii=False)
            findings = _scrub_findings(mission, parsed, corpus, resume_corpus)
            yield node(f"完成（{sum(len(v) for v in findings.values() if isinstance(v, list))} 条结论）",
                       status="done")
            return {"status": "done", "mission_id": mission_id, "type": mission["type"],
                    "goal": mission.get("goal", ""), "findings": findings}
        last_error = error
    yield node(f"失败：{last_error[:120]}", status="failed", event_kind="error")
    return {"status": "failed", "mission_id": mission_id, "type": mission["type"],
            "goal": mission.get("goal", ""), "findings": {}, "error": last_error}


# ---------------------------------------------------------------------------
# 主席循环
# ---------------------------------------------------------------------------

_TYPE_MENU = "\n".join(f"- {key}：{spec['role']}" for key, spec in TYPE_REGISTRY.items())

_LEAD_SYSTEM = f"""你是人才评估评审团的主席（组长）。评审员负责读材料、查证据、给维度分；你负责编排：
决定派哪些评审任务、核收结论、发现矛盾补派，最后写综合意见。

# 制度（不可逾越）
1. 你每轮只输出一个 JSON 决策：dispatch（派活）或 synthesize（收队）。
2. 维度分与录用裁决由系统按确定性规则计算，你的输出里没有任何分数字段。
3. findings 必须来自评审员；你不读材料原文，只依据案卷目录和收到的结论摘要编排。

# 评审员工种菜单（dispatch.missions[].type 只能选这些）
{_TYPE_MENU}

# 覆盖率纪律
- 简历含论文/奖项/录用主张而未派 verify，不得收队。
- 每个 JD 必须有一个 jd_match 任务覆盖（硬门槛 + direct_task_match/transferability）。
- 材料中有论文/项目文档时，应派 deep_read 覆盖 technical_depth/ownership/engineering_scale。
- 结论之间矛盾时，补派 cross_check（可续派已有任务，写 note_to_worker）。
- 材料很薄（只有一份简历）时，少派甚至直接 synthesize。

# 输出格式（只输出 JSON，不要 markdown）
dispatch: {{"action": "dispatch", "missions": [{{"mission_id": "m1", "type": "工种", "goal": "一句话目标",
  "files": ["指定材料（可空）"], "questions": ["要回答的问题"], "dimensions": ["deep_read 要评的维度 key"],
  "jd_id": "jd_match 的目标 JD", "resume_claims": ["verify 的待核验主张"], "note_to_worker": "续派时给的话"}}]}}
synthesize: {{"action": "synthesize", "per_jd": [{{"jd_id": "...", "confidence": 0-1,
  "strengths": [{{"summary": "...", "evidence": ["出处"]}}], "risks": [{{"summary": "...", "evidence": []}}],
  "interview_questions": ["..."], "missing_information": ["..."], "assessment_summary": "一句话"}}]}}"""


def _lead_payload(dossier: dict[str, Any], done: list[dict[str, Any]], rounds_left: int, error: str = "") -> dict[str, Any]:
    return {
        "resume": {k: dossier["resume"].get(k) for k in
                   ("name", "target_role", "stage", "education", "directions", "experiences",
                    "projects", "publications", "skills")},
        "academic_report": json.dumps(dossier["academic_report"], ensure_ascii=False)[:1500],
        "files": dossier["files"],
        "jobs": dossier["jobs"],
        "missions_done": done,
        "rounds_left": rounds_left,
        "last_error": error,
    }


def _validate_lead_decision(jobs: list, data: dict[str, Any], missions_open: int) -> tuple[str, dict[str, Any]]:
    action = str(data.get("action") or "")
    if action == "synthesize":
        per_jd = data.get("per_jd")
        if not isinstance(per_jd, list):
            return "synthesize.per_jd 必须是数组", {}
        by_id = {str(item.get("jd_id") or "") for item in per_jd if isinstance(item, dict)}
        missing = [j.id for j in jobs if j.id not in by_id]
        if missing:
            return f"per_jd 缺少 JD：{', '.join(missing)}", {}
        return "", data
    if action == "dispatch":
        missions = data.get("missions")
        if not isinstance(missions, list) or not missions:
            return "dispatch.missions 必须是非空数组", {}
        clean = []
        for m in missions[:max(0, missions_open)]:
            if not isinstance(m, dict):
                continue
            if str(m.get("type") or "") not in TYPE_REGISTRY:
                return f"未知工种：{m.get('type')!r}", {}
            clean.append(m)
        if not clean:
            return "没有可执行的 mission（预算已满）", {}
        return "", {"action": "dispatch", "missions": clean}
    return f"action 非法：{action!r}", {}


def run_panel_stream(
    resume_dump: dict[str, Any],
    jobs: list,
    academic_report: dict[str, Any] | None,
    ctx: MaterialsContext | None,
) -> Generator[dict[str, Any], None, dict[str, Any]]:
    """评审团主循环。yield 进度事件，return job_fit_raw（供 yield from 捕获）。"""
    from agi_talent_radar.core.llm_client import call_llm_json

    def lead_node(message: str, status: str = "running", **activity: Any) -> dict[str, Any]:
        return {"type": "node", "node": "panel_lead", "label": "评审团", "status": status,
                "phase": "assessment", "message": message, "agent_id": "chair",
                "agent_type": "chair", "event_kind": "status", **activity}

    yield {"type": "node", "node": "material_desk", "label": "材料整备", "status": "running",
           "phase": "preparation", "message": "正在盘点材料并预热文本层…"}
    dossier = build_dossier(resume_dump, jobs, academic_report, ctx)
    scanned = sum(1 for f in dossier["files"] if not f["text_layer"])
    yield {"type": "node", "node": "material_desk", "label": "材料整备", "status": "done",
           "phase": "preparation",
           "message": f"整备完成：{len(dossier['files'])} 份材料，{scanned} 份需视觉转译。"}

    sessions: dict[str, list] = {}
    lifetime: dict[str, int] = {}
    done: list[dict[str, Any]] = []
    per_jd: list[dict[str, Any]] = []
    max_missions = _env_int("PANEL_MAX_MISSIONS", 8)
    max_rounds = _env_int("PANEL_LEAD_MAX_ROUNDS", 12)
    dispatched = 0
    error = ""

    for round_no in range(1, max_rounds + 1):
        rounds_left = max_rounds - round_no
        data: dict[str, Any] = {}
        for attempt in range(LEAD_RETRIES + 1):
            payload = _lead_payload(dossier, done, rounds_left,
                                    error if attempt == 0 else "")
            if rounds_left == 0:
                payload["instruction"] = "这是最后一轮：立即 synthesize，基于已有信息收队。"
            yield lead_node(f"主席正在审阅结论并决定下一步（第 {round_no} 轮）",
                            event_kind="request", detail={"已收到结论": [
                                {"任务": d["mission_id"], "状态": d["status"], "摘要": d["digest"]} for d in done
                            ], "剩余轮数": rounds_left})
            try:
                data = call_llm_json(_LEAD_SYSTEM, payload, temperature=0.2)
            except Exception as exc:  # noqa: BLE001
                logger.warning("主席调用失败：%s", exc)
                data = {}
            error, data = _validate_lead_decision(jobs, data, max_missions - dispatched)
            if not error:
                break
        if error:
            # 主席连续输出非法 → 兜底：直接收队（定性字段留空，评估照常出分）
            break

        if data.get("action") == "synthesize":
            per_jd = data.get("per_jd") or []
            yield lead_node("主席收队，综合意见已交给系统装配。", event_kind="handoff",
                            target_id="system", detail={"综合意见": per_jd})
            break

        missions = data.get("missions") or []
        for mission in missions:
            mission = {**mission, "mission_id": str(mission.get("mission_id") or f"m{dispatched + 1}")}
            if mission["mission_id"] not in {d["mission_id"] for d in done}:
                dispatched += 1
            if mission.get("type") == "jd_match" and not mission.get("jd_id"):
                mission["jd_id"] = next((j["jd_id"] for j in dossier["jobs"]
                                         if j["jd_id"] not in {m.get("jd_id") for m in missions if m.get("jd_id")}), None)
            yield {**lead_node(f"派出 {mission['mission_id']}（{mission['type']}）：{mission.get('goal', '')}"),
                   "mission_id": mission["mission_id"], "mission_type": mission["type"],
                   "mission_goal": mission.get("goal", ""), "mission_status": "running",
                   "event_kind": "dispatch", "target_id": mission["mission_id"],
                   "detail": {"目标": mission.get("goal", ""), "材料": mission.get("files", []),
                              "问题": mission.get("questions", []), "续派指令": mission.get("note_to_worker", ""),
                              "复用上下文": mission["mission_id"] in sessions}}
            try:
                outcome = yield from run_mission(mission, dossier, ctx, sessions, lifetime)
            except Exception as exc:  # noqa: BLE001 — 单 mission 崩溃不拖全队
                logger.exception("mission %s 执行失败", mission.get("mission_id"))
                outcome = {"status": "failed", "mission_id": mission.get("mission_id", "?"),
                           "type": mission.get("type", "?"), "goal": mission.get("goal", ""),
                           "findings": {}, "error": str(exc)[:200]}
            digest = json.dumps(outcome.get("findings") or {}, ensure_ascii=False)[:DIGEST_CHARS]
            yield {**lead_node("评审结论已回传主席" if outcome["status"] == "done" else "任务失败已报告主席"),
                   "agent_id": mission["mission_id"], "agent_type": mission["type"],
                   "target_id": "chair", "event_kind": "handoff",
                   "mission_id": mission["mission_id"], "mission_type": mission["type"],
                   "mission_goal": mission.get("goal", ""), "mission_status": outcome["status"],
                   "detail": {"结论": outcome.get("findings", {}), "主席收到的摘要": digest,
                              "错误": outcome.get("error", "")}}
            done.append({"mission_id": outcome["mission_id"], "type": outcome["type"],
                         "goal": outcome["goal"], "status": outcome["status"], "digest": digest,
                         "findings": outcome.get("findings") or {}})

    if not per_jd:
        per_jd = [{"jd_id": job.id, "confidence": 0.3, "strengths": [], "risks": [],
                   "interview_questions": [], "missing_information": ["主席未产出综合意见"],
                   "assessment_summary": ""} for job in jobs]

    yield lead_node(f"评审团收工：{dispatched} 个任务，{sum(1 for d in done if d['status'] == 'done')} 个完成。",
                    status="done")
    return assemble(jobs, dossier["resume"], done, per_jd)


# ---------------------------------------------------------------------------
# S2 装配（确定性：分数只来自 mission findings）
# ---------------------------------------------------------------------------

_TYPE_ORDER = {"jd_match": 0, "deep_read": 1, "generic": 2}


def _evidence_quality(claims: list[dict[str, Any]], publications: list) -> tuple[float | None, str, str | None]:
    """verify ledger → (score, rationale, missing_note)。无 ledger 返回 (None, "", None)。"""
    if not claims:
        return None, "", None
    weights = [EVIDENCE_WEIGHTS.get(str(c.get("verdict")), 0.1) for c in claims]
    score = min(5.0, 1 + 4 * (sum(weights) / len(weights)))
    counts: dict[str, int] = {}
    for c in claims:
        counts[str(c.get("verdict"))] = counts.get(str(c.get("verdict")), 0) + 1
    dist = "、".join(f"{k} {v}" for k, v in sorted(counts.items()))
    note = None
    rep = str(publications[0])[:24] if publications else ""
    if rep and any(rep and rep in str(c.get("claim", "")) and
                   str(c.get("verdict")) in {"claimed", "unverifiable"} for c in claims):
        score = min(score, 2.5)  # 代表作未被公开源证实：反通胀封顶（对齐奖学金评审）
        note = f"代表作《{publications[0]}》未被公开源证实"
    return round(score, 1), f"证据核验 {len(claims)} 条（{dist}）", note


def assemble(jobs: list, resume_dump: dict[str, Any], done: list[dict[str, Any]], per_jd: list[dict[str, Any]]) -> dict[str, Any]:
    lead_by_id = {str(item.get("jd_id") or ""): item for item in per_jd if isinstance(item, dict)}
    # 评审员可能把 jd_id 写成 JD 标题：id 优先，标题兜底
    resolve: dict[str, str] = {}
    for job in jobs:
        resolve[job.id] = job.id
        resolve.setdefault(job.title, job.id)
    dim_findings: list[tuple[str, dict[str, Any]]] = []   # (jd_id, assessment) 按类型优先级
    hard_reqs: dict[str, list] = {}
    claims: list[dict[str, Any]] = []
    for outcome in sorted(done, key=lambda d: _TYPE_ORDER.get(d.get("type", "generic"), 3)):
        findings = outcome.get("findings") or {}
        if outcome.get("type") == "verify":
            claims.extend(findings.get("claims") or [])
            continue
        if outcome.get("type") == "cross_check":
            continue  # 仲裁结论供主席参考，不进装配
        for a in findings.get("assessments") or []:
            jd_id = resolve.get(str(a.get("jd_id") or ""), str(a.get("jd_id") or ""))
            dim_findings.append((jd_id, a))
            if outcome.get("type") == "jd_match" and a.get("hard_requirements"):
                hard_reqs.setdefault(jd_id, a["hard_requirements"])

    eq_score, eq_rationale, eq_note = _evidence_quality(claims, resume_dump.get("publications") or [])
    eq_defaulted = eq_score is None
    if eq_defaulted:
        eq_score = NO_VERIFY_SCORE if resume_dump.get("publications") else MISSING_DIM_SCORE
        eq_rationale = "未执行公开源证据查证，按保守缺省"
    all_dim_keys = [k for k, _l, _w in DIMENSIONS]
    assessments = []
    for job in jobs:
        dims: dict[str, dict[str, Any]] = {}
        for jd_id, a in dim_findings:
            if jd_id != job.id:
                continue
            for d in a.get("dimensions") or []:
                key = str(d.get("key") or "")
                if key in all_dim_keys and key not in dims:
                    dims[key] = d
        missing: list[str] = []
        if "direct_task_match" not in dims:
            missing.append("未执行硬门槛与直接匹配对照")
        if eq_defaulted:
            missing.append("证据未经公开源查证")
        for key in all_dim_keys:
            if key == "evidence_quality" or key in dims:
                continue
            dims[key] = {"key": key, "score": MISSING_DIM_SCORE,
                         "rationale": "该维评估未覆盖，按保守缺省", "evidence": []}
            missing.append(f"维度 {key} 评估未覆盖")
        dimensions = []
        for key, dim_label, _weight in DIMENSIONS:
            if key == "evidence_quality":  # 规则分 + 机器 rationale，不由任何 LLM 直评
                entry = {"key": key, "label": dim_label, "score": eq_score,
                         "rationale": eq_rationale, "evidence": []}
            else:
                d = dims[key]
                entry = {"key": key, "label": dim_label, "score": round(float(d.get("score", 0)), 1),
                         "rationale": str(d.get("rationale") or ""),
                         "evidence": list(d.get("evidence") or [])}
            dimensions.append(entry)

        lead = lead_by_id.get(job.id) or {}
        degraded = bool(missing)
        confidence = max(0.0, min(1.0, float(lead.get("confidence") or 0.5)))
        if degraded:
            confidence = round(confidence * 0.5, 2)
        notes = [str(x) for x in (lead.get("missing_information") or []) if str(x).strip()]
        if eq_note:
            notes.append(eq_note)
        notes.extend(missing)
        assessments.append({
            "jd_id": job.id,
            "hard_requirements": hard_reqs.get(job.id, []),
            "dimensions": dimensions,
            "confidence": confidence,
            "strengths": lead.get("strengths") or [],
            "risks": lead.get("risks") or [],
            "missing_information": notes,
            "interview_questions": lead.get("interview_questions") or [],
            "assessment_summary": str(lead.get("assessment_summary") or ""),
        })
    return {"assessments": assessments}
