from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, exists, or_
from sqlalchemy.exc import IntegrityError

from agi_talent_radar.core.db.orm import (
    CandidateJdAssessmentORM,
    CandidateORM,
    CandidateSourceORM,
    DimensionScoreORM,
    EngagementStatusHistoryORM,
    EvaluationEvidenceORM,
    EvaluationNodeRunORM,
    EvaluationORM,
    IdentitySuggestionORM,
    InterviewAssessmentBatchORM,
    InterviewAssessmentPairLockORM,
    InterviewAssessmentRunORM,
    JdEntryORM,
    MergeAuditORM,
    PersonORM,
    PublicationClaimORM,
    PublicationVerificationORM,
    ResumeSubmissionORM,
    ResumeVersionORM,
    TaskORM,
    TrackAssignmentORM,
    TrackEvaluationORM,
)
from agi_talent_radar.core.models import CandidateEvaluation, CandidateResume, ImportClassification
from agi_talent_radar.core.domain_models import EngagementStatus
from agi_talent_radar.core.persons import get_or_create_person
from agi_talent_radar.core.scoring_version import current_scoring_version


def save_candidate(
    session,
    resume: CandidateResume,
    classification: ImportClassification | None = None,
    academic_report: dict | None = None,
) -> CandidateORM:
    candidate = session.get(CandidateORM, resume.id)
    previous_payload = None
    if candidate is not None:
        previous_payload = (
            candidate.raw_text or "",
            candidate.education or "",
            candidate.experiences or "",
            candidate.projects or "",
            candidate.publications or "",
            candidate.skills or "",
        )
        active_run = session.query(InterviewAssessmentRunORM.id).filter(
            InterviewAssessmentRunORM.candidate_id == resume.id,
            InterviewAssessmentRunORM.status.in_(("queued", "running")),
        ).first()
        if active_run is not None:
            raise RuntimeError("该候选人正在进行面试准入评估，请先停止相关配对。")
    if candidate is None:
        candidate = CandidateORM(id=resume.id)
        session.add(candidate)

    candidate.name = resume.name or candidate.name
    candidate.target_role = resume.target_role or candidate.target_role
    candidate.stage = resume.stage or candidate.stage
    candidate.raw_text = resume.raw_text or candidate.raw_text
    # 结构化字段同名字段一样用「非空才覆盖」：空解析结果不得清掉已有数据
    if resume.education:
        candidate.education = _json_text(resume.education)
    if resume.directions:
        candidate.directions = _json_text(resume.directions)
    if resume.experiences:
        candidate.experiences = _json_text([experience.model_dump() for experience in resume.experiences])
    if resume.projects:
        candidate.projects = _json_text([project.model_dump() for project in resume.projects])
    if resume.publications:
        candidate.publications = _json_text(resume.publications)
    if resume.skills:
        candidate.skills = _json_text(resume.skills)
    if resume.screening_tags:
        candidate.screening_tags = _json_text(resume.screening_tags)
    candidate.source_format = resume.source_format
    candidate.document_analysis = _json_text(resume.document_analysis)
    if academic_report is not None:
        candidate.academic_report = academic_report

    if classification:
        candidate.import_category = classification.category
        candidate.import_level = ""
        candidate.import_confidence = classification.confidence

    current_payload = (
        candidate.raw_text or "",
        candidate.education or "",
        candidate.experiences or "",
        candidate.projects or "",
        candidate.publications or "",
        candidate.skills or "",
    )
    if previous_payload is not None and previous_payload != current_payload:
        session.query(CandidateJdAssessmentORM).filter_by(candidate_id=candidate.id, is_valid=True).update(
            {
                CandidateJdAssessmentORM.is_valid: False,
                CandidateJdAssessmentORM.invalid_reason: "候选人简历已更新",
            },
            synchronize_session=False,
        )
    session.commit()
    return candidate


def start_evaluation_run(session, candidate_id: str) -> EvaluationORM:
    if session.get(CandidateORM, candidate_id) is None:
        raise ValueError(f"候选人不存在: {candidate_id}")
    evaluation = EvaluationORM(candidate_id=candidate_id, status="running", evaluation_mode="jd_fit_v2")
    session.add(evaluation)
    session.commit()
    session.refresh(evaluation)
    return evaluation


def record_node_event(session, evaluation_id: int, event: dict[str, Any]) -> EvaluationNodeRunORM:
    node_key = str(event.get("node", "")).strip()
    if not node_key:
        raise ValueError("节点事件缺少 node。")
    node_run = (
        session.query(EvaluationNodeRunORM)
        .filter_by(evaluation_id=evaluation_id, node_key=node_key)
        .first()
    )
    if node_run is None:
        sequence = (
            session.query(func.count(EvaluationNodeRunORM.id))
            .filter_by(evaluation_id=evaluation_id)
            .scalar()
            or 0
        )
        node_run = EvaluationNodeRunORM(
            evaluation_id=evaluation_id,
            node_key=node_key,
            sequence=int(sequence),
        )
        session.add(node_run)
    node_run.phase = str(event.get("phase", "")) or "unknown"
    node_run.status = str(event.get("status", "done"))
    node_run.message = str(event.get("message", ""))
    if node_run.status in {"done", "skipped", "error"}:
        node_run.completed_at = _now()
    session.commit()
    return node_run


def fail_evaluation_run(session, evaluation_id: int, error: Exception | str) -> None:
    evaluation = session.get(EvaluationORM, evaluation_id)
    if evaluation is None:
        return
    evaluation.status = "failed"
    evaluation.error_message = str(error)
    evaluation.completed_at = _now()
    session.commit()


def save_evaluation(
    session,
    evaluation: CandidateEvaluation,
    evaluation_id: int | None = None,
) -> EvaluationORM:
    if evaluation_id is None:
        ev = EvaluationORM(candidate_id=evaluation.id)
        session.add(ev)
    else:
        ev = session.get(EvaluationORM, evaluation_id)
        if ev is None:
            raise ValueError(f"评估运行不存在: {evaluation_id}")
        if ev.candidate_id != evaluation.id:
            raise ValueError("评估运行与候选人不匹配。")

    ev.overall_score = evaluation.overall_score
    ev.level = ""
    ev.tier = ""
    ev.decision_method = ""
    ev.one_liner = evaluation.one_liner
    ev.core_strengths = evaluation.core_strengths
    ev.potential_risks = evaluation.potential_risks
    ev.interview_questions = evaluation.interview_questions
    ev.cultivation_direction = evaluation.cultivation_direction
    ev.recommended_tracks = [item.model_dump() for item in evaluation.recommended_tracks]
    ev.stage_profile = evaluation.stage_profile
    ev.academic_report = evaluation.academic_report or {}
    ev.critic_flags = evaluation.critic_flags
    ev.normalized_education = evaluation.normalized_education
    ev.screening_tags = evaluation.screening_tags
    ev.common_score = evaluation.common_score
    ev.document_score = evaluation.document_score
    ev.routing_confidence = evaluation.routing_confidence
    ev.evaluation_mode = evaluation.evaluation_mode
    ev.publication_score = evaluation.publication_score
    ev.safety_net_score = evaluation.safety_net_score
    ev.interview_decision = evaluation.interview_decision
    ev.best_fit_jd_id = evaluation.best_fit_jd_id
    ev.best_fit_jd_title = evaluation.best_fit_jd_title
    ev.decision_summary = evaluation.decision_summary
    ev.job_fit_assessments = [item.model_dump() for item in evaluation.job_fit_assessments]
    ev.config_version = current_scoring_version(session)
    ev.person_id = _link_person(session, evaluation).id
    ev.status = "completed"
    ev.error_message = ""
    ev.completed_at = _now()
    session.flush()

    _replace_evaluation_details(session, ev, evaluation.model_dump())
    session.commit()
    session.refresh(ev)
    return ev


def _replace_evaluation_details(session, evaluation: EvaluationORM, payload: dict[str, Any]) -> None:
    evaluation.track_assignments.clear()
    evaluation.dimension_scores.clear()
    evaluation.track_evaluations.clear()
    evaluation.evidence_items.clear()
    session.flush()

    evidence_by_key: dict[str, EvaluationEvidenceORM] = {}
    for index, item in enumerate(_as_list(payload.get("evidence"))):
        evidence_key = str(item.get("id", f"e{index + 1}"))
        row = EvaluationEvidenceORM(
            evidence_key=evidence_key,
            dimension=str(item.get("dimension", "")),
            source=str(item.get("source", "")),
            quote=str(item.get("quote", "")),
            signals=_as_list(item.get("signals")),
            strength=int(item.get("strength", 1) or 1),
            has_metric=bool(item.get("has_metric", False)),
            has_specific_tool=bool(item.get("has_specific_tool", False)),
            has_ownership=bool(item.get("has_ownership", False)),
            track_hints=_as_list(item.get("track_hints")),
            page=item.get("page"),
            bbox=_as_list(item.get("bbox")),
            extraction_confidence=float(item.get("extraction_confidence", 1.0) or 0),
            order_index=index,
        )
        evaluation.evidence_items.append(row)
        evidence_by_key[evidence_key] = row
    session.flush()

    for index, item in enumerate(_as_list(payload.get("dimension_scores"))):
        evaluation.dimension_scores.append(
            _dimension_row(evaluation, item, "common", "", index, evidence_by_key)
        )

    for index, item in enumerate(_as_list(payload.get("track_assignments"))):
        row = TrackAssignmentORM(
            track=str(item.get("track", "")),
            weight=float(item.get("weight", 0) or 0),
            confidence=float(item.get("confidence", 0) or 0),
            rationale=str(item.get("rationale", "")),
            order_index=index,
        )
        row.evidence_items = _linked_evidence(item.get("evidence_ids"), evidence_by_key)
        evaluation.track_assignments.append(row)

    for index, item in enumerate(_as_list(payload.get("track_evaluations"))):
        track_key = str(item.get("track", ""))
        track_row = TrackEvaluationORM(
            track=track_key,
            label=str(item.get("label", "")),
            weight=float(item.get("weight", 0) or 0),
            confidence=float(item.get("confidence", 0) or 0),
            raw_score=float(item.get("raw_score", 0) or 0),
            calibrated_score=float(item.get("calibrated_score", 0) or 0),
            risk_notes=_as_list(item.get("risk_notes")),
            critic_flags=_as_list(item.get("critic_flags")),
            order_index=index,
        )
        track_row.evidence_items = _linked_evidence(item.get("evidence_ids"), evidence_by_key)
        evaluation.track_evaluations.append(track_row)
        for dimension_index, dimension in enumerate(_as_list(item.get("dimension_scores"))):
            score_row = _dimension_row(
                evaluation,
                dimension,
                "track",
                track_key,
                dimension_index,
                evidence_by_key,
            )
            score_row.track_evaluation = track_row
            evaluation.dimension_scores.append(score_row)


def _dimension_row(
    evaluation: EvaluationORM,
    item: dict[str, Any],
    scope: str,
    track_key: str,
    order_index: int,
    evidence_by_key: dict[str, EvaluationEvidenceORM],
) -> DimensionScoreORM:
    row = DimensionScoreORM(
        scope=scope,
        track_key=track_key,
        dimension_key=str(item.get("key", "")),
        label=str(item.get("label", "")),
        score=float(item.get("score", 0) or 0),
        weighted_score=float(item.get("weighted_score", 0) or 0),
        max_points=float(item.get("max_points", 0) or 0),
        rationale=str(item.get("rationale", "")),
        risk_notes=_as_list(item.get("risk_notes")),
        order_index=order_index,
    )
    row.evidence_items = _linked_evidence(item.get("evidence_ids"), evidence_by_key)
    return row


def evaluation_to_dict(evaluation: EvaluationORM) -> dict[str, Any]:
    from agi_talent_radar.core.graph import evaluation_graph_catalog

    evidence = [_evidence_dict(item) for item in evaluation.evidence_items]
    common_dimensions = [
        _dimension_dict(item)
        for item in evaluation.dimension_scores
        if item.scope == "common"
    ]
    assignments = [
        {
            "track": item.track,
            "weight": item.weight,
            "confidence": item.confidence,
            "rationale": item.rationale or "",
            "evidence_ids": _evidence_keys(item.evidence_items),
        }
        for item in evaluation.track_assignments
    ]
    track_evaluations = [
        {
            "track": item.track,
            "label": item.label or "",
            "weight": item.weight,
            "confidence": item.confidence,
            "raw_score": item.raw_score,
            "calibrated_score": item.calibrated_score,
            "dimension_scores": [_dimension_dict(score) for score in item.dimension_scores],
            "evidence_ids": _evidence_keys(item.evidence_items),
            "risk_notes": item.risk_notes or [],
            "critic_flags": item.critic_flags or [],
        }
        for item in evaluation.track_evaluations
    ]
    assignment_by_track = {item["track"]: item for item in assignments}
    evaluation_by_track = {item["track"]: item for item in track_evaluations}
    recommended_tracks = []
    for raw_item in evaluation.recommended_tracks or []:
        item = dict(raw_item)
        track = str(item.get("track", ""))
        weight = item.get("weight")
        if not isinstance(weight, (int, float)) or weight <= 0:
            fallback = assignment_by_track.get(track) or evaluation_by_track.get(track) or {}
            item["weight"] = float(fallback.get("weight", 0) or 0)
        recommended_tracks.append(item)
    return {
        "id": evaluation.id,
        "overall_score": evaluation.overall_score,
        "one_liner": evaluation.one_liner or "",
        "core_strengths": evaluation.core_strengths or [],
        "potential_risks": evaluation.potential_risks or [],
        "interview_questions": evaluation.interview_questions or [],
        "cultivation_direction": evaluation.cultivation_direction or [],
        "recommended_tracks": recommended_tracks,
        "stage_profile": evaluation.stage_profile or "",
        "academic_report": evaluation.academic_report or {},
        "dimension_scores": common_dimensions,
        "evidence": evidence,
        "critic_flags": evaluation.critic_flags or [],
        "normalized_education": evaluation.normalized_education or [],
        "screening_tags": evaluation.screening_tags or [],
        "common_score": evaluation.common_score or 0,
        "document_score": evaluation.document_score or 0,
        "publication_score": evaluation.publication_score or 0,
        "safety_net_score": evaluation.safety_net_score or 0,
        "track_assignments": assignments,
        "track_evaluations": track_evaluations,
        "routing_confidence": evaluation.routing_confidence or 0,
        "evaluation_mode": evaluation.evaluation_mode or "multi_track_v1",
        "interview_decision": evaluation.interview_decision or "",
        "best_fit_jd_id": evaluation.best_fit_jd_id or "",
        "best_fit_jd_title": evaluation.best_fit_jd_title or "",
        "decision_summary": evaluation.decision_summary or "",
        "job_fit_assessments": evaluation.job_fit_assessments or [],
        "status": evaluation.status,
        "error_message": evaluation.error_message or "",
        "created_at": _iso_datetime(evaluation.created_at),
        "completed_at": _iso_datetime(evaluation.completed_at),
        "evaluation_graph": evaluation_graph_catalog(),
        "node_runs": [
            {
                "node": item.node_key,
                "phase": item.phase,
                "status": item.status,
                "message": item.message or "",
                "sequence": item.sequence,
            }
            for item in evaluation.node_runs
        ],
    }


def evaluation_run_to_dict(evaluation: EvaluationORM) -> dict[str, Any]:
    """Serialize the durable portion of any evaluation run, including active runs."""
    from agi_talent_radar.core.graph import evaluation_graph_catalog

    return {
        "id": evaluation.id,
        "candidate_id": evaluation.candidate_id,
        "status": evaluation.status,
        "error_message": evaluation.error_message or "",
        "created_at": _iso_datetime(evaluation.created_at),
        "completed_at": _iso_datetime(evaluation.completed_at),
        "evaluation_graph": evaluation_graph_catalog(),
        "node_runs": [
            {
                "node": item.node_key,
                "phase": item.phase,
                "status": item.status,
                "message": item.message or "",
                "sequence": item.sequence,
            }
            for item in evaluation.node_runs
        ],
    }


def list_candidates(session):
    return session.query(CandidateORM).order_by(CandidateORM.created_at.desc()).all()


# 已评估候选人展示 N 天后自动从队列移除（数据保留，仅不入列表）
EVALUATED_QUEUE_RETENTION_DAYS = 3


def list_candidates_for_queue(session):
    """简历评估队列专用列表：

    - 已评估（存在 evaluations 记录）且评估完成超过
      ``EVALUATED_QUEUE_RETENTION_DAYS`` 天的候选人不再返回；
      其人物档案已进入人才库（persons），评估留痕仍在 evaluations，
      故此处只做查询时过滤，不物理删除。
    - 未评估的候选人全部返回（需人工处理）。
    每行额外挂一个 ``evaluated`` 布尔，供前端区分删除/移出语义。
    """
    retention_cutoff = datetime.now(timezone.utc) - timedelta(days=EVALUATED_QUEUE_RETENTION_DAYS)
    # 子查询：每个候选人最近一次评估完成时间（completed_at）
    latest_eval_subq = (
        session.query(
            EvaluationORM.candidate_id.label("cid"),
            func.max(EvaluationORM.completed_at).label("latest"),
        )
        .group_by(EvaluationORM.candidate_id)
        .subquery()
    )
    has_eval_subq = (
        session.query(EvaluationORM.candidate_id)
        .filter(EvaluationORM.candidate_id == CandidateORM.id)
        .exists()
    )
    rows = (
        session.query(CandidateORM, latest_eval_subq.c.latest, has_eval_subq.label("evaluated"))
        .outerjoin(latest_eval_subq, latest_eval_subq.c.cid == CandidateORM.id)
        .filter(CandidateORM.group != "dismissed")
        .order_by(CandidateORM.created_at.desc())
        .all()
    )
    result = []
    for candidate, latest_completed, evaluated in rows:
        latest_run = get_latest_evaluation_run(session, candidate.id)
        run_active = bool(latest_run and latest_run.status == "running")
        # 已评估但完成时间超过保留期 → 跳过（UTC vs naive 兼容比较）；
        # 但人才库批量重新评估正在进行时（run 活跃）必须保留在队列里
        if evaluated and latest_completed is not None and not run_active:
            comp = latest_completed
            if comp.tzinfo is None:
                comp = comp.replace(tzinfo=timezone.utc)
            if comp < retention_cutoff:
                continue
        # 用 setattr 挂载临时字段，避免改动 ORM 模型
        candidate.evaluated = bool(evaluated)  # type: ignore[attr-defined]
        candidate.evaluation_status = latest_run.status if latest_run else "idle"  # type: ignore[attr-defined]
        candidate.evaluation_run_id = latest_run.id if latest_run else None  # type: ignore[attr-defined]
        result.append(candidate)
    return result


def list_candidates_by_group(session, group: str):
    return (
        session.query(CandidateORM)
        .filter_by(group=group)
        .order_by(CandidateORM.created_at.desc())
        .all()
    )


def move_candidate_group(session, candidate_id: str, group: str) -> CandidateORM | None:
    candidate = session.get(CandidateORM, candidate_id)
    if candidate is None:
        return None
    candidate.group = group
    session.commit()
    return candidate


def delete_candidate(session, candidate_id: str) -> CandidateORM | None:
    candidate = session.get(CandidateORM, candidate_id)
    if candidate is None:
        return None
    session.delete(candidate)
    session.commit()
    return candidate


def delete_person(session, person_id: str) -> PersonORM | None:
    """彻底删除人物主档及其简历、候选档案、评估与核验记录。"""
    person = session.get(PersonORM, person_id)
    if person is None:
        return None

    candidates = session.query(CandidateORM).filter_by(person_id=person_id).all()
    candidate_ids = [candidate.id for candidate in candidates]
    evaluations = session.query(EvaluationORM).filter(
        or_(
            EvaluationORM.person_id == person_id,
            EvaluationORM.candidate_id.in_(candidate_ids) if candidate_ids else False,
        )
    ).all()
    evaluation_ids = [evaluation.id for evaluation in evaluations]
    submissions = session.query(ResumeSubmissionORM).filter(
        or_(
            ResumeSubmissionORM.person_id == person_id,
            ResumeSubmissionORM.candidate_id.in_(candidate_ids) if candidate_ids else False,
        )
    ).all()
    submission_ids = [submission.id for submission in submissions]

    if evaluation_ids:
        claim_ids = [
            row.id
            for row in session.query(PublicationClaimORM.id)
            .filter(PublicationClaimORM.evaluation_id.in_(evaluation_ids))
            .all()
        ]
        if claim_ids:
            session.query(PublicationVerificationORM).filter(
                PublicationVerificationORM.claim_id.in_(claim_ids)
            ).delete(synchronize_session=False)
        session.query(PublicationClaimORM).filter(
            PublicationClaimORM.evaluation_id.in_(evaluation_ids)
        ).delete(synchronize_session=False)
    suggestion_filter = IdentitySuggestionORM.matched_person_id == person_id
    if submission_ids:
        suggestion_filter = or_(
            suggestion_filter,
            IdentitySuggestionORM.submission_id.in_(submission_ids),
        )
    session.query(IdentitySuggestionORM).filter(suggestion_filter).delete(synchronize_session=False)
    if submission_ids:
        session.query(ResumeVersionORM).filter(
            ResumeVersionORM.submission_id.in_(submission_ids)
        ).delete(synchronize_session=False)

    for evaluation in evaluations:
        session.delete(evaluation)
    for submission in submissions:
        session.delete(submission)
    for candidate in candidates:
        session.delete(candidate)
    session.query(MergeAuditORM).filter(
        or_(
            MergeAuditORM.primary_person_id == person_id,
            MergeAuditORM.merged_person_id == person_id,
        )
    ).delete(synchronize_session=False)
    for task in session.query(TaskORM).all():
        payload = task.payload if isinstance(task.payload, dict) else {}
        if (
            payload.get("person_id") == person_id
            or payload.get("candidate_id") in candidate_ids
            or payload.get("evaluation_id") in evaluation_ids
        ):
            session.delete(task)
    session.delete(person)
    session.commit()

    from agi_talent_radar.core.pdf_storage import get_resume_pdf_path

    for candidate_id in candidate_ids:
        path = get_resume_pdf_path(candidate_id)
        if path is not None:
            path.unlink(missing_ok=True)
    return person


def get_candidate_with_latest_evaluation(session, candidate_id: str):
    candidate = session.get(CandidateORM, candidate_id)
    if candidate is None:
        return None, None
    latest_evaluation = (
        session.query(EvaluationORM)
        .filter_by(candidate_id=candidate_id, status="completed")
        .order_by(EvaluationORM.created_at.desc(), EvaluationORM.id.desc())
        .first()
    )
    return candidate, latest_evaluation


def get_latest_evaluation_run(session, candidate_id: str) -> EvaluationORM | None:
    return (
        session.query(EvaluationORM)
        .filter_by(candidate_id=candidate_id)
        .order_by(EvaluationORM.created_at.desc(), EvaluationORM.id.desc())
        .first()
    )


def _iso_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _dimension_dict(item: DimensionScoreORM) -> dict[str, Any]:
    return {
        "key": item.dimension_key,
        "label": item.label or "",
        "score": item.score,
        "weighted_score": item.weighted_score,
        "max_points": item.max_points,
        "rationale": item.rationale or "",
        "evidence_ids": _evidence_keys(item.evidence_items),
        "risk_notes": item.risk_notes or [],
    }


def _evidence_dict(item: EvaluationEvidenceORM) -> dict[str, Any]:
    return {
        "id": item.evidence_key,
        "dimension": item.dimension,
        "source": item.source or "",
        "quote": item.quote or "",
        "signals": item.signals or [],
        "strength": item.strength,
        "has_metric": bool(item.has_metric),
        "has_specific_tool": bool(item.has_specific_tool),
        "has_ownership": bool(item.has_ownership),
        "track_hints": item.track_hints or [],
        "page": item.page,
        "bbox": item.bbox or [],
        "extraction_confidence": item.extraction_confidence,
    }


def _linked_evidence(
    evidence_ids: Any,
    evidence_by_key: dict[str, EvaluationEvidenceORM],
) -> list[EvaluationEvidenceORM]:
    return [
        evidence_by_key[str(evidence_id)]
        for evidence_id in _as_list(evidence_ids)
        if str(evidence_id) in evidence_by_key
    ]


def _evidence_keys(items: list[EvaluationEvidenceORM]) -> list[str]:
    return [item.evidence_key for item in sorted(items, key=lambda item: item.order_index)]


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _as_list(value: Any) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _link_person(session, evaluation: CandidateEvaluation):
    """把评估挂到人员主档：优先取候选人记录里的姓名和方向。

    候选人带教育经历时，同步结构化学校列表到主档（persons.schools），
    并把 org 刷新为最高学历学校（联培不作学位授予校）。
    """
    candidate = session.get(CandidateORM, evaluation.id)
    if candidate and candidate.person_id:
        person = session.get(PersonORM, candidate.person_id)
        if person is not None:
            _refresh_person_schools(person, candidate)
            return person
    name = (candidate.name if candidate else "") or evaluation.name
    direction = ""
    if candidate and candidate.directions:
        items = _as_list(candidate.directions)
        if items:
            direction = str(items[0])[:256]
    person = get_or_create_person(session, name=name, direction=direction)
    if candidate is not None:
        _refresh_person_schools(person, candidate)
    return person


def _refresh_person_schools(person, candidate) -> None:
    """用候选人 education 自由文本重建主档学校列表 + 最高学历 org。"""
    from agi_talent_radar.core.education import highest_school, parse_education_entries

    entries = parse_education_entries(_as_list(candidate.education))
    if not entries:
        return
    person.schools = [entry.to_dict() for entry in entries]
    top = highest_school(entries)
    if top:
        person.org = top


def create_task(session, task_type: str, payload: dict[str, Any] | None = None, task_id: str | None = None) -> TaskORM:
    task = TaskORM(id=task_id or uuid.uuid4().hex, task_type=task_type, payload=payload or {})
    session.add(task)
    session.commit()
    session.refresh(task)
    return task


def update_task(
    session,
    task_id: str,
    status: str | None = None,
    progress: dict[str, Any] | None = None,
    error: str = "",
) -> TaskORM | None:
    task = session.get(TaskORM, task_id)
    if task is None:
        return None
    if status:
        task.status = status
    if progress is not None:
        task.progress = progress
    if error:
        task.error_message = error
    session.commit()
    return task


# ---------------------------------------------------------------------------
# 阶段 1：ResumeSubmission / 人才档案入库 / 来源追加 / HR 状态变更
# ---------------------------------------------------------------------------


def save_resume_submission(
    session,
    resume_id: str,
    source_format: str,
    raw_text: str = "",
    structured: dict[str, Any] | None = None,
    filename: str = "",
    parse_status: str = "pending",
    candidate_id: str | None = None,
    person_id: str | None = None,
    parse_error: str = "",
) -> ResumeSubmissionORM:
    """保存一次简历导入动作。阶段 1 之后，导入仅写 submission，不写 candidate。

    兼容期允许同时绑定 ``candidate_id`` 用于老 workbench id 复用；
    阶段 1.7 之后 ``talent_service.admit_candidate_after_evaluation`` 会
    切断这条路径。
    """
    import uuid as _uuid

    from agi_talent_radar.core.db.orm import ResumeSubmissionORM

    submission = session.get(ResumeSubmissionORM, resume_id)
    if submission is None:
        submission = ResumeSubmissionORM(id=resume_id or _uuid.uuid4().hex)
        session.add(submission)
    submission.source_format = source_format
    submission.filename = filename or submission.filename
    submission.raw_text = raw_text or submission.raw_text
    submission.structured = structured if structured is not None else submission.structured or {}
    submission.parse_status = parse_status or submission.parse_status or "pending"
    submission.parse_error = parse_error or submission.parse_error or ""
    if candidate_id is not None:
        submission.candidate_id = candidate_id
    if person_id is not None:
        submission.person_id = person_id
    session.commit()
    session.refresh(submission)
    return submission


def create_resume_version(
    session,
    submission_id: str,
    raw_text: str = "",
    structured: dict[str, Any] | None = None,
    note: str = "",
) -> ResumeVersionORM:
    """创建一份简历版本；同一 submission 下 version 自增。原文永不被覆盖。"""
    import uuid as _uuid

    from agi_talent_radar.core.db.orm import ResumeVersionORM

    last_version = (
        session.query(ResumeVersionORM)
        .filter_by(submission_id=submission_id)
        .order_by(ResumeVersionORM.version.desc())
        .first()
    )
    next_version = (last_version.version if last_version else 0) + 1
    row = ResumeVersionORM(
        id=_uuid.uuid4().hex,
        submission_id=submission_id,
        version=next_version,
        raw_text=raw_text,
        structured=structured or {},
        note=note,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def find_candidate_by_person(session, person_id: str) -> CandidateORM | None:
    """同一 person 至多一个 Candidate；阶段 1 后所有候选人通过 person 归并。"""
    return session.query(CandidateORM).filter_by(person_id=person_id).first()


def list_person_resume_versions(session, person_id: str) -> list[dict[str, Any]]:
    """查某人物的所有简历版本（按导入时间倒序），供前端对比。

    双查口径：person_id 有值时按 person_id 查；
    同时也查该 person 关联的 candidate 的所有 submissions（含 person_id=None 的早期导入）。
    确保同一人的多次导入都能聚合到一起，即使身份归并时序差异。
    """
    from agi_talent_radar.core.db.orm import ResumeSubmissionORM

    query = session.query(ResumeSubmissionORM)
    # 先按 person_id 查
    conds = [ResumeSubmissionORM.person_id == person_id]
    # 再补充：该 person 关联的 candidate 的 submissions
    candidate = find_candidate_by_person(session, person_id)
    if candidate:
        conds.append(ResumeSubmissionORM.candidate_id == candidate.id)
    # union：满足任一条件
    from sqlalchemy import or_
    rows = (
        query.filter(or_(*conds))
        .order_by(ResumeSubmissionORM.created_at.desc())
        .all()
    )
    return [
        {
            "submission_id": r.id,
            "filename": r.filename or "",
            "source_format": r.source_format or "",
            "created_at": r.created_at.isoformat() if r.created_at else "",
            "structured": r.structured or {},
        }
        for r in rows
    ]


def find_or_create_candidate_for_person(
    session,
    person_id: str,
    name: str = "",
    target_role: str = "",
    stage: str = "",
    group: str = "pending",
) -> CandidateORM:
    """按 person 查找或创建 Candidate。返回的 CandidateORM 已 flush。"""
    import uuid as _uuid

    candidate = find_candidate_by_person(session, person_id)
    if candidate is not None:
        return candidate
    candidate = CandidateORM(
        id=_uuid.uuid4().hex[:32],
        name=name,
        target_role=target_role,
        stage=stage,
        group=group,
        person_id=person_id,
        engagement_status="newly_admitted",
        admitted_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    session.add(candidate)
    session.flush()
    return candidate


def append_candidate_source(
    session,
    candidate_id: str,
    source_kind: str,
    source_record_id: str = "",
    note: str = "",
    created_by: str = "",
) -> CandidateSourceORM | None:
    """为人才档案追加一个来源；同 ``source_kind`` 幂等返回已有记录。

    ``source_kind`` 必须属于 ``CANDIDATE_SOURCE_KINDS``，否则抛出 ``ValueError``。
    """
    from agi_talent_radar.core.db.orm import CANDIDATE_SOURCE_KINDS, CandidateSourceORM

    if source_kind not in CANDIDATE_SOURCE_KINDS:
        raise ValueError(f"source_kind 必须是 {CANDIDATE_SOURCE_KINDS} 之一")
    existing = (
        session.query(CandidateSourceORM)
        .filter_by(candidate_id=candidate_id, source_kind=source_kind)
        .first()
    )
    if existing is not None:
        return existing
    row = CandidateSourceORM(
        candidate_id=candidate_id,
        source_kind=source_kind,
        source_record_id=source_record_id,
        note=note,
        created_by=created_by,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def list_candidate_source_kinds(session, candidate_id: str) -> list[str]:
    """获取人才档案所有来源类型，按创建时间升序。"""
    from agi_talent_radar.core.db.orm import CandidateSourceORM

    rows = (
        session.query(CandidateSourceORM)
        .filter_by(candidate_id=candidate_id)
        .order_by(CandidateSourceORM.created_at, CandidateSourceORM.id)
        .all()
    )
    return [row.source_kind for row in rows]


def update_engagement_status(
    session,
    candidate_id: str,
    status: str,
    changed_by: str,
    note: str = "",
) -> EngagementStatusHistoryORM:
    """修改 HR 跟进状态；写入不可变审计记录。

    - ``status`` 必须是招聘生命周期中的有效状态。
    - ``changed_by`` 强制要求；不接受自动入参。
    """
    from agi_talent_radar.core.db.orm import EngagementStatusHistoryORM

    allowed = set(EngagementStatus.accepted())
    if status not in allowed:
        raise ValueError(f"status 必须是 {sorted(allowed)} 之一")
    if not changed_by or not changed_by.strip():
        raise ValueError("changed_by 必填，禁止基于评分自动切换。")
    candidate = session.get(CandidateORM, candidate_id)
    if candidate is None:
        raise ValueError(f"候选人不存在: {candidate_id}")
    previous = candidate.engagement_status or ""
    history = EngagementStatusHistoryORM(
        candidate_id=candidate_id,
        previous_status=previous,
        current_status=status,
        changed_by=changed_by,
        note=note or "",
    )
    session.add(history)
    candidate.engagement_status = status
    session.commit()
    session.refresh(history)
    return history


def list_engagement_history(session, candidate_id: str) -> list[EngagementStatusHistoryORM]:
    from agi_talent_radar.core.db.orm import EngagementStatusHistoryORM

    return (
        session.query(EngagementStatusHistoryORM)
        .filter_by(candidate_id=candidate_id)
        .order_by(EngagementStatusHistoryORM.created_at, EngagementStatusHistoryORM.id)
        .all()
    )


# ---------------------------------------------------------------------------
# 阶段 3：论文自述（claim）与外部核验（verification）持久化
# ---------------------------------------------------------------------------


def save_publication_claims(
    session,
    evaluation_id: int,
    claims: list[dict[str, Any]],
) -> list[PublicationClaimORM]:
    """把 AI 提取的论文自述写入 publication_claims。

    清空旧 claims 后按顺序重写；自述与外部核验分表存储。
    """
    existing = session.query(PublicationClaimORM).filter_by(evaluation_id=evaluation_id).all()
    for row in existing:
        session.delete(row)
    session.flush()

    rows: list[PublicationClaimORM] = []
    for index, item in enumerate(claims):
        row = PublicationClaimORM(
            evaluation_id=evaluation_id,
            claim_key=str(item.get("id") or item.get("claim_key") or f"c{index + 1}"),
            title=str(item.get("title", "")).strip(),
            venue=str(item.get("venue", "") or ""),
            year=str(item.get("year", "") or ""),
            claimed_role=str(item.get("claimed_role", "") or "不明"),
            claimed_status=str(item.get("claimed_status", "") or "unknown"),
            source_quote=str(item.get("source_quote", "") or ""),
            rationale=str(item.get("rationale", "") or ""),
            confidence=float(item.get("confidence", 0.0) or 0.0),
            order_index=index,
        )
        session.add(row)
        rows.append(row)
    session.commit()
    for row in rows:
        session.refresh(row)
    return rows


def save_publication_verification(
    session,
    claim_id: int,
    source: str,
    matched_title: str = "",
    verified_status: str = "pending",
    author_position_match: str = "pending",
    identity_confidence: float = 0.0,
    conflicts: list[str] | None = None,
    failure_reason: str = "",
    checked_at: datetime | None = None,
) -> PublicationVerificationORM:
    """写入或更新某条 claim 的外部核验结果。

    同一 claim_id 至多一条核验（一对一）；
    重试时覆盖旧记录的核验字段，但 ``human_*`` 字段不动。
    """
    row = (
        session.query(PublicationVerificationORM)
        .filter_by(claim_id=claim_id)
        .first()
    )
    if row is None:
        row = PublicationVerificationORM(claim_id=claim_id, source=source)
        session.add(row)
    row.source = source
    row.matched_title = matched_title
    row.verified_status = verified_status
    row.author_position_match = author_position_match
    row.identity_confidence = identity_confidence
    row.conflicts = conflicts or []
    row.failure_reason = failure_reason
    row.checked_at = checked_at or _now()
    session.commit()
    session.refresh(row)
    return row


def list_publication_claims(session, evaluation_id: int) -> list[PublicationClaimORM]:
    return (
        session.query(PublicationClaimORM)
        .filter_by(evaluation_id=evaluation_id)
        .order_by(PublicationClaimORM.order_index, PublicationClaimORM.id)
        .all()
    )


def create_publication_verification_task(
    session,
    evaluation_id: int,
    claim_ids: list[int] | None = None,
) -> TaskORM:
    """派发外部论文核验任务。

    ``claim_ids=None`` 表示重试整个 evaluation 的所有 claims。
    """
    return create_task(
        session,
        task_type="publication_verification",
        payload={
            "evaluation_id": evaluation_id,
            "claim_ids": claim_ids,
        },
    )


# ---------------------------------------------------------------------------
# JD 池：JD 原文 + LLM 起草的 track spec（人批激活后参与评估）
# ---------------------------------------------------------------------------


def jd_to_dict(row: JdEntryORM) -> dict[str, Any]:
    return {
        "id": row.id,
        "title": row.title,
        "team": row.team or "",
        "raw_text": row.raw_text or "",
        "track_key": row.track_key or "",
        "spec": json.loads(row.spec) if row.spec else None,
        "supplements": list(row.supplements or []),
        "assessment_card": dict(row.assessment_card or {}),
        "card_status": row.card_status or "generating",
        "card_error": row.card_error or "",
        "card_run_trace": list(row.card_run_trace or []),
        "card_model_usage": list(row.card_model_usage or []),
        "archived": bool(row.archived),
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "updated_at": row.updated_at.isoformat() if row.updated_at else "",
    }


def list_jds(session, include_archived: bool = True) -> list[JdEntryORM]:
    query = session.query(JdEntryORM)
    if not include_archived:
        query = query.filter(JdEntryORM.archived.is_(False))
    return list(query.order_by(JdEntryORM.created_at.desc()).all())


def create_jd(session, title: str, team: str, raw_text: str) -> JdEntryORM:
    row = JdEntryORM(title=title, team=team, raw_text=raw_text, card_status="generating")
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def update_jd(session, jd_id: str, title: str, team: str, raw_text: str) -> JdEntryORM | None:
    row = session.get(JdEntryORM, jd_id)
    if row is None:
        return None
    row.title = title
    row.team = team
    if raw_text != (row.raw_text or ""):
        row.card_status = "generating"
        row.card_error = ""
    row.raw_text = raw_text
    session.commit()
    session.refresh(row)
    return row


def save_jd_spec(session, jd_id: str, spec_dict: dict[str, Any]) -> JdEntryORM | None:
    row = session.get(JdEntryORM, jd_id)
    if row is None:
        return None
    row.spec = json.dumps(spec_dict, ensure_ascii=False)
    row.track_key = str(spec_dict.get("key", ""))
    row.spec_version = (row.spec_version or 0) + 1
    session.commit()
    session.refresh(row)
    return row


def replace_jd_assessment_card(
    session,
    jd_id: str,
    supplements: list[str],
    card: dict[str, Any],
    run_trace: list[dict[str, Any]] | None = None,
    model_usage: list[dict[str, str]] | None = None,
) -> JdEntryORM | None:
    """原子替换当前岗位卡，并只失效该 JD 的当前候选人报告。"""
    row = session.get(JdEntryORM, jd_id)
    if row is None:
        return None
    row.supplements = [str(item).strip() for item in supplements if str(item).strip()]
    row.assessment_card = card
    row.card_status = "ready"
    row.card_error = ""
    row.card_run_trace = run_trace or []
    row.card_model_usage = model_usage or []
    session.query(CandidateJdAssessmentORM).filter_by(jd_id=jd_id, is_valid=True).update(
        {
            CandidateJdAssessmentORM.is_valid: False,
            CandidateJdAssessmentORM.invalid_reason: "岗位评估卡已更新",
        },
        synchronize_session=False,
    )
    session.commit()
    session.refresh(row)
    return row


def fail_jd_assessment_card(session, jd_id: str, error: Exception | str) -> JdEntryORM | None:
    row = session.get(JdEntryORM, jd_id)
    if row is None:
        return None
    row.card_status = "failed"
    row.card_error = str(error)
    session.commit()
    session.refresh(row)
    return row


def delete_jd(session, jd_id: str) -> bool:
    row = session.get(JdEntryORM, jd_id)
    if row is None:
        return False
    session.delete(row)
    session.commit()
    return True


def list_active_jds(session) -> list[JdEntryORM]:
    """旧接口兼容：返回所有可选择且岗位卡可用的 JD，不再读取 active 状态。"""
    return list(
        session.query(JdEntryORM)
        .filter(JdEntryORM.archived.is_(False), JdEntryORM.card_status == "ready")
        .order_by(JdEntryORM.created_at.asc())
        .all()
    )


def invalidate_assessments_for_jd(session, jd_id: str, reason: str) -> int:
    count = (
        session.query(CandidateJdAssessmentORM)
        .filter_by(jd_id=jd_id, is_valid=True)
        .update(
            {
                CandidateJdAssessmentORM.is_valid: False,
                CandidateJdAssessmentORM.invalid_reason: reason,
            },
            synchronize_session=False,
        )
    )
    session.commit()
    return int(count)


def invalidate_assessments_for_candidate(session, candidate_id: str, reason: str) -> int:
    count = (
        session.query(CandidateJdAssessmentORM)
        .filter_by(candidate_id=candidate_id, is_valid=True)
        .update(
            {
                CandidateJdAssessmentORM.is_valid: False,
                CandidateJdAssessmentORM.invalid_reason: reason,
            },
            synchronize_session=False,
        )
    )
    session.commit()
    return int(count)


def create_interview_assessment_batch(
    session,
    candidate_ids: list[str],
    jd_ids: list[str],
    owner_id: str | None = None,
) -> InterviewAssessmentBatchORM:
    """创建批次和 N×M 个运行记录，不启动模型调用。"""
    candidates = list(dict.fromkeys(candidate_ids))
    jobs = list(dict.fromkeys(jd_ids))
    if not candidates or not jobs:
        raise ValueError("候选人和 JD 均不能为空。")
    existing_candidates = {
        value for (value,) in session.query(CandidateORM.id).filter(CandidateORM.id.in_(candidates)).all()
    }
    existing_jobs = {
        value
        for (value,) in session.query(JdEntryORM.id)
        .filter(
            JdEntryORM.id.in_(jobs),
            JdEntryORM.archived.is_(False),
            JdEntryORM.card_status == "ready",
        )
        .all()
    }
    if existing_candidates != set(candidates):
        raise ValueError("批次包含不存在的候选人。")
    if existing_jobs != set(jobs):
        raise ValueError("批次包含不存在、已归档或岗位卡未就绪的 JD。")

    batch = InterviewAssessmentBatchORM(
        owner_id=owner_id,
        candidate_ids=candidates,
        jd_ids=jobs,
        total_pairs=len(candidates) * len(jobs),
    )
    session.add(batch)
    session.flush()
    runs = [
        InterviewAssessmentRunORM(batch_id=batch.id, candidate_id=candidate_id, jd_id=jd_id)
        for candidate_id in candidates
        for jd_id in jobs
    ]
    session.add_all(runs)
    session.flush()
    session.add_all(
        InterviewAssessmentPairLockORM(
            candidate_id=run.candidate_id,
            jd_id=run.jd_id,
            run_id=run.id,
        )
        for run in runs
    )
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ValueError("部分候选人–JD 配对正在评估，请等待当前运行结束。") from exc
    session.refresh(batch)
    return batch
