"""评审团评估 v2：主席是一个带工具的主 agent（问答 agent 同款循环），spawn 是它的工具。

- 主席工具 = 只读材料工具（list_files/read_text/read_pages/search_text/verify_paper/
  web_search）+ spawn_agent；它亲自读材料或派子 agent 调查，由它现场决定
- spawn_agent 的 prompt 就是子评审 agent 的全部约束与指引——不再按工种区分
  系统提示词/工具白名单/findings 合同；子 agent 工具与主 agent 相同但不能
  spawn（不嵌套）
- 子 agent 的最终报告作为工具结果回到主席上下文；主席收尾经独立 JSON 通道
  输出评分合同（job_fit_raw），decision_guard / formatter 复用原节点——
  硬门槛裁决与评分合同不变
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Generator

from agi_talent_radar.agents.job_fit.evaluator import DIMENSIONS
from agi_talent_radar.agents.job_fit.materials import (
    MaterialsContext,
    extract_text_layer,
    parse_json_block,
    tool_read_pages,
    tool_search_text,
    tools_schema,
)
from agi_talent_radar.agents.evaluation_trace import stream_call

logger = logging.getLogger(__name__)

FILE_LIST_MAX = 500
LEAD_RETRIES = 2            # 主席单轮调用失败重试
FINAL_RETRIES = 3           # 收尾评分合同重试
MISSING_DIM_SCORE = 2.0     # 缺维保守缺省（绝不补 0——0 分会把人错误推向 reject）


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


# ---------------------------------------------------------------------------
# 工具：主 agent 与子 agent 共享同一套只读材料工具；spawn_agent 仅主 agent 可用
# ---------------------------------------------------------------------------

_SPAWN_SCHEMA = [{
    "type": "function",
    "function": {
        "name": "spawn_agent",
        "description": (
            "派生一个子评审 agent 去完成一项调查任务，或对已有子 agent 续命让它继续工作。"
            "子 agent 拥有和你相同的材料只读工具（读取/视觉转译/检索/论文查证/全网检索），"
            "但不能再生子 agent。prompt 必须自包含：任务目标、要读的材料、要回答的问题、报告要求。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "goal": {"type": "string", "description": "一句话任务目标（展示用）"},
                "prompt": {"type": "string", "description": "给子 agent 的完整任务指令；续命时写继续指令（基于它已有的进展）"},
                "agent_id": {"type": "string", "description": "续命已有子 agent 时填它的 id（上下文保留、轮数重置）；新任务留空"},
            },
            "required": ["goal", "prompt"],
        },
    },
}]

CHAIR_TOOLS = tools_schema() + _SPAWN_SCHEMA
WORKER_TOOLS = tools_schema()

_TOOL_LABELS = {
    "list_files": "盘点材料", "read_text": "读取文本", "read_pages": "视觉转译",
    "search_text": "检索内容", "verify_paper": "论文查证", "web_search": "全网检索",
    "spawn_agent": "派出子评审 agent",
}


def build_dossier(
    resume_dump: dict[str, Any],
    jobs: list,
    academic_report: dict[str, Any] | None,
    ctx: MaterialsContext | None,
) -> dict[str, Any]:
    """案卷目录：主 agent 与子 agent 共享的全局视图。顺带预热文本层缓存。"""
    files = []
    for rel in (ctx.walk() if ctx else [])[:FILE_LIST_MAX]:
        text = extract_text_layer(ctx, rel) if ctx else ""
        files.append({
            "file": rel,
            "segments": max(1, (len(text) + 4000 - 1) // 4000) if text else 0,
            "text_layer": bool(text),
        })
    return {
        "resume": resume_dump,
        "academic_report": academic_report or {},
        "files": files,
        "jobs": [{
            "jd_id": job.id,
            "title": job.title,
            "spec": job.spec if isinstance(job.spec, dict) else None,
            "raw_excerpt": (job.raw_text or "")[:6000],
        } for job in jobs],
    }


def _execute_tool(ctx: MaterialsContext | None, name: str, args: dict[str, Any]) -> dict[str, Any]:
    if name == "list_files":
        files = ctx.walk() if ctx else []
        return {"summary": f"{len(files)} 个文件", "detail": {"files": files[:FILE_LIST_MAX]}}
    if name == "read_text":
        rel = str(args.get("file") or "")
        text = extract_text_layer(ctx, rel) if ctx else ""
        page = max(0, int(args.get("page") or 0))
        page_chars = 4000
        chunk = text[page * page_chars:(page + 1) * page_chars]
        if not chunk:
            return {"summary": f"{rel} 无文本层", "detail": {"error": "无文本层（扫描件/图片用 read_pages 视觉转译）或超出范围"}}
        total = max(1, (len(text) + page_chars - 1) // page_chars)
        return {"summary": f"{rel} 第 {page + 1}/{total} 段（{len(chunk)} 字）",
                "detail": {"file": rel, "page": page, "total_pages": total, "text": chunk}}
    if name == "read_pages":
        return tool_read_pages(ctx, args)
    if name == "search_text":
        return tool_search_text(ctx, args)
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
# 主 agent（主席）
# ---------------------------------------------------------------------------

def _chair_system(dossier: dict[str, Any]) -> str:
    files = "\n".join(f"- {f['file']}（{f['segments']} 段{'' if f['text_layer'] else '，扫描件需视觉转译'}）"
                      for f in dossier["files"]) or "（无原始材料文件）"
    jobs = "\n".join(f"- jd_id={j['jd_id']}｜{j['title']}" for j in dossier["jobs"])
    return f"""你是人才评估评审团的主席（主 agent）。任务：对照全部 JD 完成候选人评估，
产出可复核的评审结论。你拥有材料只读工具，并可以通过 spawn_agent 派出子评审 agent。

# 制度
1. 子 agent 与你工具相同，但不能再生子 agent；它们的报告只回给你。
2. 大量阅读应交给子 agent（spawn 的 prompt 写清楚目标、材料、问题、报告要求），
   保持你自己的上下文留给综合判断；小的核对你可以亲自做。
3. 事实纪律：结论必须落在材料原文上，引文到「文件名 第N页」；简历没写的事实是
   unknown，不能标 unmet；「优先/加分」不进硬门槛。
4. 每个 JD 必须独立评估：硬门槛逐条对照 + 六维打分（0-5），禁止跨 JD 平均。
5. 评估覆盖纪律：简历含论文/奖项主张必须有查证结论；材料里的论文/项目文档要有人深读。

# 评估对象
{jobs or "（无 JD）"}

# 案卷目录（read_text/read_pages 的 file 取这里的相对路径）
{files}

# 结构化简历
{json.dumps(dossier["resume"], ensure_ascii=False)[:3000]}

# 论文核验报告
{json.dumps(dossier["academic_report"], ensure_ascii=False)[:1500]}

# 工作方式
每次调用工具（包括 spawn_agent）之前，先用一两句话向用户说明你要做什么、为什么；
拿到结果后简述关键发现。禁止一句话不说就连环调工具。
调查充分后停止调用工具，等待系统向你收取最终评估。"""


_CHAIR_SUMMARY_PROMPT = """最后一步：面向用人方写一段评估总结（markdown，250–450 字）。

要求：
- 先按 JD 逐个给出结论概览（各维度得分要点与最终等级判断）；
- 提炼最有价值的证据（引用到「文件名 第N页」）与最大的不确定性；
- 指出主要风险与面试建议（验证什么、怎么验证）；
- 只依据上方已收集的子 agent 报告与你亲自核对的事实，不引入新结论。
不要输出 JSON，不要重复逐条列引用。"""


def _chair_final_prompt(jobs: list) -> str:
    jd_list = "\n".join(f"- jd_id={job.id}｜{job.title}" for job in jobs)
    dims = "\n".join(f"- {key}（{label}）" for key, label, _w in DIMENSIONS)
    return f"""调查结束。基于你收集的全部信息，只输出一个 JSON 对象（不要 markdown、不要解释），
即本次评估的评分合同：

{{"assessments": [{{
  "jd_id": "原样返回",
  "hard_requirements": [{{"requirement": "JD 明确必备条件", "status": "met|unmet|unknown",
    "evidence": ["结构化简历原文"], "rationale": "判断理由"}}],
  "dimensions": [{{"key": "维度 key", "score": 0-5, "rationale": "引用具体证据",
    "evidence": ["文件名 第N页: 原文"]}}],
  "confidence": 0-1,
  "strengths": [{{"summary": "...", "evidence": ["出处"]}}],
  "risks": [{{"summary": "...", "evidence": []}}],
  "missing_information": ["..."],
  "interview_questions": ["..."],
  "assessment_summary": "一句话"
}}]}}

要求：
- 必须覆盖全部 JD：{jd_list or "（无）"}
- 六维齐全且只能用这些 key：{dims}
- met/unmet 的 evidence 必须是结构化简历原文；unknown ≠ unmet
- 各 JD 独立评分，禁止互相平均；分数要有 rationale 支撑"""


def _validate_contract(jobs: list, data: dict[str, Any]) -> str:
    items = data.get("assessments")
    if not isinstance(items, list) or not items:
        return "assessments 必须是非空数组"
    by_id = {str(item.get("jd_id") or ""): item for item in items if isinstance(item, dict)}
    missing = [job.id for job in jobs if job.id not in by_id]
    if missing:
        return f"缺少 JD 评估：{', '.join(missing)}"
    dim_keys = {key for key, _label, _weight in DIMENSIONS}
    for job in jobs:
        item = by_id[job.id]
        dims = item.get("dimensions")
        if not isinstance(dims, list) or not dims:
            return f"JD {job.id} 缺少 dimensions"
        seen = set()
        for dim in dims:
            if not isinstance(dim, dict):
                return f"JD {job.id} 存在非法维度条目"
            key = str(dim.get("key") or "")
            if key not in dim_keys:
                return f"JD {job.id} 维度 key 非法：{key!r}"
            if key in seen:
                return f"JD {job.id} 维度 {key} 重复"
            seen.add(key)
            try:
                score = float(dim.get("score"))
            except (TypeError, ValueError):
                return f"JD {job.id} 维度 {key} 的 score 不是数字"
            if not 0 <= score <= 5:
                return f"JD {job.id} 维度 {key} 的 score 超出 0-5"
    return ""


# ---------------------------------------------------------------------------
# 子评审 agent：与主 agent 相同的工具（去掉 spawn），由 spawn prompt 全权约束
# ---------------------------------------------------------------------------

def _worker_system(dossier: dict[str, Any]) -> str:
    files = "\n".join(f"- {f['file']}（{f['segments']} 段{'' if f['text_layer'] else '，扫描件需视觉转译'}）"
                      for f in dossier["files"]) or "（无原始材料文件）"
    return f"""你是人才评估评审团的评审 agent。主席交给你的任务指令就是你的全部职责范围，
按指令完成调查并输出报告。你拥有材料只读工具，但不能派生其他 agent。

# 案卷目录（read_text/read_pages 的 file 取这里的相对路径）
{files}

# 工作纪律
1. 每轮至少向主席输出一句进展说明：做了什么、发现了什么、下一步为什么。
2. 结论必须落在材料原文上，引用到「文件名 第N页」；查不到就明说，禁止推测。
3. 材料读完（或任务完成）就停止调用工具，输出最终报告（结论、证据、风险）。
4. 主席可能发出续派指令让你继续：基于已有上下文接着做，不要重复已完成的工作。"""


def run_agent_mission(
    mission_id: str,
    goal: str,
    prompt: str,
    dossier: dict[str, Any],
    ctx: MaterialsContext | None,
    messages: list[dict[str, Any]] | None = None,
    rounds: int | None = None,
) -> Generator[dict[str, Any], None, dict[str, Any]]:
    """执行一个子评审 agent（messages 传入 = 续命，上下文保留、轮数重置）。

    yield {"type":"sse"/"trace", ...}，return {"status","report","messages"}。"""
    if messages is None:
        messages = [
            {"role": "system", "content": _worker_system(dossier)},
            {"role": "user", "content": f"[主席] {prompt}"},
        ]
    else:
        messages.append({"role": "user", "content": f"[主席] {prompt}"})

    def sse(event: dict[str, Any]) -> dict[str, Any]:
        return {"type": "sse", "event": event}

    rounds = rounds if rounds is not None else _env_int("PANEL_AGENT_ROUNDS", 8)
    report = ""
    for _round in range(rounds):
        result = yield from stream_call(
            messages, WORKER_TOOLS, temperature=0.2,
            reasoning_effort=os.getenv("OPENAI_EFFORT_SCORING", "high"),
        )
        tool_calls = result.get("tool_calls") or []
        report = str(result.get("text") or "")
        if not tool_calls and not report:
            break
        messages.append({"role": "assistant", "content": report,
                         "tool_calls": [{"id": tc["id"], "type": "function",
                                         "function": {"name": tc["name"], "arguments": tc["arguments"]}}
                                        for tc in tool_calls]})
        if not tool_calls:
            break
        for tc in tool_calls:
            try:
                args = json.loads(tc.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            label = _TOOL_LABELS.get(tc["name"], tc["name"])
            yield sse({"type": "tool_start", "payload": {
                "call_id": tc["id"], "tool": tc["name"], "label": label,
                "args_summary": json.dumps(args, ensure_ascii=False)[:200]}})
            if tc["name"] == "spawn_agent":
                # 工具集里没有 spawn（提示词层约束）；这里再硬拦一层防幻觉嵌套
                output = {"summary": "子 agent 不能派生 agent", "detail": {"error": "禁止嵌套 spawn"}}
            else:
                output = _execute_tool(ctx, tc["name"], args)
            summary = str(output.get("summary") or "完成")
            status = "error" if "未授权" in summary or "不能派生" in summary else "ok"
            yield sse({"type": "tool_end", "payload": {
                "call_id": tc["id"], "status": status, "summary": summary,
                "detail": json.dumps(output.get("detail"), ensure_ascii=False, default=str)[:2000]}})
            messages.append({"role": "tool", "tool_call_id": tc["id"],
                             "content": json.dumps({"summary": summary, "detail": output.get("detail")},
                                                   ensure_ascii=False, default=str)[:6000]})
    if not report:
        return {"status": "failed", "report": "", "messages": messages}
    return {"status": "done", "report": report, "messages": messages}


# ---------------------------------------------------------------------------
# 主流程：主席 agentic loop + 收尾评分合同
# ---------------------------------------------------------------------------

def run_panel_stream(
    resume_dump: dict[str, Any],
    jobs: list,
    academic_report: dict[str, Any] | None,
    ctx: MaterialsContext | None,
) -> Generator[dict[str, Any], None, dict[str, Any]]:
    """主 agent 循环。yield {"type":"sse"/"node"} 事件，return {"job_fit_raw","trace"}。"""
    from agi_talent_radar.core.llm_client import call_llm_tools

    def sse(event: dict[str, Any]) -> dict[str, Any]:
        return {"type": "sse", "event": event}

    trace: list[dict[str, Any]] = []

    def trace_append(segment: dict[str, Any]) -> None:
        trace.append(segment)

    def stream_chair(messages_arg, tools_arg, **kwargs):
        iterator = iter(stream_call(messages_arg, tools_arg, **kwargs))
        while True:
            try:
                item = next(iterator)
            except StopIteration as stop:
                return stop.value
            payload = item["event"].get("payload", {})
            event_type = item["event"]["type"]
            segment_type = "thinking" if event_type == "thinking_delta" else "text"
            if event_type in {"answer_delta", "thinking_delta"} and payload.get("text"):
                if (trace and trace[-1].get("type") == segment_type
                        and not trace[-1].get("spawn_id")):
                    trace[-1]["text"] += payload["text"]
                else:
                    trace_append({"type": segment_type, "text": payload["text"]})
            yield item

    yield {"type": "node", "node": "material_desk", "label": "材料整备", "status": "running",
           "phase": "preparation", "message": "正在盘点材料并预热文本层…"}
    dossier = build_dossier(resume_dump, jobs, academic_report, ctx)
    scanned = sum(1 for f in dossier["files"] if not f["text_layer"])
    yield {"type": "node", "node": "material_desk", "label": "材料整备", "status": "done",
           "phase": "preparation",
           "message": f"整备完成：{len(dossier['files'])} 份材料，{scanned} 份需视觉转译。"}

    max_spawns = _env_int("PANEL_MAX_SPAWNS", 8)
    max_rounds = _env_int("PANEL_LEAD_ROUNDS", 10)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _chair_system(dossier)},
        {"role": "user", "content": "开始本次评估。先盘点要查证什么，派出子评审 agent 或亲自核对；调查充分后停止调用工具。"},
    ]
    spawned = 0
    sessions: dict[str, list[dict[str, Any]]] = {}   # mission_id -> 子 agent 上下文（续命复用）

    for _round in range(max_rounds):
        result: dict[str, Any] = {}
        error = ""
        for attempt in range(LEAD_RETRIES + 1):
            try:
                result = yield from stream_chair(
                    messages, CHAIR_TOOLS, temperature=0.2,
                    reasoning_effort=os.getenv("OPENAI_EFFORT_SCORING", "high"),
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("主席调用失败：%s", exc)
                result = {}
            if (result.get("tool_calls") or []) or str(result.get("text") or "").strip():
                error = ""
                break
            error = "主席没有返回内容"
        if error:
            break

        text = str(result.get("text") or "").strip()
        tool_calls = result.get("tool_calls") or []
        if text:
            messages.append({"role": "assistant", "content": text})
        if not tool_calls:
            break
        messages.append({"role": "assistant", "content": "",
                         "tool_calls": [{"id": tc["id"], "type": "function",
                                         "function": {"name": tc["name"], "arguments": tc["arguments"]}}
                                        for tc in tool_calls]})

        for tc in tool_calls:
            try:
                args = json.loads(tc.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            name = tc["name"]
            if name == "spawn_agent":
                goal = str(args.get("goal") or "").strip() or "子评审任务"
                prompt = str(args.get("prompt") or "").strip()
                agent_id = str(args.get("agent_id") or "").strip()
                continuing = bool(agent_id) and agent_id in sessions
                if not prompt:
                    output = {"summary": "缺少 prompt", "detail": {"error": "spawn_agent 需要 prompt"}}
                elif spawned >= max_spawns and not continuing:
                    output = {"summary": "spawn 预算已用尽，可对已有子 agent 续命或基于已有信息收尾",
                              "detail": {"error": f"最多派出 {max_spawns} 个子 agent"}}
                else:
                    if continuing:
                        # 续命：上下文保留、轮数重置；过程叙事里追加续派指令
                        mission_id = agent_id
                        spawn_segment = next(s for s in trace
                                             if s.get("type") == "spawn" and s.get("spawn_id") == mission_id)
                        spawn_segment["status"] = "running"
                        spawn_segment["summary"] = ""
                        spawn_segment["prompt"] = prompt
                        yield sse({"type": "spawn_start", "payload": {
                            "spawn_id": mission_id, "agent": spawn_segment["agent"],
                            "title": goal, "prompt": prompt}})
                        yield sse({"type": "answer_delta", "payload": {
                            "text": f"[续命指令] {prompt}", "spawn_id": mission_id}})
                        trace_append({"type": "text", "text": f"[续命指令] {prompt}",
                                      "spawn_id": mission_id})
                    else:
                        spawned += 1
                        mission_id = agent_id or f"m{spawned}"
                        spawn_segment = {"type": "spawn", "spawn_id": mission_id,
                                         "agent": "通用评审员", "title": goal, "status": "running",
                                         "summary": "", "children": [], "prompt": prompt}
                        trace_append(spawn_segment)
                        yield sse({"type": "spawn_start", "payload": {
                            "spawn_id": mission_id, "agent": "通用评审员",
                            "title": goal, "prompt": prompt}})

                    def wrap(gen: Generator[dict[str, Any], None, dict[str, Any]],
                             spawn_id: str = mission_id) -> Generator[dict[str, Any], None, dict[str, Any]]:
                        # 子 agent 的 SSE 注入 spawn_id，并镜像为 trace 段（挂在 spawn 下）
                        outcome: dict[str, Any] | None = None
                        iterator = iter(gen)
                        while True:
                            try:
                                item = next(iterator)
                            except StopIteration as stop:
                                outcome = stop.value
                                break
                            if item["type"] == "sse":
                                event = item["event"]
                                payload = event.setdefault("payload", {})
                                payload["spawn_id"] = spawn_id
                                if event["type"] == "tool_start":
                                    trace_append({"type": "tool", "call_id": payload["call_id"],
                                                  "tool": payload["tool"], "label": payload["label"],
                                                  "args_summary": payload.get("args_summary", ""),
                                                  "spawn_id": spawn_id})
                                elif event["type"] in {"answer_delta", "thinking_delta"}:
                                    segment_type = "thinking" if event["type"] == "thinking_delta" else "text"
                                    if (trace and trace[-1].get("type") == segment_type
                                            and trace[-1].get("spawn_id") == spawn_id):
                                        trace[-1]["text"] += payload.get("text", "")
                                    else:
                                        trace_append({"type": segment_type, "text": payload.get("text", ""),
                                                      "spawn_id": spawn_id})
                                elif event["type"] == "tool_end":
                                    for segment in reversed(trace):
                                        if segment.get("type") == "tool" and segment.get("call_id") == payload["call_id"]:
                                            segment["status"] = payload.get("status", "ok")
                                            segment["summary"] = payload.get("summary", "")
                                            break
                            yield item
                        return outcome

                    try:
                        outcome = yield from wrap(
                            run_agent_mission(mission_id, goal, prompt, dossier, ctx,
                                              messages=sessions.get(mission_id),
                                              rounds=_env_int("PANEL_AGENT_ROUNDS", 8)))
                    except Exception as exc:  # noqa: BLE001 — 单个 spawn 崩溃不拖垮主 agent
                        logger.exception("spawn %s 执行失败", mission_id)
                        outcome = {"status": "failed", "report": "", "messages": None}
                    sessions[mission_id] = outcome.get("messages") or sessions.get(mission_id) or []
                    spawn_segment["status"] = "done" if outcome["status"] == "done" else "failed"
                    spawn_segment["summary"] = (outcome["report"] or "子 agent 未产出报告")[:200]
                    yield sse({"type": "spawn_end", "payload": {
                        "spawn_id": mission_id, "status": spawn_segment["status"],
                        "summary": spawn_segment["summary"]}})
                    output = {"summary": f"子 agent {mission_id}（{goal}）"
                                         f"{'已完成' if outcome['status'] == 'done' else '失败'}",
                              "detail": {"report": outcome["report"][:6000]} if outcome["status"] == "done"
                                        else {"error": "子 agent 未产出报告"}}
            else:
                yield sse({"type": "tool_start", "payload": {
                    "call_id": tc["id"], "tool": name, "label": _TOOL_LABELS.get(name, name),
                    "args_summary": json.dumps(args, ensure_ascii=False)[:200]}})
                output = _execute_tool(ctx, name, args)
                summary = str(output.get("summary") or "完成")
                trace_append({"type": "tool", "call_id": tc["id"], "tool": name,
                              "label": _TOOL_LABELS.get(name, name),
                              "args_summary": json.dumps(args, ensure_ascii=False)[:200],
                              "status": "ok", "summary": summary})
                yield sse({"type": "tool_end", "payload": {
                    "call_id": tc["id"], "status": "ok", "summary": summary,
                    "detail": json.dumps(output.get("detail"), ensure_ascii=False, default=str)[:2000]}})
            messages.append({"role": "tool", "tool_call_id": tc["id"],
                             "content": json.dumps({"summary": str(output.get("summary") or "完成"),
                                                    "detail": output.get("detail")},
                                                   ensure_ascii=False, default=str)[:6000]})

    # ---- 收尾：独立 JSON 通道收取评分合同（校验不过带错误重试）----
    contract: dict[str, Any] = {}
    last_error = ""
    for attempt in range(FINAL_RETRIES):
        messages.append({"role": "user", "content": _chair_final_prompt(jobs) if attempt == 0
                         else f"[系统] 上次输出校验未通过：{last_error}。请修正后重新只输出 JSON。"})
        result = call_llm_tools(messages, tools=[], temperature=0.2,
                                reasoning_effort=os.getenv("OPENAI_EFFORT_SCORING", "high"))
        text = str(result.get("text") or "").strip()
        messages.append({"role": "assistant", "content": text})
        parsed = parse_json_block(text)
        if parsed is None:
            last_error = "输出不是合法 JSON"
            continue
        last_error = _validate_contract(jobs, parsed)
        if not last_error:
            contract = parsed
            break
    if last_error:
        # 主席连续输出非法 → 兜底：空合同走保守缺省，评估照常出分
        trace_append({"type": "text", "text": f"评分合同未产出：{last_error[:120]}，按保守缺省出分"})

    # ---- 最后一轮：主席生成面向用人方的评估总结（markdown）----
    messages.append({"role": "user", "content": _CHAIR_SUMMARY_PROMPT})
    try:
        result = call_llm_tools(messages, tools=[], temperature=0.4,
                                reasoning_effort=os.getenv("OPENAI_EFFORT_SCORING", "high"))
        summary_text = str(result.get("text") or "").strip()
        messages.append({"role": "assistant", "content": summary_text})
    except Exception as exc:  # noqa: BLE001 — 总结生成失败不影响评分结果
        logger.warning("主席总结生成失败：%s", exc)
        summary_text = ""
    if summary_text:
        trace_append({"type": "text", "text": summary_text})
        yield sse({"type": "answer_delta", "payload": {"text": summary_text}})

    yield {"type": "node", "node": "panel_lead", "label": "评审团", "status": "done",
           "phase": "assessment", "message": f"评审团收工：派出 {spawned} 个子 agent。"}
    return {"job_fit_raw": assemble(jobs, contract), "trace": trace}


# ---------------------------------------------------------------------------
# 装配（确定性）：合同缺维补保守缺省，压 confidence，绝不静默补 0
# ---------------------------------------------------------------------------

def assemble(jobs: list, contract: dict[str, Any]) -> dict[str, Any]:
    by_id = {str(item.get("jd_id") or ""): item for item in contract.get("assessments", []) if isinstance(item, dict)}
    all_dim_keys = [key for key, _label, _weight in DIMENSIONS]
    assessments = []
    for job in jobs:
        item = by_id.get(job.id) or {}
        raw_dims = {str(d.get("key") or ""): d for d in item.get("dimensions") or [] if isinstance(d, dict)}
        missing: list[str] = []
        if not by_id:
            missing.append("主 agent 未产出评分合同")
        dims = []
        for key, label, _weight in DIMENSIONS:
            raw = raw_dims.get(key)
            if raw is None:
                dims.append({"key": key, "label": label, "score": MISSING_DIM_SCORE,
                             "rationale": "该维评估未覆盖，按保守缺省", "evidence": []})
                missing.append(f"维度 {key} 评估未覆盖")
            else:
                try:
                    score = round(float(raw.get("score")), 1)
                except (TypeError, ValueError):
                    score = MISSING_DIM_SCORE
                dims.append({"key": key, "label": label, "score": score,
                             "rationale": str(raw.get("rationale") or ""),
                             "evidence": list(raw.get("evidence") or [])})
        confidence = max(0.0, min(1.0, float(item.get("confidence") or 0.5)))
        if missing:
            confidence = round(confidence * 0.5, 2)
        notes = [str(x) for x in (item.get("missing_information") or []) if str(x).strip()]
        notes.extend(missing)
        assessments.append({
            "jd_id": job.id,
            "hard_requirements": item.get("hard_requirements") or [],
            "dimensions": dims,
            "confidence": confidence,
            "strengths": item.get("strengths") or [],
            "risks": item.get("risks") or [],
            "missing_information": notes,
            "interview_questions": item.get("interview_questions") or [],
            "assessment_summary": str(item.get("assessment_summary") or ""),
        })
    return {"assessments": assessments}
