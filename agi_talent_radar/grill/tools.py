"""画像澄清 Agent 工具注册表：9 个工具，handler(ctx, args) -> dict。

ctx 携带 session_id 与 emit；写状态的工具 handler 内完成收敛判定并推 profile/outline 事件。
移植自 grill/backend/agent/tools.py，改 import 指向 zhipu_talent 基础设施。
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable

from agi_talent_radar.core.llm_client import call_llm_json
from agi_talent_radar.grill import repository as state
from agi_talent_radar.grill.prompts import STATE_SNAPSHOT_HEADER

TOOL_RESULT_MAX_CHARS = 2000
# 蓝本选择/重检请求的消息句式（前端岗位卡片提交与提示词约定）
BLUEPRINT_RE = re.compile(r"我觉得「(.+?)」和我的需求最契合")
RETRY_RE = re.compile(r"都不太符合|换一批|重新检索|重新匹配|换方向")
JOB_ID_RE = re.compile(r"（岗位ID[:：]\s*(\d+)）")


def resolve_blueprint(sess: dict) -> dict | None:
    """从消息历史解析蓝本岗位完整记录：优先岗位ID，退回标题精确匹配。"""
    from agi_talent_radar.grill.jobs_store import find_by_title, full_job

    texts = [str(m.get("text") or "") for m in sess["messages"] if m.get("role") == "user"]
    for t in reversed(texts):
        m = JOB_ID_RE.search(t)
        if m:
            job = full_job(m.group(1))
            if job:
                return job
        m = BLUEPRINT_RE.search(t)
        if m:
            job = find_by_title(m.group(1))
            if job:
                return job
    return None


def blueprint_section(sess: dict) -> str:
    """蓝本 JD 全文注入段（拼进系统提示）；无蓝本时为空串。"""
    job = resolve_blueprint(sess)
    if not job:
        return ""
    return (
        "\n\n# 已选蓝本岗位（全文在此，对照提问直接引用，无需也不许再调 search_jobs 获取）\n"
        f"标题：{job.get('title')}\n岗位描述：{job.get('description')}\n岗位要求：{job.get('requirement')}"
    )

CONVERGED_NOTICE = (
    "所有必填字段置信度已达标（converged=true）。停止追问，输出画像总结请用户确认；"
    "用户明确确认后才可调用 finalize。"
)

Emit = Callable[[str, dict[str, Any]], None]


class ToolContext:
    def __init__(self, session_id: str, emit: Emit) -> None:
        self.session_id = session_id
        self.emit = emit

    def push_profile(self, profile: dict) -> None:
        self.emit("profile_update", {"profile": profile})

    def push_outline(self, outline: list) -> None:
        self.emit("outline_update", {"outline": outline})


# 工具 handler

def _ask_question(ctx: ToolContext, args: dict) -> dict:
    node_id = str(args.get("outline_node_id") or "")
    sess = state.get_session_by_id(ctx.session_id)
    outline = sess["outline"]
    for node in outline:
        if node["id"] == node_id and node["status"] == "pending":
            node["status"] = "active"
    if node_id:
        state.save_session(ctx.session_id, outline=outline)
        ctx.push_outline(outline)
    raw = args.get("options")
    options = [str(o).strip() for o in raw if str(o).strip()][:6] if isinstance(raw, list) else []
    subs: list[dict] = []
    raw_qs = args.get("questions")
    if isinstance(raw_qs, list):
        for q in raw_qs[:3]:
            if not isinstance(q, dict):
                continue
            text_ = str(q.get("text") or "").strip()
            if not text_:
                continue
            opts = q.get("options")
            subs.append({
                "text": text_,
                "options": [str(o).strip() for o in opts if str(o).strip()][:6] if isinstance(opts, list) else [],
                "multi_select": bool(q.get("multi_select")),
            })
    if not subs:
        subs = [{
            "text": str(args.get("question") or ""),
            "options": options,
            "multi_select": bool(args.get("multi_select")),
        }]
    return {
        "ok": True,
        "question": str(args.get("question") or ""),
        "mechanism": str(args.get("mechanism") or ""),
        "options": options,
        "questions": subs,
    }


def _update_profile_card(ctx: ToolContext, args: dict) -> dict:
    field = str(args.get("field") or "")
    sess = state.get_session_by_id(ctx.session_id)
    profile = sess["profile"]
    group = "required_fields" if field in profile["required_fields"] else (
        "optional_fields" if field in profile["optional_fields"] else None
    )
    if group is None:
        return {"ok": False, "error": f"未知字段 {field}，可选：{list(profile['required_fields']) + list(profile['optional_fields'])}"}
    confidence = max(0.0, min(1.0, float(args.get("confidence") or 0)))
    slot = profile[group][field]
    value = args.get("value")
    if isinstance(value, str) and value.startswith("["):  # LLM 偶把数组传成 JSON 字符串
        try:
            parsed = json.loads(value)
            value = parsed if isinstance(parsed, list) else value
        except json.JSONDecodeError:
            pass
    slot["value"] = value
    slot["confidence"] = confidence
    slot["evidence"] = str(args.get("evidence") or "")
    slot["status"] = "confirmed" if confidence >= state.CONFIDENCE_THRESHOLD else "probing"

    # 用户重新明确了冲突涉及的字段 → 自动消解相关 open 冲突
    for conflict in profile["conflicts"]:
        if conflict["status"] == "open" and field in conflict.get("fields", []):
            conflict["status"] = "resolved"
            conflict["resolution"] = f"字段 {field} 已被用户重新明确"

    converged = state.check_converged(profile)
    profile["converged"] = converged
    state.save_session(ctx.session_id, profile=profile, converged=converged)
    ctx.push_profile(profile)
    result = {"ok": True, "converged": converged}
    if converged:
        result["notice"] = CONVERGED_NOTICE
    return result


def _init_outline(ctx: ToolContext, args: dict) -> dict:
    sess = state.get_session_by_id(ctx.session_id)
    if sess["outline"]:
        return {"ok": False, "error": "大纲已存在，后续请用 insert_followup/mark_covered/mark_obsolete 维护"}
    nodes = []
    for i, item in enumerate(args.get("nodes") or [], start=1):
        nodes.append({
            "id": f"n{i}",
            "parent_id": None,
            "order": i,
            "topic": str(item.get("topic") or ""),
            "question_hint": str(item.get("question_hint") or ""),
            "linked_fields": list(item.get("linked_fields") or []),
            "status": "pending",
            "source": "initial",
            "answer_summary": None,
        })
    state.save_session(ctx.session_id, outline=nodes)
    ctx.push_outline(nodes)
    return {"ok": True, "node_ids": [n["id"] for n in nodes]}


def _insert_followup(ctx: ToolContext, args: dict) -> dict:
    sess = state.get_session_by_id(ctx.session_id)
    outline = sess["outline"]
    parent_id = str(args.get("parent_node_id") or "") or None
    siblings = [n for n in outline if n.get("parent_id") == parent_id]
    node = {
        "id": f"n{len(outline) + 1}",
        "parent_id": parent_id,
        "order": len(siblings) + 1,
        "topic": str(args.get("topic") or ""),
        "question_hint": str(args.get("question_hint") or ""),
        "linked_fields": list(args.get("linked_fields") or []),
        "status": "pending",
        "source": "dynamic",
        "answer_summary": None,
    }
    outline.append(node)
    state.save_session(ctx.session_id, outline=outline)
    ctx.push_outline(outline)
    return {"ok": True, "node_id": node["id"]}


def _mark_covered(ctx: ToolContext, args: dict) -> dict:
    return _set_node_status(ctx, str(args.get("node_id") or ""), "covered",
                            answer_summary=str(args.get("answer_summary") or ""))


def _mark_obsolete(ctx: ToolContext, args: dict) -> dict:
    sess = state.get_session_by_id(ctx.session_id)
    outline = sess["outline"]
    target = str(args.get("node_id") or "")
    doomed = {target}
    changed = True
    while changed:
        changed = False
        for n in outline:
            if n.get("parent_id") in doomed and n["id"] not in doomed:
                doomed.add(n["id"])
                changed = True
    found = False
    for n in outline:
        if n["id"] in doomed and n["status"] not in ("covered", "obsolete"):
            n["status"] = "obsolete"
            n["answer_summary"] = str(args.get("reason") or "")
            found = True
    if not found:
        return {"ok": False, "error": f"节点 {target} 不存在或已终结"}
    state.save_session(ctx.session_id, outline=outline)
    ctx.push_outline(outline)
    return {"ok": True}


def _set_node_status(ctx: ToolContext, node_id: str, status: str, answer_summary: str = "") -> dict:
    sess = state.get_session_by_id(ctx.session_id)
    outline = sess["outline"]
    for node in outline:
        if node["id"] == node_id:
            node["status"] = status
            if answer_summary:
                node["answer_summary"] = answer_summary
            state.save_session(ctx.session_id, outline=outline)
            ctx.push_outline(outline)
            return {"ok": True}
    return {"ok": False, "error": f"节点 {node_id} 不存在"}


def _detect_conflict(ctx: ToolContext, args: dict) -> dict:
    sess = state.get_session_by_id(ctx.session_id)
    profile = sess["profile"]
    fields = [str(f) for f in (args.get("fields") or [])]
    profile["conflicts"].append({
        "fields": fields,
        "description": str(args.get("description") or ""),
        "status": "open",
        "resolution": None,
    })
    state.save_session(ctx.session_id, profile=profile)
    ctx.push_profile(profile)
    return {"ok": True, "notice": "冲突已打标，请用 conflict_point 机制当面指出并逼用户排序"}


def _search_jobs(ctx: ToolContext, args: dict) -> dict:
    from agi_talent_radar.grill.jobs_store import search_jobs

    # 重复检索静默兜底：有蓝本且本轮无重检意图 → 返回空调用指令（ok=True，前端不渲染）
    sess = state.get_session_by_id(ctx.session_id)
    job = resolve_blueprint(sess) if sess else None
    texts = [str(m.get("text") or "") for m in (sess["messages"] if sess else []) if m.get("role") == "user"]
    if job and not (texts and RETRY_RE.search(texts[-1])):
        return {"ok": True, "jobs": [], "note": f"蓝本岗位「{job.get('title')}」全文已在系统上下文，无需再检索；请基于它继续提问"}

    try:
        jobs = search_jobs(
            str(args.get("query") or ""),
            top_k=int(args.get("top_k") or 5),
            job_category=str(args.get("job_category") or "") or None,
        )
        # 类别过滤是精确匹配，模型给的值常与库内枚举不符导致 0 命中 → 回退不带过滤重试
        if not jobs and args.get("job_category"):
            jobs = search_jobs(str(args.get("query") or ""), top_k=int(args.get("top_k") or 5))
    except Exception as exc:  # noqa: BLE001 检索坏了不伤主链路
        return {"ok": False, "jobs": [], "note": f"检索不可用：{exc}，请直接裸问"}
    for j in jobs:
        ex = str(j.get("requirement_excerpt") or "")
        j["requirement_excerpt"] = ex[:120] + ("…" if len(ex) > 120 else "")
    return {"ok": True, "jobs": jobs, "note": "检索结果仅作参照物，预填置信度不得超过 0.3；结果会以岗位卡片展示给用户，随后必须问契合度"}


def generate_deliverables(sess: dict) -> dict:
    """需求包生成（候选人画像 + JD 草稿 + 筛选标准）：finalize 与重新生成共用。"""
    profile = sess["profile"]
    req = profile["required_fields"]
    query = f"{req['position_name']['value'] or ''} {req['hard_skills']['value'] or ''}"
    reference_jds: list[dict] = []
    try:
        from agi_talent_radar.grill.jobs_store import search_jobs

        reference_jds = search_jobs(query, top_k=3)
    except Exception:
        reference_jds = []

    history_text = "\n".join(
        f"{'用户' if m['role'] == 'user' else 'Agent'}：{m['text']}"
        for m in sess["messages"]
        if m["text"].strip()
    )[-6000:]
    data = call_llm_json(
        "你是资深招聘 HR。根据用人经理的整场澄清对话与确认的画像卡，生成三部分交付物。只输出 JSON："
        '{"persona_profile": "中文字符串", "jd_draft": "markdown 字符串", '
        '"screening_criteria": {"hard_requirements": ["..."], "bonus_items": ["..."]}}。'
        "persona_profile 是候选人人物侧写（300-500 字）：这是什么样的人（背景轮廓）、可能擅长什么"
        "（硬技能落到场景）、可能做过/会做什么工作（呼应岗位方向）、未来会负责什么（入职角色预期）、"
        "性格/工作风格（从软素质偏好与取舍答案推断）；推断内容用「很可能」「倾向于」等推测措辞，"
        "与用户明确提出的要求区分开，不写成既定事实；像资深 HR 写的素描，不是字段清单的复读。"
        "JD 文风结构参照给定的真实同类 JD（不要照抄）。",
        {
            "profile_card": profile,
            "conversation": history_text,
            "blueprint_jd": blueprint_section(sess),
            "reference_jds": reference_jds,
        },
        temperature=0.3,
        conversation=True,
    )
    return {
        "persona_profile": str(data.get("persona_profile") or ""),
        "jd_draft": str(data.get("jd_draft") or ""),
        "screening_criteria": data.get("screening_criteria") or {},
        "reference_jobs": [
            {"job_id": j.get("job_id"), "title": j.get("title"), "score": j.get("score")}
            for j in reference_jds
        ],
    }


def _finalize(ctx: ToolContext, args: dict) -> dict:
    sess = state.get_session_by_id(ctx.session_id)
    if not sess["converged"]:
        return {"ok": False, "error": "必填字段未全部达标，禁止 finalize，继续追问"}
    if sess["deliverables"]:
        return {"ok": True, "deliverables": sess["deliverables"], "note": "需求包已生成过"}

    deliverables = generate_deliverables(sess)
    state.save_session(ctx.session_id, deliverables=deliverables)
    ctx.emit("deliverables", deliverables)
    return {"ok": True, "deliverables": deliverables}


# 注册表

def _props(**kwargs) -> dict:
    return kwargs


TOOLS: list[dict[str, Any]] = [
    {
        "name": "ask_question",
        "label": "提问",
        "description": "提出下一个澄清问题；基础信息可一次合并 2-3 个子问题（用 questions），深度追问一次只问一个",
        "parameters": _props(
            question={"type": "string", "description": "要问用户的问题，短而尖锐（合并提问时为第一个子问题）"},
            target_fields={"type": "array", "items": {"type": "string"}, "description": "问题针对的画像卡字段"},
            mechanism={"type": "string", "enum": ["clarify", "tradeoff", "conflict_point", "normal"]},
            outline_node_id={"type": "string", "description": "对应大纲节点 id"},
            options={
                "type": "array",
                "items": {"type": "string"},
                "description": "2-6 个预设回答选项（把问答题变选择题）：具体、互斥、覆盖常见取值；枚举字段给完备选项集，「其他」由前端追加不用生成；契合度问题（配合岗位卡片）传空数组",
            },
            multi_select={
                "type": "boolean",
                "description": "可叠加取值（技术栈/加分项/多 Base 等）= true；互斥取值（学历门槛/招聘类型等）= false",
            },
            questions={
                "type": "array",
                "items": {"type": "object", "properties": _props(
                    text={"type": "string"},
                    options={"type": "array", "items": {"type": "string"}},
                    multi_select={"type": "boolean"},
                )},
                "description": "合并提问的子问题数组（2-3 个，各带 2-6 个 options 与 multi_select）；仅用于基础信息打包问，深度追问不要用",
            },
        ),
        "required": ["question", "target_fields", "mechanism", "outline_node_id", "options"],
        "handler": _ask_question,
    },
    {
        "name": "update_profile_card",
        "label": "更新画像卡",
        "description": "更新画像卡某字段的取值/置信度/用户原话证据；返回收敛判定",
        "parameters": _props(
            field={"type": "string", "description": "字段名，如 position_name/hard_skills"},
            value={"description": "字段取值，字符串或字符串数组"},
            confidence={"type": "number", "description": "0-1；明确陈述0.9/间接推断0.6/RAG预填0.3"},
            evidence={"type": "string", "description": "用户原话证据"},
        ),
        "required": ["field", "value", "confidence", "evidence"],
        "handler": _update_profile_card,
    },
    {
        "name": "init_outline",
        "label": "建大纲",
        "description": "冷启动建立提问大纲骨架，仅首轮调用一次",
        "parameters": _props(
            nodes={"type": "array", "items": {"type": "object", "properties": _props(
                topic={"type": "string"}, question_hint={"type": "string"},
                linked_fields={"type": "array", "items": {"type": "string"}},
            )}},
        ),
        "required": ["nodes"],
        "handler": _init_outline,
    },
    {
        "name": "insert_followup",
        "label": "插入追问",
        "description": "用户回答延伸出新问题时，在父节点下动态插入分支",
        "parameters": _props(
            parent_node_id={"type": "string"},
            topic={"type": "string"},
            question_hint={"type": "string"},
            linked_fields={"type": "array", "items": {"type": "string"}},
        ),
        "required": ["parent_node_id", "topic", "question_hint"],
        "handler": _insert_followup,
    },
    {
        "name": "mark_covered",
        "label": "标记已覆盖",
        "description": "用户回答提前覆盖了后面的问题时标记已覆盖",
        "parameters": _props(
            node_id={"type": "string"},
            answer_summary={"type": "string"},
        ),
        "required": ["node_id", "answer_summary"],
        "handler": _mark_covered,
    },
    {
        "name": "mark_obsolete",
        "label": "废弃分支",
        "description": "用户改方向导致问题不再相关时废弃（子分支级联废弃）",
        "parameters": _props(
            node_id={"type": "string"},
            reason={"type": "string"},
        ),
        "required": ["node_id", "reason"],
        "handler": _mark_obsolete,
    },
    {
        "name": "detect_conflict",
        "label": "标记冲突",
        "description": "前后回答冲突时给画像卡打冲突标记，随后用 conflict_point 机制回指",
        "parameters": _props(
            fields={"type": "array", "items": {"type": "string"}},
            description={"type": "string"},
        ),
        "required": ["fields", "description"],
        "handler": _detect_conflict,
    },
    {
        "name": "search_jobs",
        "label": "检索岗位",
        "description": "RAG 检索真实校招岗位库（只读参照物：冷启动锚定/具体化追问弹药/JD 参照）",
        "parameters": _props(
            query={"type": "string"},
            top_k={"type": "integer", "default": 5},
            job_category={"type": "string", "description": "可选，按岗位类别过滤"},
        ),
        "required": ["query"],
        "handler": _search_jobs,
    },
    {
        "name": "finalize",
        "label": "生成需求包",
        "description": "收敛且用户确认后调用，生成候选人画像、JD 草稿与结构化筛选标准",
        "parameters": _props(),
        "required": [],
        "handler": _finalize,
    },
]

TOOLS_BY_NAME = {t["name"]: t for t in TOOLS}


def tools_schema() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": {
                    "type": "object",
                    "properties": t["parameters"],
                    "required": t["required"],
                },
            },
        }
        for t in TOOLS
    ]


def state_snapshot(sess: dict) -> str:
    """喂给 LLM 的当前状态摘要。"""
    slim_outline = [
        {"id": n["id"], "topic": n["topic"], "status": n["status"], "source": n["source"]}
        for n in sess["outline"]
    ]
    return STATE_SNAPSHOT_HEADER + json.dumps(
        {"profile_card": sess["profile"], "outline": slim_outline, "converged": sess["converged"]},
        ensure_ascii=False,
    )


__all__ = [
    "TOOLS",
    "TOOLS_BY_NAME",
    "TOOL_RESULT_MAX_CHARS",
    "ToolContext",
    "tools_schema",
    "state_snapshot",
    "blueprint_section",
]
