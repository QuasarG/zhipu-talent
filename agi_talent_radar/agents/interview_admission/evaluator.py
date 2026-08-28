from __future__ import annotations

import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

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


CAPABILITY_MAPPING_PROMPT = """
你是面试准入工作流的【能力映射】节点。只输出 JSON 对象。

你会同时看到完整脱敏简历、结构化简历和完整岗位评估卡。请创造性但克制地把真实项目、论文、
工程经历映射到岗位核心任务。论文、顶会、系统成果和相邻项目可以成为能力证据；技能栏没写某个
工具绝不代表不会。学历和专业只作为背景证据。不得评价实习时长、到岗、地点、薪资等可用性。

输出 {"task_mappings": [{"task_id": "...", "candidate_evidence": ["简历短原文"],
"mapping_reason": "为什么相关", "transfer_boundary": "迁移成立的边界"}]}。
能力映射只是导航，不是信息围栏；后续评分节点仍会读取完整简历并可自行补证据。
""".strip()


TASK_SCORING_PROMPT = """
你是面试准入工作流的【核心任务评分】节点。只输出 JSON 对象。

只评价输入中的一个核心任务，但必须阅读完整脱敏简历、完整结构化简历和整张岗位评估卡。
可以纠正能力映射遗漏并自行从简历补证据。评分采用唯一的 0–4 等级：
0 无证据；1 相关基础；2 实际参与；3 独立胜任；4 成熟胜任。
岗位卡的 2/3/4 锚点是该任务的岗位化解释。不要机械要求数字，不要把技能栏未写某工具推断为不会。

每个非零等级必须有简历可追溯短原文。证据类型只能是 direct / transferable / background，
置信度只能是 high / medium / low。背景证据不能单独支撑 2 分以上；可迁移证据必须说明迁移边界。

其中 reasoning_summary 是列表卡片上的一行概述，必须极简：只写一句中文，建议 20–36 个汉字，
最多 45 个汉字；采用“结论 + 最关键事实”的结构，只保留最能解释等级的一项事实。禁止列举多个
项目、工具或数字，禁止换行、分号、括号和重复 evidence。详细证据放在 evidence，不要塞进摘要。

输出：{"task_id":"...", "level":0到4, "confidence":"high|medium|low",
"reasoning_summary":"20–36字的一句话卡片摘要，最多45字", "transfer_boundary":"...",
"evidence":[{"quote":"简历短原文", "evidence_type":"direct|transferable|background",
"confidence":"high|medium|low", "relevance":"它如何支撑本任务"}], "risks":["..."]}。
""".strip()


OVERALL_REVIEW_PROMPT = """
你是面试准入工作流的【评分总审】节点。只输出 JSON 对象。

重新阅读完整脱敏简历、完整岗位评估卡和全部任务评分，检查遗漏、任务间尺度漂移、证据夸大和
等级与岗位锚点不一致。可以纠错，但每次修改必须给出原等级、新等级、原因和可追溯简历原文。
不要因为学历、专业、没写某工具、实习时长或到岗信息修改能力等级。

输出：{"corrections":[{"task_id":"...","original_level":0到4,"revised_level":0到4,
"reason":"...","evidence":["简历短原文"]}],
"interview_focus":[{"task_id":"...","focus":"与具体任务缺口绑定的验证重点"}],
"summary":"总审摘要"}。无需给总分或进面结论，它们由代码确定。
""".strip()


_TASK_EXECUTOR = ThreadPoolExecutor(
    max_workers=max(1, int(os.getenv("ADMISSION_TASK_CONCURRENCY", "50"))),
    thread_name_prefix="admission-task",
)


class _Trace:
    def __init__(self, observer: EventObserver | None) -> None:
        self.run_id = uuid4().hex
        self.events: list[dict[str, Any]] = []
        self.model_usage: list[dict[str, str]] = []
        self._observer = observer
        self._lock = threading.Lock()

    def event(
        self,
        node_id: str,
        label: str,
        status: str,
        summary: str,
        parent_id: str = "",
        detail: dict[str, Any] | None = None,
        error: str = "",
    ) -> None:
        item = {
            "run_id": self.run_id,
            "node_id": node_id,
            "parent_id": parent_id,
            "label": label,
            "status": status,
            "summary": summary,
            "detail": detail or {},
            "error": error,
            "at": _utc_now(),
        }
        with self._lock:
            self.events.append(item)
        if self._observer is not None:
            self._observer(item)

    def observe_call(self, item: dict[str, str]) -> None:
        with self._lock:
            self.model_usage.append(item)


def evaluate_candidate_for_job(
    resume: CandidateResume | dict[str, Any],
    jd_id: str,
    card: AssessmentCard | dict[str, Any],
    llm: LlmCallable | None = None,
    on_event: EventObserver | None = None,
) -> PairAssessmentResult:
    candidate = resume if isinstance(resume, CandidateResume) else CandidateResume.model_validate(resume)
    assessment_card = card if isinstance(card, AssessmentCard) else AssessmentCard.model_validate(card)
    trace = _Trace(on_event)
    invoke = llm or _default_llm(trace)
    anonymized = _anonymize_resume(candidate)

    trace.event("input_preparation", "输入准备", "running", "正在锁定并脱敏评估输入")
    trace.event("input_preparation", "输入准备", "completed", "完整简历与岗位卡已就绪")

    trace.event("capability_mapping", "能力映射", "running", "正在建立经历与核心任务的关联")
    mapping = invoke(
        CAPABILITY_MAPPING_PROMPT,
        {"resume_text": anonymized["raw_text"], "structured_resume": anonymized, "assessment_card": assessment_card.model_dump()},
    )
    trace.event(
        "capability_mapping",
        "能力映射",
        "completed",
        "能力映射完成",
        detail={"task_mappings": mapping.get("task_mappings", [])},
    )

    trace.event("task_scoring", "核心任务评分", "running", "核心任务已进入统一并发队列")
    assessments = _score_tasks(invoke, anonymized, assessment_card, mapping, trace)
    trace.event(
        "task_scoring",
        "核心任务评分",
        "completed",
        f"{len(assessments)} 个核心任务评分完成",
    )

    trace.event("evidence_validation", "证据校验", "running", "正在核对所有引用与简历原文")
    assessments = _validate_and_repair_evidence(
        invoke, anonymized, assessment_card, mapping, assessments, trace
    )
    trace.event("evidence_validation", "证据校验", "completed", "证据引用校验完成")

    trace.event("overall_review", "评分总审", "running", "正在复核任务间尺度与遗漏")
    review = OverallReview.model_validate(
        invoke(
            OVERALL_REVIEW_PROMPT,
            {
                "resume_text": anonymized["raw_text"],
                "structured_resume": anonymized,
                "assessment_card": assessment_card.model_dump(),
                "task_assessments": [item.model_dump() for item in assessments],
            },
        )
    )
    assessments, corrections = _apply_review(assessments, review, anonymized["raw_text"])
    trace.event(
        "overall_review",
        "评分总审",
        "completed",
        review.summary or "评分总审完成",
        detail={"corrections": [item.model_dump() for item in corrections]},
    )

    total_score = calculate_total_score(assessment_card, assessments)
    decision, reason = decide_admission(assessment_card, assessments, total_score)
    trace.event(
        "admission_decision",
        "准入决策与报告",
        "completed",
        reason,
        detail={"decision": decision, "total_score": total_score},
    )
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
        run_trace=trace.events,
    )


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


def _score_tasks(
    invoke: LlmCallable,
    resume: dict[str, Any],
    card: AssessmentCard,
    mapping: dict[str, Any],
    trace: _Trace,
) -> list[TaskAssessment]:
    futures = {
        _TASK_EXECUTOR.submit(_score_one_task, invoke, resume, card, mapping, task.model_dump()): task
        for task in card.core_tasks
    }
    by_id: dict[str, TaskAssessment] = {}
    for future in as_completed(futures):
        task = futures[future]
        node_id = f"task_score:{task.id}"
        try:
            assessment = future.result()
        except Exception as exc:
            trace.event(node_id, task.title, "failed", "任务评分失败", "task_scoring", error=str(exc))
            raise
        by_id[task.id] = assessment
        trace.event(
            node_id,
            task.title,
            "completed",
            f"能力等级 {assessment.level}，置信度 {assessment.confidence}",
            "task_scoring",
            detail=assessment.model_dump(),
        )
    return [by_id[task.id] for task in card.core_tasks]


def _score_one_task(
    invoke: LlmCallable,
    resume: dict[str, Any],
    card: AssessmentCard,
    mapping: dict[str, Any],
    task: dict[str, Any],
    repair_feedback: list[str] | None = None,
) -> TaskAssessment:
    raw = invoke(
        TASK_SCORING_PROMPT,
        {
            "resume_text": resume["raw_text"],
            "structured_resume": resume,
            "assessment_card": card.model_dump(),
            "current_task": task,
            "capability_mapping": mapping,
            "evidence_repair_feedback": repair_feedback or [],
        },
    )
    raw = {**raw, "task_id": task["id"]}
    return TaskAssessment.model_validate(raw)


def _validate_and_repair_evidence(
    invoke: LlmCallable,
    resume: dict[str, Any],
    card: AssessmentCard,
    mapping: dict[str, Any],
    assessments: list[TaskAssessment],
    trace: _Trace,
) -> list[TaskAssessment]:
    tasks = {task.id: task for task in card.core_tasks}
    repaired: list[TaskAssessment] = []
    for assessment in assessments:
        invalid = [item.quote for item in assessment.evidence if not _quote_is_traceable(item.quote, resume["raw_text"])]
        if invalid:
            trace.event(
                f"evidence_repair:{assessment.task_id}",
                tasks[assessment.task_id].title + "证据修正",
                "running",
                "发现不可追溯引用，正在局部重评",
                "evidence_validation",
                detail={"invalid_quotes": invalid},
            )
            assessment = _score_one_task(
                invoke,
                resume,
                card,
                mapping,
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
            trace.event(
                f"evidence_repair:{assessment.task_id}",
                tasks[assessment.task_id].title + "证据修正",
                "completed",
                f"局部重评完成，当前等级 {assessment.level}",
                "evidence_validation",
                detail=assessment.model_dump(),
            )
        elif assessment.level > 0 and not assessment.evidence:
            assessment = assessment.model_copy(update={"level": 0, "confidence": "low"})
        repaired.append(assessment)
    return repaired


def _apply_review(
    assessments: list[TaskAssessment],
    review: OverallReview,
    resume_text: str,
) -> tuple[list[TaskAssessment], list[ReviewCorrection]]:
    by_id = {item.task_id: item for item in assessments}
    accepted: list[ReviewCorrection] = []
    for correction in review.corrections:
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
        temperature = 0.3 if prompt == CAPABILITY_MAPPING_PROMPT else 0.15
        node_id = "capability_mapping" if prompt == CAPABILITY_MAPPING_PROMPT else "overall_review"
        if prompt == TASK_SCORING_PROMPT:
            node_id = f"task_score:{payload.get('current_task', {}).get('id', '')}"
        if prompt == OVERALL_REVIEW_PROMPT:
            temperature = 0.05
        return llm_client.call_llm_json(
            prompt,
            payload,
            temperature=temperature,
            deep=True,
            on_call=lambda item: trace.observe_call({**item, "node_id": node_id}),
        )

    return invoke


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
