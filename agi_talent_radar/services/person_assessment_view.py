"""人物简历与评估的统一只读视图。

调用者只需要 ``get_person_assessment_view(session, person_id)``。人物、候选人、
简历版本、旧通用评估和新岗位准入的选择规则都封装在本模块内，页面和 Agent
不得再自行推断“是否有简历/评估”或“最新结果”。
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import desc

from agi_talent_radar.core.db.orm import (
    CandidateJdAssessmentORM,
    CandidateORM,
    EvaluationORM,
    JdEntryORM,
    PersonORM,
    ResumeSubmissionORM,
)


SCHEMA_VERSION = "person-assessment-view.v1"


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


def _json_value(value, fallback):
    if isinstance(value, type(fallback)):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, type(fallback)) else fallback
        except json.JSONDecodeError:
            return fallback
    return fallback


def get_person_assessment_view(session, person_id: str) -> dict[str, Any] | None:
    """返回人物唯一的简历/评估读视图；人物不存在时返回 ``None``。

    Interface invariants:

    - ``resume.has_resume`` 只由已落库简历提交或候选人原始简历判断。
    - ``admissions`` 只包含 completed 且 is_valid 的当前岗位准入。
    - ``latest`` 优先指向最新有效岗位准入；无准入时才回退通用评估。
    - 返回值包含稳定 schema version，供页面、Agent 与测试共同消费。
    """
    person = session.get(PersonORM, person_id)
    if person is None:
        return None

    candidate = (
        session.query(CandidateORM)
        .filter(CandidateORM.person_id == person_id)
        .order_by(desc(CandidateORM.updated_at), desc(CandidateORM.created_at), desc(CandidateORM.id))
        .first()
    )
    submission = (
        session.query(ResumeSubmissionORM)
        .filter(ResumeSubmissionORM.person_id == person_id)
        .order_by(desc(ResumeSubmissionORM.created_at), desc(ResumeSubmissionORM.id))
        .first()
    )
    general = (
        session.query(EvaluationORM)
        .filter(EvaluationORM.person_id == person_id, EvaluationORM.status == "completed")
        .order_by(desc(EvaluationORM.created_at), desc(EvaluationORM.id))
        .first()
    )

    admission_rows = (
        session.query(CandidateJdAssessmentORM, JdEntryORM)
        .join(CandidateORM, CandidateJdAssessmentORM.candidate_id == CandidateORM.id)
        .outerjoin(JdEntryORM, CandidateJdAssessmentORM.jd_id == JdEntryORM.id)
        .filter(
            CandidateORM.person_id == person_id,
            CandidateJdAssessmentORM.status == "completed",
            CandidateJdAssessmentORM.is_valid.is_(True),
        )
        .order_by(
            desc(CandidateJdAssessmentORM.updated_at),
            desc(CandidateJdAssessmentORM.created_at),
            desc(CandidateJdAssessmentORM.id),
        )
        .all()
    )
    admissions = [
        {
            "id": assessment.id,
            "candidate_id": assessment.candidate_id,
            "jd_id": assessment.jd_id,
            "jd_title": jd.title if jd is not None else "",
            "status": assessment.status,
            "is_valid": bool(assessment.is_valid),
            "invalid_reason": assessment.invalid_reason or "",
            "decision": assessment.decision,
            "total_score": round(float(assessment.total_score or 0), 1),
            "task_assessments": assessment.task_assessments or [],
            "review_corrections": assessment.review_corrections or [],
            "interview_focus": assessment.interview_focus or [],
            "model_usage": assessment.model_usage or [],
            "run_trace": assessment.run_trace or [],
            "created_at": _iso(assessment.created_at),
            "updated_at": _iso(assessment.updated_at),
        }
        for assessment, jd in admission_rows
    ]

    structured = submission.structured if submission is not None and isinstance(submission.structured, dict) else {}
    if not structured and candidate is not None:
        structured = {
            "education": _json_value(candidate.education, []),
            "directions": _json_value(candidate.directions, []),
            "experiences": _json_value(candidate.experiences, []),
            "projects": _json_value(candidate.projects, []),
            "publications": _json_value(candidate.publications, []),
            "skills": _json_value(candidate.skills, []),
            "target_role": candidate.target_role or "",
        }
    candidate_has_resume = bool(candidate and (candidate.raw_text or candidate.current_resume_version_id))
    resume = {
        "has_resume": submission is not None or candidate_has_resume,
        "submission_id": submission.id if submission is not None else None,
        "candidate_id": candidate.id if candidate is not None else None,
        "filename": submission.filename if submission is not None else "",
        "source_format": (
            submission.source_format
            if submission is not None
            else (candidate.source_format if candidate is not None else "")
        ),
        "parse_status": submission.parse_status if submission is not None else None,
        "structured": structured,
        "structured_sections": sorted(structured.keys()),
        "updated_at": _iso(submission.updated_at if submission is not None else None),
    }

    general_view = None
    if general is not None:
        general_view = {
            "id": general.id,
            "candidate_id": general.candidate_id,
            "status": general.status,
            "overall_score": general.overall_score,
            "level": general.level or "",
            "tier": general.tier or "",
            "one_liner": general.one_liner or "",
            "stage_profile": general.stage_profile or "",
            "core_strengths": general.core_strengths or [],
            "potential_risks": general.potential_risks or [],
            "recommended_tracks": general.recommended_tracks or [],
            "academic_report": general.academic_report or {},
            "created_at": _iso(general.created_at),
            "completed_at": _iso(general.completed_at),
        }

    latest = None
    if admissions:
        latest_admission = admissions[0]
        latest = {
            "source_type": "interview_admission",
            "source_id": latest_admission["id"],
            "candidate_id": latest_admission["candidate_id"],
            "jd_id": latest_admission["jd_id"],
            "jd_title": latest_admission["jd_title"],
            "decision": latest_admission["decision"],
            "score": latest_admission["total_score"],
            "generated_at": latest_admission["updated_at"] or latest_admission["created_at"],
        }
    elif general_view is not None:
        latest = {
            "source_type": "general_evaluation",
            "source_id": str(general_view["id"]),
            "candidate_id": general_view["candidate_id"],
            "decision": None,
            "score": general_view["overall_score"],
            "generated_at": general_view["completed_at"] or general_view["created_at"],
        }

    return {
        "schema_version": SCHEMA_VERSION,
        "person_id": person.id,
        "candidate_id": candidate.id if candidate is not None else None,
        "resume": resume,
        "general_evaluation": general_view,
        "admissions": admissions,
        "latest": latest,
    }


__all__ = ["SCHEMA_VERSION", "get_person_assessment_view"]
