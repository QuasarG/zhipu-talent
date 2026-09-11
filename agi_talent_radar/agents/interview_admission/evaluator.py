from __future__ import annotations

import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from pydantic import ValidationError

from agi_talent_radar.core import llm_client
from agi_talent_radar.core.models import CandidateResume

from .contracts import (
    AssessmentCard,
    OverallReview,
    PairAssessmentResult,
    ReviewCorrection,
    TaskAssessment,
)
from .job_card import EventObserver, LlmCallable


CHAIR_REVIEW_PROMPT = """
你是面试准入评估的主 agent（评审主席）。子评估 agent 已按岗位卡逐项完成任务评分，
下面是全部任务评分。请总审：检查遗漏、任务间尺度漂移、证据夸大和等级与岗位锚点不一致。
可以纠错，但每次修改必须给出原等级、新等级、原因和可追溯简历原文。
不要因为学历、专业、没写某工具、实习时长或到岗信息修改能力等级。

输出：{"corrections":[{"task_id":"...","original_level":0到4,"revised_level":0到4,
"reason":"...","evidence":["简历短原文"]}],
"interview_focus":[{"task_id":"...","focus":"与具体任务缺口绑定的验证重点"}],
"summary":"总审摘要（一到三句，面向用人方）"}。无需给总分或进面结论，它们由代码确定。
""".strip()


_SPAWN_PROMPT_TEMPLATE = """
你是面试准入评估的任务评估 agent。主席派你评估一项核心任务，你的产出就是该任务的最终评分。

# 岗位与任务
{task_block}

# 评分规则
- 只评价这一个任务，但必须阅读完整简历全文；可以纠正映射遗漏并自行从简历补证据。
- 评分采用唯一的 0–4 等级：0 无证据；1 相关基础；2 实际参与；3 独立胜任；4 成熟胜任。
- 任务锚点（2/3/4 级）是岗位化解释；不要机械要求数字，技能栏未写某工具不代表不会。
- 每个非零等级必须有简历可追溯短原文；背景证据不能单独支撑 2 分以上；
  可迁移证据必须说明迁移边界。
- reasoning_summary 是报告卡片上的一行概述：一句中文（20–36 字，最多 45 字），
  「结论 + 最关键事实」，禁止列举多个项目或换行。

# 输出（只输出一个 JSON 对象，不要 markdown）
{{"task_id":"{task_id}","level":0到4,"confidence":"high|medium|low",
"reasoning_summary":"20–36字一句话概述","transfer_boundary":"迁移成立的边界，无则空串",
"evidence":[{{"quote":"简历短原文","evidence_type":"direct|transferable|background",
"confidence":"high|medium|low","relevance":"它如何支撑本任务"}}],
"risks":["..."]}}
""".strip()


_TASK_EXECUTOR = ThreadPoolExecutor(
    max_workers=max(1, int(os.getenv("ADMISSION_TASK_CONCURRENCY", "50"))),
    thread_name_prefix="admission-task",
)

_EVIDENCE_TYPES = {"direct", "transferable", "background"}
_CONFIDENCE_LEVELS = {"high", "medium", "low"}


class _Trace:
    """线程安全的聊天段收集器：段 = 奖学金同款 text/tool/spawn，直接落 run_trace。"""

    def __init__(self, on_event: EventObserver | None) -> None:
        self.segments: list[dict[str, Any]] = []
        self.model_usage: list[dict[str, str]] = []
        self._on_event = on_event
        self._lock = threading.Lock()

    def segment(self, segment: dict[str, Any]) -> None:
        with self._lock:
            # spawn 段按 spawn_id 原位替换（状态落位重发不产生重复行）
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

    def spawn(self, spawn_id: str, title: str) -> dict[str, Any]:
        segment = {"type": "spawn", "spawn_id": spawn_id, "agent": "任务评估 Agent",
                   "title": title, "status": "running", "summary": ""}
        self.segment(segment)
        return segment

    def spawn_update(self, segment: dict[str, Any], status: str, summary: str) -> None:
        # 状态落位后整段重发：订阅方按 spawn_id 原位替换
        segment["status"] = status
        segment["summary"] = summary[:160]
        self.segment(segment)

    def observe_call(self, item: dict[str, str]) -> None:
        with self._lock:
            self.model_usage.append(item)


def evaluate_candidate_for_job(
    resume: CandidateResume | dict[str, Any],
    jd_id: str,
    card: AssessmentCard,
    llm: LlmCallable | None = None,
    on_event: EventObserver | None = None,
) -> PairAssessmentResult:
    candidate = resume if isinstance(resume, CandidateResume) else CandidateResume.model_validate(resume)
    assessment_card = card if isinstance(card, AssessmentCard) else AssessmentCard.model_validate(card)
    trace = _Trace(on_event)
    invoke = llm or _default_llm(trace)
    anonymized = _anonymize_resume(candidate)

    trace.text(f"对照岗位卡「{assessment_card.role_summary}」的 "
               f"{len(assessment_card.core_tasks)} 项核心任务，逐项派出子评估 agent。")

    assessments = _score_tasks(invoke, anonymized, assessment_card, trace)
    assessments = _validate_and_repair_evidence(invoke, anonymized, assessment_card, assessments)

    trace.text("全部任务评分完成，主席总审尺度、遗漏与证据夸大。")
    review = OverallReview.model_validate(
        invoke(
            CHAIR_REVIEW_PROMPT,
            {
                "resume_text": anonymized["raw_text"],
                "structured_resume": anonymized,
                "assessment_card": assessment_card.model_dump(),
                "task_assessments": [item.model_dump() for item in assessments],
            },
        )
    )
    assessments, corrections = _apply_review(assessments, review.corrections, anonymized["raw_text"])
    if review.summary:
        trace.text(review.summary)

    total_score = calculate_total_score(assessment_card, assessments)
    decision, reason = decide_admission(assessment_card, assessments, total_score)
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
    invoke: LlmCallable,
    resume: dict[str, Any],
    card: AssessmentCard,
    trace: _Trace,
) -> list[TaskAssessment]:
    """按核心任务并发 spawn 子评估 agent；每个子 agent 就是该任务的最终评分。"""
    segments_by_task: dict[str, dict[str, Any]] = {}
    lock = threading.Lock()

    def score_task(task):
        segment = trace.spawn(f"task_score:{task.id}", task.title)
        with lock:
            segments_by_task[task.id] = segment
        return _score_one_task(invoke, resume, card, {}, task.model_dump())

    futures = {_TASK_EXECUTOR.submit(score_task, task): task for task in card.core_tasks}
    by_id: dict[str, TaskAssessment] = {}
    first_error: RuntimeError | None = None
    for future in as_completed(futures):
        task = futures[future]
        segment = segments_by_task[task.id]
        try:
            assessment = future.result()
        except RuntimeError as exc:
            with lock:
                trace.spawn_update(segment, "failed", str(exc)[:160])
            first_error = first_error or exc
            continue
        with lock:
            trace.spawn_update(segment, "done",
                               f"评定 {assessment.level} 级（{assessment.confidence}）：{assessment.reasoning_summary}")
        by_id[task.id] = assessment
    if first_error is not None:
        raise first_error
    return [by_id[task.id] for task in card.core_tasks]


def _spawn_prompt(task: dict[str, Any], card: AssessmentCard) -> dict[str, Any]:
    anchors = task.get("anchors") or {}
    task_block = (
        f"岗位使命：{card.role_summary}\n"
        f"任务：{task['title']}（{'首要' if task['importance'] == 'primary' else '主要' if task['importance'] == 'major' else '补充'}）\n"
        f"要完成什么：{task['description']}\n"
        f"评价看什么：{task['evaluation_focus']}\n"
        f"等级锚点：2 级={anchors.get('level_2', '')}；3 级={anchors.get('level_3', '')}；4 级={anchors.get('level_4', '')}"
    )
    return {
        "system": _SPAWN_PROMPT_TEMPLATE.replace("{task_block}", task_block).replace("{task_id}", task["id"]),
        "payload": {"current_task": task},
    }


def _score_one_task(
    invoke: LlmCallable,
    resume: dict[str, Any],
    card: AssessmentCard,
    mapping: dict[str, Any],
    task: dict[str, Any],
    repair_feedback: list[str] | None = None,
) -> TaskAssessment:
    """单任务评分（子评估 agent 的产出）：宽容归一 + 校验失败回喂重试。

    GLM 对长 schema 的必填字段偶发遗漏，链路默认「单次输出可能不合规」：
    归一吸收字段缺失，重试吸收结构错误，都失败才按技术故障抛出。
    """
    spawn_prompt = _spawn_prompt(task, card)
    payload = {
        "resume_text": resume["raw_text"],
        "structured_resume": resume,
        "assessment_card": card.model_dump(),
        "current_task": task,
        "evidence_repair_feedback": repair_feedback or [],
    }
    last_error = ""
    for attempt in range(3):
        if attempt > 0:
            payload = {
                **payload,
                "evidence_repair_feedback": [
                    *(repair_feedback or []),
                    f"上次输出未通过校验：{last_error}。请严格按输出格式重新评分；"
                    "evidence 每项必须包含 quote/evidence_type/confidence/relevance 四个字段。",
                ],
            }
        raw = invoke(spawn_prompt["system"], {**payload, **spawn_prompt["payload"]})
        if not isinstance(raw, dict) or not raw:
            # 空响应不能静默归一成 0 分评分——那是把技术失败伪装成业务结论
            last_error = "模型未返回任何内容"
            continue
        raw = {**raw, "task_id": task["id"]}
        try:
            return TaskAssessment.model_validate(_normalize_task_payload(raw))
        except ValidationError as exc:
            last_error = str(exc)
    raise RuntimeError(f"任务 {task['id']} 评分输出连续 3 次不合规：{last_error}")


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


def _validate_and_repair_evidence(
    invoke: LlmCallable,
    resume: dict[str, Any],
    card: AssessmentCard,
    assessments: list[TaskAssessment],
) -> list[TaskAssessment]:
    tasks = {task.id: task for task in card.core_tasks}
    repaired: list[TaskAssessment] = []
    for assessment in assessments:
        invalid = [item.quote for item in assessment.evidence if not _quote_is_traceable(item.quote, resume["raw_text"])]
        if invalid:
            assessment = _score_one_task(
                invoke,
                resume,
                card,
                {},
                tasks[assessment.task_id].model_dump(),
                [f"以下引用无法在简历找到，请删除或改为真实短原文：{quote}" for quote in invalid],
            )
            invalid = [item.quote for item in assessment.evidence if not _quote_is_traceable(item.quote, resume["raw_text"])]
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


def _default_llm(trace: _Trace) -> LlmCallable:
    def invoke(prompt: str, payload: dict[str, Any]) -> dict[str, Any]:
        temperature = 0.3 if prompt.startswith("你是面试准入评估的任务评估 agent") else 0.05
        return llm_client.call_llm_json(
            prompt,
            payload,
            temperature=temperature,
            deep=True,
            on_call=lambda item: trace.observe_call({**item}),
        )

    return invoke
