from __future__ import annotations

from typing import Any

from agi_talent_radar.agents.job_fit.evaluator import _build_evaluation, _request_assessments
from agi_talent_radar.core.models import (
    CandidateEvaluation,
    CandidateJobFitEvaluation,
    CandidateResume,
    DirectionRecommendation,
    JobDefinition,
)


def run_candidate_preparer(state: dict[str, Any]) -> dict[str, Any]:
    resume = CandidateResume.model_validate(state["resume"])
    jobs = [JobDefinition.model_validate(item) for item in state.get("jobs", [])]
    if not jobs:
        raise ValueError("没有激活的 JD，无法进行面试准入评估。")
    if len({job.id for job in jobs}) != len(jobs):
        raise ValueError("JD id 必须唯一。")
    return {
        "prepared_resume": resume.model_dump(),
        "prepared_jobs": [job.model_dump() for job in jobs],
    }


def run_jd_fit_assessor(state: dict[str, Any]) -> dict[str, Any]:
    resume = CandidateResume.model_validate(state["prepared_resume"])
    jobs = [JobDefinition.model_validate(item) for item in state["prepared_jobs"]]
    return {
        "job_fit_raw": _request_assessments(
            resume,
            jobs,
            academic_report=state.get("academic_report"),
        )
    }


def run_decision_guard(state: dict[str, Any]) -> dict[str, Any]:
    resume = CandidateResume.model_validate(state["prepared_resume"])
    jobs = [JobDefinition.model_validate(item) for item in state["prepared_jobs"]]
    result = _build_evaluation(resume, jobs, state["job_fit_raw"])
    return {"job_fit_result": result.model_dump()}


def run_job_fit_formatter(state: dict[str, Any]) -> dict[str, Any]:
    resume = CandidateResume.model_validate(state["prepared_resume"])
    result = CandidateJobFitEvaluation.model_validate(state["job_fit_result"])
    best = next(item for item in result.assessments if item.jd_id == result.best_fit_jd_id)
    recommendations = [
        DirectionRecommendation(
            track=item.jd_id,
            label=item.jd_title,
            score=round(item.fit_score * 0.6, 1),
            weight=round(item.fit_score / 100, 3),
            confidence=item.confidence,
            rationale=item.decision_reason,
        )
        for item in sorted(result.assessments, key=_recommendation_rank, reverse=True)
    ]
    output = CandidateEvaluation(
        id=resume.id,
        name=resume.name,
        target_role=resume.target_role,
        stage=resume.stage,
        overall_score=round(best.fit_score),
        one_liner=best.decision_reason,
        core_strengths=[item.summary for item in best.strengths],
        potential_risks=[item.summary for item in best.risks] + best.missing_information,
        interview_questions=best.interview_questions,
        cultivation_direction=[],
        dimension_scores=[],
        evidence=[],
        normalized_education=[],
        screening_tags=resume.screening_tags,
        recommended_tracks=recommendations,
        routing_confidence=best.confidence,
        evaluation_mode="jd_fit_v2",
        interview_decision=best.decision,
        best_fit_jd_id=best.jd_id,
        best_fit_jd_title=best.jd_title,
        decision_summary=best.decision_reason,
        job_fit_assessments=result.assessments,
    )
    return {"final_output": output.model_dump()}


def _recommendation_rank(item) -> tuple[int, float, float]:
    decision_rank = {"reject": 0, "hold": 1, "interview": 2}
    return decision_rank[item.decision], item.fit_score, item.confidence
