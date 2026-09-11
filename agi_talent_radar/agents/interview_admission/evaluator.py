from __future__ import annotations

import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Generator

from pydantic import ValidationError

from agi_talent_radar.agents.job_fit.materials import (
    MaterialsContext,
    parse_json_block,
    tools_schema,
)
from agi_talent_radar.core import llm_client
from agi_talent_radar.core.models import CandidateResume

from .contracts import (
    AssessmentCard,
    OverallReview,
    PairAssessmentResult,
    ReviewCorrection,
    TaskAssessment,
)
from .job_card import EventObserver, LlmCallable  # noqa: F401  (EventObserver 供类型标注)

_TASK_EXECUTOR = ThreadPoolExecutor(
    max_workers=max(1, int(os.getenv("ADMISSION_TASK_CONCURRENCY", "50"))),
    thread_name_prefix="admission-task",
)


CHAIR_REVIEW_PROMPT = """
你是面试准入评估的主 agent（评审主席）。这是本次 agentic loop 的最后一轮。
子评估 agent 已按岗位卡逐项完成任务评分，
下面是全部任务评分。请做最后一轮总审并生成评估总结。

总审：检查遗漏、任务间尺度漂移、证据夸大和等级与岗位锚点不一致。
可以纠错，但每次修改必须给出原等级、新等级、原因和可追溯简历原文。
不要因为学历、专业、没写某工具、实习时长或到岗信息修改能力等级。

输出：{"corrections":[{"task_id":"...","original_level":0到4,"revised_level":0到4,
"reason":"...","evidence":["简历短原文"]}],
"interview_focus":[{"task_id":"...","focus":"与具体任务缺口绑定的验证重点"}],
"summary":"评估总结（面向用人方，3–6 句）：先概述各核心任务的等级与判断依据，
再指出最有价值的证据与最大的不确定性，最后给出结论性意见与面试建议。"}。
无需给总分或进面结论，它们由代码确定。
""".strip()


TOOL_LABELS = {
    "list_files": "盘点材料", "read_text": "读取文本", "read_pages": "视觉转译",
    "search_text": "检索内容", "verify_paper": "论文查证", "web_search": "全网检索",
}

WORKER_TOOLS = tools_schema()

_ADMISSION_SPAWN_SCHEMA = [{
    "type": "function",
    "function": {
        "name": "spawn_agent",
        "description": (
            "派出通用子 agent，针对指定材料与一个评估维度或方向完成独立阅读。"
            "prompt 必须说明材料范围、评估角度、证据要求和交付内容；子 agent 不能继续派生 agent。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "对应岗位卡核心任务 id"},
                "goal": {"type": "string", "description": "简短、具体的调查目标"},
                "prompt": {"type": "string", "description": "完整、自包含的任务约束与报告要求"},
                "agent_id": {"type": "string", "description": "续命已有子 agent 时填写"},
            },
            "required": ["task_id", "goal", "prompt"],
        },
    },
}]
ADMISSION_MAIN_TOOLS = WORKER_TOOLS + _ADMISSION_SPAWN_SCHEMA

FINAL_RETRIES = 3
AGENT_ROUNDS = max(1, int(os.getenv("ADMISSION_AGENT_ROUNDS", "8")))
MAIN_WORK_ROUNDS = max(1, int(os.getenv("ADMISSION_MAIN_WORK_ROUNDS", "15")))

_EVIDENCE_TYPES = {"direct", "transferable", "background"}
_CONFIDENCE_LEVELS = {"high", "medium", "low"}


class _Trace:
    """线程安全的聊天段收集器（奖学金同款 text/tool/spawn），直接落 run_trace。"""

    def __init__(self, on_event: EventObserver | None) -> None:
        self.segments: list[dict[str, Any]] = []
        self.model_usage: list[dict[str, str]] = []
        self._on_event = on_event
        self._lock = threading.Lock()

    def segment(self, segment: dict[str, Any]) -> None:
        with self._lock:
            # spawn 段按 spawn_id 原位替换（状态落位/children 更新重发不产生重复行）
            replaced = False
            if segment.get("type") == "spawn":
                for index, existing in enumerate(self.segments):
                    if existing.get("type") == "spawn" and existing.get("spawn_id") == segment.get("spawn_id"):
                        self.segments[index] = segment
                        replaced = True
                        break
            if not replaced:
                self.segments.append(segment)
        if self._on_event is not None:
            self._on_event(segment)

    def text(self, text: str) -> None:
        if text.strip():
            self.segment({"type": "text", "text": text})

    def text_update(self, key: str, text: str) -> None:
        if not text:
            return
        with self._lock:
            current = next((item for item in self.segments if item.get("_key") == key), None)
            if current is None:
                current = {"type": "text", "text": text, "_key": key}
                self.segments.append(current)
            else:
                current["text"] = text
        if self._on_event is not None:
            self._on_event(current)

    def spawn(self, spawn_id: str, title: str, prompt: str) -> dict[str, Any]:
        segment = {"type": "spawn", "spawn_id": spawn_id, "agent": "任务评估 Agent",
                   "title": title, "status": "running", "summary": "",
                   "prompt": prompt, "children": []}
        self.segment(segment)
        return segment

    def spawn_update(self, segment: dict[str, Any], status: str, summary: str) -> None:
        # 状态落位后整段重发：订阅方按 spawn_id 原位替换
        segment["status"] = status
        segment["summary"] = summary[:160]
        self.segment(segment)

    def append_child(self, spawn_id: str, child: dict[str, Any], key: str) -> None:
        """把子 agent 的工作段挂到它的 children（同 key 原位替换），并整段重发。"""
        with self._lock:
            for existing in self.segments:
                if existing.get("type") == "spawn" and existing.get("spawn_id") == spawn_id:
                    children = [*(existing.get("children") or [])]
                    tagged = {**child, "_key": key}
                    index = next((i for i, c in enumerate(children) if c.get("_key") == key), None)
                    if index is None:
                        children.append(tagged)
                    else:
                        children[index] = tagged
                    existing["children"] = children
                    break
        if self._on_event is not None:
            with self._lock:
                current = next((s for s in self.segments
                                if s.get("type") == "spawn" and s.get("spawn_id") == spawn_id), None)
            if current is not None:
                self._on_event(current)

    def observe_call(self, item: dict[str, str]) -> None:
        with self._lock:
            self.model_usage.append(item)


def evaluate_candidate_for_job(
    resume: CandidateResume | dict[str, Any],
    jd_id: str,
    card: AssessmentCard,
    on_event: EventObserver | None = None,
    materials: MaterialsContext | None = None,
) -> PairAssessmentResult:
    """面试准入 v2：主 agent 按岗位卡核心任务并发 spawn 子评估 agent。

    子评估 agent 是真正的 agent 循环：与主 agent 相同的材料只读工具（不能嵌套
    spawn），行为完全由 spawn prompt 约束；其叙述与工具调用实时进入过程 trace，
    最终产出该任务的评分 JSON（宽容归一 + 校验失败回喂重试）。
    """
    candidate = resume if isinstance(resume, CandidateResume) else CandidateResume.model_validate(resume)
    assessment_card = card if isinstance(card, AssessmentCard) else AssessmentCard.model_validate(card)
    trace = _Trace(on_event)
    anonymized = _anonymize_resume(candidate)

    trace.text(f"对照岗位卡「{assessment_card.role_summary}」的 "
               f"{len(assessment_card.core_tasks)} 项核心任务，正在按材料范围与评估维度拆分工作。")

    assessments, sessions = _score_tasks(anonymized, assessment_card, trace, materials)

    # 续命修正：不可追溯引用 → 同一个子 agent 带反馈继续（上下文保留、轮数重置）
    for index, assessment in enumerate(assessments):
        invalid = [item.quote for item in assessment.evidence
                   if not _quote_is_traceable(item.quote, anonymized["raw_text"])]
        if not invalid:
            continue
        session = sessions.get(assessment.task_id)
        task = next((t for t in assessment_card.core_tasks if t.id == assessment.task_id), None)
        if not session or task is None:
            continue
        spawn_id = next(
            (key for key, context in sessions.items()
             if key.startswith("task_agent:") and context is session),
            f"task_score:{assessment.task_id}",
        )
        trace.text(f"「{task.title}」发现 {len(invalid)} 条不可追溯引用，主席续命修正。")
        try:
            assessment, _ = _run_evaluator_mission(
                task.model_dump(), assessment_card, anonymized, materials, trace, spawn_id,
                messages=session,
                instruction=(f"以下引用无法在简历中追溯：{'、'.join(invalid)}。"
                             "请剔除或改为真实短原文后，重新输出完整评分 JSON。"),
                cont=1,
            )
            assessments[index] = assessment
            trace.append_child(spawn_id,
                               {"type": "text", "text": _assessment_markdown(assessment)}, key="report")
        except RuntimeError:
            pass  # 续命仍失败 → 交给本地确定性证据校验兜底
    assessments = _repair_evidence_locally(assessments, anonymized["raw_text"])

    trace.text("全部任务评分完成，主席总审尺度、遗漏与证据夸大。")
    review = OverallReview.model_validate(
        llm_client.call_llm_json(
            CHAIR_REVIEW_PROMPT,
            {
                "resume_text": anonymized["raw_text"],
                "structured_resume": anonymized,
                "assessment_card": assessment_card.model_dump(),
                "task_assessments": [item.model_dump() for item in assessments],
            },
            temperature=0.05,
            deep=True,
        )
    )
    assessments, corrections = _apply_review(assessments, review.corrections, anonymized["raw_text"])
    if review.summary:
        trace.text(review.summary)

    total_score = calculate_total_score(assessment_card, assessments)
    decision, reason = decide_admission(assessment_card, assessments, total_score)
    decision_label = "进入面试" if decision == "interview" else "不进入面试"
    trace.text(f"评估结论：{decision_label}（总分 {total_score}）。{reason}")

    return PairAssessmentResult(
        candidate_id=candidate.id,
        jd_id=jd_id,
        decision=decision,
        decision_reason=reason,
        total_score=total_score,
        task_assessments=assessments,
        review_corrections=corrections,
        interview_focus=review.interview_focus,
        summary=review.summary,
        model_usage=trace.model_usage,
        run_trace=trace.segments,
    )


def _score_tasks(
    resume: dict[str, Any],
    card: AssessmentCard,
    trace: _Trace,
    materials: MaterialsContext | None,
) -> tuple[list[TaskAssessment], dict[str, list[dict[str, Any]]]]:
    """主 agent 编排评估；模型不可用或未覆盖全部任务时兼容旧链路。"""
    try:
        return _score_tasks_agentic(resume, card, trace, materials)
    except (RuntimeError, AssertionError, KeyError, ValidationError, ValueError) as exc:
        if any(item.get("type") == "spawn" for item in trace.segments):
            raise RuntimeError(f"主 agent 编排中断：{str(exc)[:160]}") from exc
        trace.text(f"主 agent 编排未完成（{str(exc)[:80]}），补齐尚未覆盖的核心任务。")
        return _score_tasks_fallback(resume, card, trace, materials)


def _admission_main_system(resume: dict[str, Any], card: AssessmentCard,
                           materials: MaterialsContext | None) -> str:
    files = "\n".join(f"- {rel}" for rel in (materials.walk() if materials else [])) \
        or "（无独立材料文件，以简历全文为准）"
    return f"""你是面试准入评估的主 agent（评审主席）。你先理解岗位卡、简历和材料目录，
再通过 spawn_agent 把不同材料、不同核心任务或不同证据方向交给子 agent 针对性阅读。

编排规则：
1. 每轮最多同时调用两个 spawn_agent；同一子 agent 完成后才可续命，不得嵌套派生。
2. 每个 prompt 必须自包含，明确材料范围、评估维度/方向、需核对的问题、证据格式和边界。
3. 子 agent 之间应有明确分工，避免多人重复通读同一材料；你负责对照岗位锚点和汇总尺度得失。
4. 需要补证时用 agent_id 续命原 agent，保留上下文。全部核心任务得到报告后停止调用工具。
5. 不得根据姓名、性别、年龄、学校层级或其他敏感属性作判断。

岗位卡：
{json.dumps(card.model_dump(), ensure_ascii=False)}

匿名结构化:
{json.dumps(resume, ensure_ascii=False)[:5000]}

简历全文：
{resume.get('raw_text', '')[:12000]}

材料目录：
{files}"""


def _score_tasks_agentic(
    resume: dict[str, Any],
    card: AssessmentCard,
    trace: _Trace,
    materials: MaterialsContext | None,
) -> tuple[list[TaskAssessment], dict[str, list[dict[str, Any]]]]:
    task_by_id = {task.id: task for task in card.core_tasks}
    assessments: dict[str, TaskAssessment] = {}
    sessions: dict[str, list[dict[str, Any]]] = {}
    spawn_count = 0
    spawn_lock = threading.Lock()
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _admission_main_system(resume, card, materials)},
        {"role": "user", "content": (
            "开始评估。先说明材料与核心任务的拆分思路，然后按不同材料和评估方向派工；"
            "每轮最多并行两个子 agent。")},
    ]

    for round_index in range(MAIN_WORK_ROUNDS):
        chunks: list[str] = []
        key = f"main:{round_index}"

        def on_delta(delta: str) -> None:
            chunks.append(delta)
            trace.text_update(key, "".join(chunks))

        result = llm_client.call_llm_tools(
            messages, ADMISSION_MAIN_TOOLS, temperature=0.2, on_delta=on_delta,
            reasoning_effort=os.getenv("OPENAI_EFFORT_SCORING", "high"),
        )
        text = str(result.get("text") or "").strip()
        if text and not chunks:
            trace.text_update(key, text)
        calls = result.get("tool_calls") or []
        if not calls:
            if len(assessments) == len(task_by_id):
                break
            raise RuntimeError("主 agent 尚未覆盖全部核心任务")
        messages.append({"role": "assistant", "content": text,
                         "tool_calls": [{"id": tc["id"], "type": "function",
                                         "function": {"name": tc["name"], "arguments": tc["arguments"]}}
                                        for tc in calls]})

        spawn_calls = [tc for tc in calls if tc["name"] == "spawn_agent"]
        if len(spawn_calls) > 2:
            spawn_calls = spawn_calls[:2]
        direct_calls = [tc for tc in calls if tc["name"] != "spawn_agent"]

        def run_spawn(tc: dict[str, Any]) -> tuple[dict[str, Any], TaskAssessment | None, str, list[dict[str, Any]]]:
            nonlocal spawn_count
            segment: dict[str, Any] | None = None
            try:
                args = json.loads(tc.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            task_id = str(args.get("task_id") or "")
            task = task_by_id.get(task_id)
            if task is None:
                return tc, None, "", []
            agent_id = str(args.get("agent_id") or "").strip()
            continuing = agent_id in sessions
            if continuing:
                spawn_id = agent_id
                segment = next(item for item in trace.segments
                               if item.get("type") == "spawn" and item.get("spawn_id") == spawn_id)
                segment["status"] = "running"
                segment["prompt"] = str(args.get("prompt") or "")
                trace.segment(segment)
            else:
                with spawn_lock:
                    spawn_count += 1
                    spawn_id = f"task_agent:{spawn_count}"
                trace.spawn(spawn_id, str(args.get("goal") or task.title), str(args.get("prompt") or ""))
            segment = next(item for item in trace.segments
                           if item.get("type") == "spawn" and item.get("spawn_id") == spawn_id)
            prompt = str(args.get("prompt") or "").strip()
            try:
                assessment, context = _run_evaluator_mission(
                    task.model_dump(), card, resume, materials, trace, spawn_id,
                    messages=sessions.get(spawn_id), instruction=prompt,
                    cont=sum(1 for item in segment.get("children", [])
                             if str(item.get("_key", "")).startswith("prompt:")),
                )
            except Exception as exc:
                trace.spawn_update(segment, "failed", f"执行失败：{str(exc)[:120]}")
                raise
            trace.spawn_update(segment, "done",
                               f"评定 {assessment.level} 级（{assessment.confidence}）：{assessment.reasoning_summary}")
            trace.append_child(spawn_id, {"type": "text", "text": _assessment_markdown(assessment)}, key="report")
            return tc, assessment, spawn_id, context

        futures = [_TASK_EXECUTOR.submit(run_spawn, tc) for tc in spawn_calls]
        outcomes = [future.result() for future in futures]
        by_call: dict[str, dict[str, Any]] = {}
        for tc, assessment, spawn_id, context in outcomes:
            if assessment is None:
                by_call[tc["id"]] = {"summary": "task_id 不属于岗位卡", "detail": {"error": "无效任务"}}
                continue
            assessments[assessment.task_id] = assessment
            sessions[spawn_id] = context
            sessions[assessment.task_id] = context
            by_call[tc["id"]] = {"summary": f"{assessment.task_id} 已完成",
                                  "detail": {"agent_id": spawn_id, **assessment.model_dump()}}
        for tc in direct_calls:
            try:
                args = json.loads(tc.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            output = _execute_read_tool(materials, tc["name"], args)
            trace.segment({"type": "tool", "call_id": tc["id"], "tool": tc["name"],
                           "label": TOOL_LABELS.get(tc["name"], tc["name"]),
                           "args_summary": json.dumps(args, ensure_ascii=False)[:200],
                           "status": "ok", "summary": str(output.get("summary") or "完成")})
            by_call[tc["id"]] = output
        for tc in calls:
            output = by_call.get(tc["id"], {"summary": "本轮并行上限为两个子 agent",
                                             "detail": {"error": "请下一轮再派发"}})
            messages.append({"role": "tool", "tool_call_id": tc["id"],
                             "content": json.dumps(output, ensure_ascii=False, default=str)[:6000]})

    missing = [task.id for task in card.core_tasks if task.id not in assessments]
    if missing:
        raise RuntimeError(f"主 agent 未完成核心任务：{', '.join(missing)}")
    return [assessments[task.id] for task in card.core_tasks], sessions


def _score_tasks_fallback(
    resume: dict[str, Any],
    card: AssessmentCard,
    trace: _Trace,
    materials: MaterialsContext | None,
) -> tuple[list[TaskAssessment], dict[str, list[dict[str, Any]]]]:
    """按核心任务并发 spawn 子评估 agent（过程实时进 trace）。

    返回 (评分列表, 各子 agent 会话上下文)——上下文供主席续命（证据修正时复用）。"""
    segments_by_task: dict[str, dict[str, Any]] = {}
    sessions: dict[str, list[dict[str, Any]]] = {}
    first_error: RuntimeError | None = None
    lock = threading.Lock()

    def score_task(task):
        task_dict = task.model_dump()
        spawn_id = f"task_score:{task.id}"
        segment = trace.spawn(spawn_id, task.title, _spawn_prompt_text(task_dict))
        with lock:
            segments_by_task[task.id] = segment
        assessment, messages = _run_evaluator_mission(
            task_dict, card, resume, materials, trace, spawn_id)
        with lock:
            sessions[task.id] = messages
        return assessment

    futures = {_TASK_EXECUTOR.submit(score_task, task): task for task in card.core_tasks}
    by_id: dict[str, TaskAssessment] = {}
    for future in as_completed(futures):
        task = futures[future]
        segment = segments_by_task[task.id]
        try:
            assessment = future.result()
        except RuntimeError as exc:
            trace.spawn_update(segment, "failed", str(exc)[:160])
            first_error = first_error or exc
            continue
        trace.spawn_update(segment, "done",
                           f"评定 {assessment.level} 级（{assessment.confidence}）：{assessment.reasoning_summary}")
        trace.append_child(f"task_score:{task.id}",
                           {"type": "text", "text": _assessment_markdown(assessment)}, key="report")
        by_id[task.id] = assessment
    if first_error is not None:
        raise first_error
    return [by_id[task.id] for task in card.core_tasks], sessions


def _assessment_markdown(assessment: TaskAssessment) -> str:
    """子评估 agent 的完整报告（侧栏与主流程同款 markdown 渲染，不截断）。"""
    lines = [f"**评定 {assessment.level} 级（{assessment.confidence}）**：{assessment.reasoning_summary}"]
    if assessment.transfer_boundary:
        lines.append(f"- 迁移边界：{assessment.transfer_boundary}")
    if assessment.evidence:
        lines.append("")
        lines.append("证据：")
        lines.extend(f"- 「{e.quote}」（{e.evidence_type} / {e.confidence}）：{e.relevance}"
                     for e in assessment.evidence)
    if assessment.risks:
        lines.append("")
        lines.append("风险：")
        lines.extend(f"- {risk}" for risk in assessment.risks)
    return "\n".join(lines)


def _spawn_prompt_text(task: dict[str, Any]) -> str:
    """spawn 时的任务指令：只含该任务的目标、评价看什么与等级锚点（短任务卡）。

    评分规则与输出合同是所有任务共享的静态要求，放在 worker 系统提示里，
    不随每个 spawn 重复——派工气泡保持简短可读。"""
    anchors = task.get("anchors") or {}
    importance = {"primary": "首要", "major": "主要", "supporting": "补充"}.get(
        task.get("importance", ""), "补充")
    return (f"评估核心任务「{task.get('title', '')}」（{importance}任务）。\n"
            f"要完成什么：{task.get('description', '')}\n"
            f"评价看什么：{task.get('evaluation_focus', '')}\n"
            f"等级锚点：2 级={anchors.get('level_2', '')}；3 级={anchors.get('level_3', '')}；"
            f"4 级={anchors.get('level_4', '')}")


_SCORING_RULES = """
# 评分规则（所有任务统一）
- 评分采用唯一的 0–4 等级：0 无证据；1 相关基础；2 实际参与；3 独立胜任；4 成熟胜任。
- 每个非零等级必须有简历可追溯短原文；背景证据不能单独支撑 2 分以上；
  可迁移证据必须说明迁移边界。
- reasoning_summary 是报告卡片上的一行概述：一句中文（20–36 字，最多 45 字），
  「结论 + 最关键事实」，禁止换行与列举。

# 输出合同（证据收集完成后输出该任务的评分 JSON，不要 markdown、不要解释）
{"task_id":"<按主席指令>","level":0到4,"confidence":"high|medium|low",
"reasoning_summary":"20–36字一句话概述","transfer_boundary":"迁移成立的边界，无则空串",
"evidence":[{"quote":"简历短原文","evidence_type":"direct|transferable|background",
"confidence":"high|medium|low","relevance":"它如何支撑本任务"}}],
"risks":["..."]}

每个非零等级必须有简历可追溯短原文；不要因为学历、专业、没写某工具而降级。"""


def _evaluator_system(resume: dict[str, Any], materials: MaterialsContext | None) -> str:
    files = "\n".join(f"- {rel}" for rel in (materials.walk() if materials else [])) \
        or "（无原始材料文件，以简历全文为准）"
    return f"""你是面试准入评估的任务评估 agent。主席在任务指令里给出了你要评估的核心任务、
锚点——那就是你的全部职责。你拥有材料只读工具（不能派生其他 agent），
每次调工具前先用一两句话说明目的；证据收集完成后停止调用工具，按输出合同给出结果。

# 结构化简历
{json.dumps(resume, ensure_ascii=False)[:4000]}

# 简历全文（证据引用必须出自这里或材料原文）
{resume.get("raw_text", "")[:12000]}

# 材料目录（read_text/read_pages 的 file 取这里的相对路径）
{files}
{_SCORING_RULES}

# 事实纪律
结论必须落在简历/材料原文上，查不到就明说，禁止推测；
技能栏未写某工具不代表不会；学历专业只作背景证据。"""


def _run_evaluator_mission(
    task: dict[str, Any],
    card: AssessmentCard,
    resume: dict[str, Any],
    materials: MaterialsContext | None,
    trace: _Trace,
    spawn_id: str,
    messages: list[dict[str, Any]] | None = None,
    instruction: str | None = None,
    cont: int = 0,
) -> tuple[TaskAssessment, list[dict[str, Any]]]:
    """子评估 agent 循环（messages 传入 = 续命，上下文保留、轮数重置）。

    叙述/工具调用实时进 children；最终产出任务评分 JSON，失败按技术故障抛出。"""
    prompt = instruction or _spawn_prompt_text(task)
    if messages is None:
        messages = [
            {"role": "system", "content": _evaluator_system(resume, materials)},
            {"role": "user", "content": f"[主席] {prompt}"},
        ]
        trace.append_child(spawn_id, {"type": "text", "text": prompt}, key="prompt")
    else:
        messages.append({"role": "user", "content": f"[主席] {instruction}"})
        trace.append_child(spawn_id, {"type": "text", "text": f"[续命指令] {instruction}"},
                           key=f"prompt:{cont}")
    narration_index = 0
    report_text = ""

    for _round in range(AGENT_ROUNDS):
        narration_index += 1
        narration_key = f"narration:{narration_index}"
        narration_chunks: list[str] = []

        def on_delta(delta: str) -> None:
            narration_chunks.append(delta)
            trace.append_child(spawn_id, {"type": "text", "text": "".join(narration_chunks)},
                               key=narration_key)

        result = llm_client.call_llm_tools(messages, WORKER_TOOLS, temperature=0.2,
                                           on_delta=on_delta,
                                           reasoning_effort=os.getenv("OPENAI_EFFORT_SCORING", "high"))
        tool_calls = result.get("tool_calls") or []
        text = str(result.get("text") or "").strip()
        report_text = text
        if text and not narration_chunks:
            trace.append_child(spawn_id, {"type": "text", "text": text}, key=narration_key)
        if not tool_calls:
            break
        messages.append({"role": "assistant", "content": text,
                         "tool_calls": [{"id": tc["id"], "type": "function",
                                         "function": {"name": tc["name"], "arguments": tc["arguments"]}}
                                        for tc in tool_calls]})
        for tc in tool_calls:
            try:
                args = json.loads(tc.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            label = TOOL_LABELS.get(tc["name"], tc["name"])
            child_key = f"tool:{tc['id']}"
            trace.append_child(spawn_id, {"type": "tool", "call_id": tc["id"], "tool": tc["name"],
                                          "label": label, "args_summary": json.dumps(args, ensure_ascii=False)[:200]},
                               key=child_key)
            output = _execute_read_tool(materials, tc["name"], args)
            summary = str(output.get("summary") or "完成")
            trace.append_child(spawn_id, {"type": "tool", "call_id": tc["id"], "tool": tc["name"],
                                          "label": label, "args_summary": json.dumps(args, ensure_ascii=False)[:200],
                                          "status": "ok", "summary": summary},
                               key=child_key)
            messages.append({"role": "tool", "tool_call_id": tc["id"],
                             "content": json.dumps({"summary": summary, "detail": output.get("detail")},
                                                   ensure_ascii=False, default=str)[:6000]})

    # ---- 独立 JSON 通道收取任务评分合同（宽容归一 + 校验失败回喂重试）----
    last_error = ""
    payload = {"resume_text": resume["raw_text"], "structured_resume": resume,
               "assessment_card": card.model_dump(), "current_task": task}
    for attempt in range(FINAL_RETRIES):
        messages.append({"role": "user", "content": (
            _task_output_contract(task) if attempt == 0 else
            f"[系统] 上次输出校验未通过：{last_error}。请严格按输出合同重新只输出一个 JSON 对象；"
            "evidence 每项必须包含 quote/evidence_type/confidence/relevance 四个字段。")})
        result = llm_client.call_llm_tools(messages, tools=[], temperature=0.2,
                                           reasoning_effort=os.getenv("OPENAI_EFFORT_SCORING", "high"))
        text = str(result.get("text") or "").strip()
        messages.append({"role": "assistant", "content": text})
        parsed = parse_json_block(text)
        if parsed is None:
            last_error = "输出不是合法 JSON"
            continue
        raw = {**parsed, "task_id": task["id"]}
        try:
            return TaskAssessment.model_validate(_normalize_task_payload(raw)), messages
        except ValidationError as exc:
            last_error = str(exc)
    if not report_text and not last_error:
        last_error = "模型未返回任何内容"
    raise RuntimeError(f"任务 {task['id']} 评分输出连续 {FINAL_RETRIES} 次不合规：{last_error}")


def _task_output_contract(task: dict[str, Any]) -> str:
    return f"""任务「{task['title']}」的证据收集完成。只输出一个 JSON 对象（不要 markdown、不要解释）：

{{"task_id":"{task['id']}","level":0到4,"confidence":"high|medium|low",
"reasoning_summary":"20–36字一句话概述","transfer_boundary":"迁移成立的边界，无则空串",
"evidence":[{{"quote":"简历短原文","evidence_type":"direct|transferable|background",
"confidence":"high|medium|low","relevance":"它如何支撑本任务"}}],
"risks":["..."]}}

每个非零等级必须有简历可追溯短原文；不要因为学历、专业、没写某工具而降级。"""


def _execute_read_tool(materials: MaterialsContext | None, name: str, args: dict[str, Any]) -> dict[str, Any]:
    """子评估 agent 的材料只读工具集（无 spawn、无写入）。"""
    from agi_talent_radar.agents.job_fit.panel import _execute_tool

    if name == "spawn_agent":
        return {"summary": "子 agent 不能派生 agent", "detail": {"error": "禁止嵌套 spawn"}}
    return _execute_tool(materials, name, args)


def _repair_evidence_locally(
    assessments: list[TaskAssessment],
    resume_text: str,
) -> list[TaskAssessment]:
    """确定性证据校验：不可追溯引用剔除 + 按证据类型封顶等级（不再依赖 LLM 回喂）。"""
    repaired: list[TaskAssessment] = []
    for assessment in assessments:
        invalid = [item.quote for item in assessment.evidence if not _quote_is_traceable(item.quote, resume_text)]
        if invalid:
            valid_evidence = [item for item in assessment.evidence if item.quote not in invalid]
            level = _level_cap_from_evidence(assessment.level, valid_evidence)
            assessment = assessment.model_copy(
                update={"evidence": valid_evidence, "level": level, "confidence": "low"}
            )
        elif assessment.level > 0 and not assessment.evidence:
            assessment = assessment.model_copy(update={"level": 0, "confidence": "low"})
        repaired.append(assessment)
    return repaired


def _normalize_task_payload(raw: dict[str, Any]) -> dict[str, Any]:
    """宽容归一：吸收 GLM 偶发的字段遗漏/类型漂移，再交 pydantic 硬校验。"""
    payload = dict(raw)
    evidence: list[dict[str, Any]] = []
    for item in payload.get("evidence") or []:
        if not isinstance(item, dict):
            continue
        quote = str(item.get("quote") or "").strip()
        if len(quote) < 2:
            continue  # 没有可用引文的条目无法核验，直接丢弃
        evidence_type = str(item.get("evidence_type") or "").strip()
        confidence = str(item.get("confidence") or "").strip()
        relevance = str(item.get("relevance") or "").strip()
        evidence.append({
            "quote": quote,
            # 缺类型按背景证据兜底（评分规则本就限制背景证据单独支撑高分）
            "evidence_type": evidence_type if evidence_type in _EVIDENCE_TYPES else "background",
            "confidence": confidence if confidence in _CONFIDENCE_LEVELS else "low",
            "relevance": relevance if len(relevance) >= 2 else "未说明支撑关系",
        })
    payload["evidence"] = evidence
    try:
        payload["level"] = max(0, min(4, int(float(payload.get("level")))))
    except (TypeError, ValueError):
        payload["level"] = 0
        payload["confidence"] = "low"
    if str(payload.get("confidence") or "").strip() not in _CONFIDENCE_LEVELS:
        payload["confidence"] = "low"
    payload["reasoning_summary"] = str(payload.get("reasoning_summary") or "")
    payload["transfer_boundary"] = str(payload.get("transfer_boundary") or "")
    payload["risks"] = [str(r) for r in (payload.get("risks") or []) if str(r).strip()]
    return payload


def calculate_total_score(card: AssessmentCard, assessments: list[TaskAssessment]) -> float:
    levels = {item.task_id: item.level for item in assessments}
    weighted = sum((levels.get(task.id, 0) / 4 * 100) * task.coefficient for task in card.core_tasks)
    total_weight = sum(task.coefficient for task in card.core_tasks)
    return round(weighted / total_weight, 1) if total_weight else 0.0


def decide_admission(
    card: AssessmentCard,
    assessments: list[TaskAssessment],
    total_score: float,
) -> tuple[str, str]:
    levels = {item.task_id: item.level for item in assessments}
    failed_primary = [task.title for task in card.core_tasks if task.importance == "primary" and levels.get(task.id, 0) < 2]
    if failed_primary:
        return "no_interview", "首要任务未达到实际参与等级：" + "、".join(failed_primary)
    if total_score < 60:
        return "no_interview", f"核心任务加权总分 {total_score:.1f}，低于 60 分准入线"
    return "interview", f"首要任务均达到 2 级且加权总分 {total_score:.1f} 达到准入线"


def _apply_review(
    assessments: list[TaskAssessment],
    corrections: list[ReviewCorrection],
    resume_text: str,
) -> tuple[list[TaskAssessment], list[ReviewCorrection]]:
    by_id = {item.task_id: item for item in assessments}
    accepted: list[ReviewCorrection] = []
    for correction in corrections:
        current = by_id.get(correction.task_id)
        if current is None or correction.original_level != current.level:
            continue
        if correction.evidence and not all(_quote_is_traceable(quote, resume_text) for quote in correction.evidence):
            continue
        by_id[correction.task_id] = current.model_copy(update={"level": correction.revised_level})
        accepted.append(correction)
    return [by_id[item.task_id] for item in assessments], accepted


def _level_cap_from_evidence(level: int, evidence: list[Any]) -> int:
    if not evidence:
        return 0
    types = {item.evidence_type for item in evidence}
    if types == {"background"}:
        return min(level, 1)
    if "direct" not in types:
        return min(level, 3)
    return level


def _quote_is_traceable(quote: str, resume_text: str) -> bool:
    normalized_quote = re.sub(r"\s+", "", quote).strip("，。；：,.;: ")
    normalized_resume = re.sub(r"\s+", "", resume_text)
    return len(normalized_quote) >= 2 and normalized_quote in normalized_resume


def _anonymize_resume(candidate: CandidateResume) -> dict[str, Any]:
    structured = candidate.model_dump(exclude={"document_analysis"})
    name = str(structured.get("name", "")).strip()
    raw_text = str(structured.get("raw_text", ""))
    if name:
        raw_text = raw_text.replace(name, "候选人")
    structured["name"] = "候选人"
    structured["raw_text"] = raw_text
    return structured
