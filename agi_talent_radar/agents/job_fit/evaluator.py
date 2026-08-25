from __future__ import annotations

from collections.abc import Callable, Iterable
import json
from typing import Any

from agi_talent_radar.core import llm_client
from agi_talent_radar.core.models import (
    CandidateJobFitEvaluation,
    CandidateResume,
    InterviewDecision,
    JobDefinition,
    JobFitAssessment,
    JobFitDimension,
    JobFitFinding,
    JobRequirementAssessment,
)


DIMENSIONS = (
    ("direct_task_match", "直接任务匹配", 30.0),
    ("technical_depth", "技术深度", 20.0),
    ("ownership", "本人贡献与主导性", 15.0),
    ("evidence_quality", "结果与证据质量", 15.0),
    ("engineering_scale", "工程与规模", 10.0),
    ("transferability", "可迁移性", 10.0),
)

INTERVIEW_SCORE = 70.0
HOLD_SCORE = 55.0
INTERVIEW_DIRECT_MATCH = 3.0
HOLD_DIRECT_MATCH = 2.5

JOB_FIT_PROMPT = """
你是为用人方分配面试资源的【JD 面试准入评估 Agent】。只输出 JSON 对象。

任务：把同一份简历分别对照每一个 JD。每个 JD 必须独立判断，禁止跨 JD 平均、互相补偿，
也禁止因为学校、论文、竞赛或公司名气而跳过岗位要求。

事实纪律：
1. 只能使用简历和 JD 明文；简历没写的事实必须标 unknown，不能标 unmet。
2. met 必须引用能够直接支持该要求的简历原文；相邻关键词不等于做过核心任务。
3. unmet 仅用于简历明确提供了相反事实，例如年限明确不足、学历明确不符。
4. “优先、最好、加分、有则更佳”等偏好绝不能列入 hard_requirements。
5. 不输出 decision 和总分，它们由系统门禁确定。
6. evidence 必须是简历中的短原文，不能写你的概括。

每个 JD 输出：
{
  "jd_id": "原样返回",
  "hard_requirements": [
    {"requirement": "JD 中的明确必备条件", "status": "met|unmet|unknown", "evidence": ["简历原文"], "rationale": "判断理由"}
  ],
  "dimensions": [
    {"key": "固定维度 key", "score": 0到5, "rationale": "理由", "evidence": ["简历原文"]}
  ],
  "strengths": [{"summary": "与该 JD 直接相关的优势", "evidence": ["简历原文"]}],
  "risks": [{"summary": "与该 JD 相关的风险", "evidence": ["简历原文"]}],
  "missing_information": ["会影响准入、但简历没有提供的信息"],
  "interview_questions": ["用于验证关键 claim 或风险的问题"],
  "confidence": 0到1,
  "assessment_summary": "一句话说明为什么值得或不值得花面试资源"
}

固定维度必须完整输出且只能使用以下 key：
- direct_task_match：是否真正做过 JD 核心工作
- technical_depth：方法细节、问题难度和关键技术判断
- ownership：本人具体贡献和主导性
- evidence_quality：指标、上线、发表、开源、验收及可核验性
- engineering_scale：数据、训练、系统规模和端到端闭环
- transferability：相邻经验迁移到 JD 核心任务的可信度

顶层格式：{"assessments": [上述对象]}。顺序与输入 jobs 一致，不要输出 Markdown。
""".strip()


LlmCallable = Callable[[str, dict[str, Any]], dict[str, Any]]


def evaluate_candidate_against_jobs(
    resume: CandidateResume | dict[str, Any],
    jobs: Iterable[JobDefinition | dict[str, Any]],
    llm: LlmCallable | None = None,
    academic_report: dict[str, Any] | None = None,
) -> CandidateJobFitEvaluation:
    """一次模型调用完成一份简历对多个 JD 的独立准入评估。"""
    candidate = resume if isinstance(resume, CandidateResume) else CandidateResume.model_validate(resume)
    job_list = [job if isinstance(job, JobDefinition) else JobDefinition.model_validate(job) for job in jobs]
    if not job_list:
        raise ValueError("至少需要一个激活的 JD 才能进行面试准入评估。")
    if len({job.id for job in job_list}) != len(job_list):
        raise ValueError("JD id 必须唯一。")

    raw = _request_assessments(candidate, job_list, llm, academic_report)
    return _build_evaluation(candidate, job_list, raw)


def _request_assessments(
    candidate: CandidateResume,
    job_list: list[JobDefinition],
    llm: LlmCallable | None = None,
    academic_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    invoke = llm or _call_llm
    return invoke(
        JOB_FIT_PROMPT,
        {
            "resume": candidate.model_dump(exclude={"document_analysis"}),
            "jobs": [job.model_dump() for job in job_list],
            "academic_report": academic_report or {},
        },
    )


def _build_evaluation(
    candidate: CandidateResume,
    job_list: list[JobDefinition],
    raw: dict[str, Any],
) -> CandidateJobFitEvaluation:
    raw_by_id = {
        str(item.get("jd_id", "")): item
        for item in raw.get("assessments", [])
        if isinstance(item, dict)
    }
    missing = [job.id for job in job_list if job.id not in raw_by_id]
    if missing:
        raise ValueError(f"模型遗漏 JD 评估: {', '.join(missing)}")

    resume_corpus = json.dumps(candidate.model_dump(), ensure_ascii=False)
    assessments = [_normalize_assessment(job, raw_by_id[job.id], resume_corpus) for job in job_list]
    best = max(assessments, key=_assessment_rank)
    return CandidateJobFitEvaluation(
        candidate_id=candidate.id,
        candidate_name=candidate.name,
        assessments=assessments,
        best_fit_jd_id=best.jd_id,
        best_fit_jd_title=best.jd_title,
        best_fit_reason=best.decision_reason,
    )


def _call_llm(system_prompt: str, payload: dict[str, Any]) -> dict[str, Any]:
    return llm_client.call_llm_json(system_prompt, payload, temperature=0.1, deep=True)


def _normalize_assessment(job: JobDefinition, raw: dict[str, Any], resume_corpus: str) -> JobFitAssessment:
    requirements = [
        _normalize_requirement(item, resume_corpus)
        for item in raw.get("hard_requirements", [])
        if isinstance(item, dict) and str(item.get("requirement", "")).strip()
    ]
    raw_dimensions = {
        str(item.get("key", "")): item
        for item in raw.get("dimensions", [])
        if isinstance(item, dict)
    }
    dimensions = []
    for key, label, weight in DIMENSIONS:
        item = raw_dimensions.get(key, {})
        dimensions.append(
            JobFitDimension(
                key=key,
                label=label,
                score=_clamp_float(item.get("score"), 0, 5),
                weight=weight,
                rationale=str(item.get("rationale", "")).strip(),
                evidence=_text_list(item.get("evidence")),
            )
        )

    fit_score = round(sum(item.score / 5 * item.weight for item in dimensions), 1)
    direct_match = next(item.score for item in dimensions if item.key == "direct_task_match")
    decision = _guard_decision(requirements, fit_score, direct_match)
    reason = _decision_reason(decision, requirements, fit_score, direct_match, raw)
    confidence = _clamp_float(raw.get("confidence"), 0, 1)
    if decision == "hold":
        confidence = min(confidence, 0.75)

    return JobFitAssessment(
        jd_id=job.id,
        jd_title=job.title,
        decision=decision,
        confidence=confidence,
        fit_score=fit_score,
        hard_requirements=requirements,
        dimensions=dimensions,
        strengths=_findings(raw.get("strengths")),
        risks=_findings(raw.get("risks")),
        missing_information=_text_list(raw.get("missing_information")),
        interview_questions=_text_list(raw.get("interview_questions")),
        decision_reason=reason,
    )


def _guard_decision(
    requirements: list[JobRequirementAssessment],
    fit_score: float,
    direct_match: float,
) -> InterviewDecision:
    statuses = {item.status for item in requirements}
    if "unmet" in statuses:
        return "reject"
    if "unknown" in statuses:
        if fit_score >= HOLD_SCORE and direct_match >= HOLD_DIRECT_MATCH:
            return "hold"
        return "reject"
    if fit_score >= INTERVIEW_SCORE and direct_match >= INTERVIEW_DIRECT_MATCH:
        return "interview"
    if fit_score >= HOLD_SCORE and direct_match >= HOLD_DIRECT_MATCH:
        return "hold"
    return "reject"


def _decision_reason(
    decision: InterviewDecision,
    requirements: list[JobRequirementAssessment],
    fit_score: float,
    direct_match: float,
    raw: dict[str, Any],
) -> str:
    unmet = [item.requirement for item in requirements if item.status == "unmet"]
    unknown = [item.requirement for item in requirements if item.status == "unknown"]
    if unmet:
        return f"不进入面试：明确不满足硬门槛——{'；'.join(unmet)}。"
    if unknown:
        return f"待补信息：以下硬门槛尚无法从简历确认——{'；'.join(unknown)}。"
    summary = str(raw.get("assessment_summary", "")).strip()
    prefix = {
        "interview": "进入面试",
        "hold": "待补信息",
        "reject": "不进入面试",
    }[decision]
    score_note = f"岗位匹配 {fit_score:.1f}/100，直接任务匹配 {direct_match:.1f}/5"
    return f"{prefix}：{summary or score_note}。" if summary else f"{prefix}：{score_note}。"


def _assessment_rank(item: JobFitAssessment) -> tuple[int, float, float]:
    decision_rank = {"reject": 0, "hold": 1, "interview": 2}
    direct_match = next(
        (dimension.score for dimension in item.dimensions if dimension.key == "direct_task_match"),
        0,
    )
    return decision_rank[item.decision], direct_match, item.fit_score


def _normalize_requirement(item: dict[str, Any], resume_corpus: str) -> JobRequirementAssessment:
    evidence = [quote for quote in _text_list(item.get("evidence")) if quote in resume_corpus]
    status = str(item.get("status", "unknown"))
    if status not in {"met", "unmet", "unknown"}:
        status = "unknown"
    if status in {"met", "unmet"} and not evidence:
        status = "unknown"
    return JobRequirementAssessment(
        requirement=str(item.get("requirement", "")).strip(),
        status=status,
        evidence=evidence,
        rationale=str(item.get("rationale", "")).strip(),
    )


def _findings(value: Any) -> list[JobFitFinding]:
    return [
        JobFitFinding(
            summary=str(item.get("summary", "")).strip(),
            evidence=_text_list(item.get("evidence")),
        )
        for item in (value if isinstance(value, list) else [])
        if isinstance(item, dict) and str(item.get("summary", "")).strip()
    ]


def _text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _clamp_float(value: Any, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = minimum
    return max(minimum, min(maximum, number))
