from __future__ import annotations

import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

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
你是面试准入双 Agent 链路中的【督导 Agent】。只输出 JSON 对象。

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
        actor: str = "system",
        event_type: str = "stage",
        target_id: str = "",
        event_kind: str = "status",
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
            "actor": actor,
            "event_type": event_type,
            "agent_id": node_id if node_id.startswith(("task_score:", "evidence_repair:")) else (
                node_id if node_id in {"capability_mapping", "overall_review"} else "system"
            ),
            "agent_type": "task_scorer" if node_id.startswith(("task_score:", "evidence_repair:")) else (
                {"capability_mapping": "mapper", "overall_review": "reviewer"}.get(node_id, "system")
            ),
            "target_id": target_id,
            "event_kind": event_kind,
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

    trace.event(
        "capability_mapping", "评估 Agent", "running", "正在建立经历与核心任务的关联",
        actor="evaluator", event_type="thinking",
        event_kind="request", detail={"输入材料": ["完整脱敏简历", "完整结构化简历", "完整岗位评估卡"]},
    )
    mapping = invoke(
        CAPABILITY_MAPPING_PROMPT,
        {"resume_text": anonymized["raw_text"], "structured_resume": anonymized, "assessment_card": assessment_card.model_dump()},
    )
    mapped_count = len(mapping.get("task_mappings", []) or [])
    trace.event(
        "capability_mapping",
        "能力映射",
        "completed",
        f"已把简历经历映射到 {mapped_count} 项核心任务，作为逐项评分的导航",
        detail={"task_mappings": mapping.get("task_mappings", [])},
        actor="evaluator",
        target_id="system", event_kind="handoff",
    )

    trace.event(
        "task_scoring", "评估 Agent", "running", "正在逐项核对核心任务与候选人证据",
        actor="evaluator", event_type="thinking",
    )
    assessments = _score_tasks(invoke, anonymized, assessment_card, mapping, trace)
    trace.event(
        "task_scoring",
        "核心任务评分",
        "completed",
        f"{len(assessments)} 个核心任务评分完成",
        actor="evaluator",
    )

    trace.event(
        "evidence_validation", "结果校验", "running", "正在核对所有引用与简历原文",
        event_type="validation",
    )
    assessments = _validate_and_repair_evidence(
        invoke, anonymized, assessment_card, mapping, assessments, trace
    )
    trace.event(
        "evidence_validation", "结果校验", "completed", "证据引用校验完成",
        event_type="validation",
    )

    trace.event(
        "overall_review", "督导 Agent", "running", "正在独立复核尺度、遗漏与证据夸大",
        actor="observer", event_type="observer",
        event_kind="request", detail={"收到的任务评分": [item.model_dump() for item in assessments],
                                      "输入材料": ["完整脱敏简历", "完整岗位评估卡"]},
    )
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
        detail={"corrections": [item.model_dump() for item in corrections], "面试重点": review.interview_focus},
        actor="observer",
        event_type="observer",
        target_id="system", event_kind="handoff",
    )

    total_score = calculate_total_score(assessment_card, assessments)
    decision, reason = decide_admission(assessment_card, assessments, total_score)
    trace.event(
        "admission_decision",
        "硬门槛裁决",
        "completed",
        reason,
        detail={"decision": decision, "total_score": total_score},
        event_type="decision",
    )
    trace.event(
        "result_formatter",
        "报告生成",
        "completed",
        "评估结论、证据与面试重点已写入报告",
        detail={"decision": decision, "total_score": total_score},
        event_type="report",
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
    def score_task(task):
        trace.event(
            f"task_score:{task.id}", task.title, "running", f"正在评估：{task.title}",
            "task_scoring", actor="evaluator", event_kind="request",
            detail={"当前任务": task.model_dump(), "收到的能力映射": mapping,
                    "输入材料": ["完整脱敏简历", "完整结构化简历", "完整岗位卡"]},
        )
        return _score_one_task(invoke, resume, card, mapping, task.model_dump())
    futures = {
        _TASK_EXECUTOR.submit(score_task, task): task
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
            f"评定 {assessment.level} 级（{assessment.confidence}）：{assessment.reasoning_summary}",
            "task_scoring",
            detail=assessment.model_dump(),
            actor="evaluator",
            target_id="system", event_kind="handoff",
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
    """单任务评分：输出先做宽容归一；pydantic 校验失败带错误回喂重试。

    GLM 对长 schema 的必填字段偶发遗漏（同源于 panel 链路 1210 教训），链路设计
    默认「单次输出可能不合规」：归一吸收字段缺失，重试吸收结构错误，都失败才算
    技术故障交给上层落失败态。
    """
    payload = {
        "resume_text": resume["raw_text"],
        "structured_resume": resume,
        "assessment_card": card.model_dump(),
        "current_task": task,
        "capability_mapping": mapping,
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
        raw = invoke(TASK_SCORING_PROMPT, payload)
        if not isinstance(raw, dict) or not raw:
            # 空响应不能静默归一成 0 分评分——那是把技术失败伪装成业务结论
            last_error = "模型未返回任何内容"
            continue
        raw = {**raw, "task_id": task["id"]}
        try:
            return TaskAssessment.model_validate(_normalize_task_payload(raw))
        except ValidationError as exc:
            last_error = str(exc)
    raise RuntimeError(f"任务 {task['id']} 评分输出连续 {3} 次不合规：{last_error}")


_EVIDENCE_TYPES = {"direct", "transferable", "background"}
_CONFIDENCE_LEVELS = {"high", "medium", "low"}


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
                actor="evaluator",
                event_type="validation",
                event_kind="request",
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
                f"证据修正后评定 {assessment.level} 级：{assessment.reasoning_summary}",
                "evidence_validation",
                detail=assessment.model_dump(),
                actor="evaluator",
                event_type="validation",
                event_kind="handoff", target_id="system",
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
