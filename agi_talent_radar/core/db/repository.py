from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func

from agi_talent_radar.core.db.orm import (
    CandidateORM,
    DimensionScoreORM,
    EvaluationEvidenceORM,
    EvaluationNodeRunORM,
    EvaluationORM,
    TaskORM,
    TrackAssignmentORM,
    TrackEvaluationORM,
)
from agi_talent_radar.core.models import CandidateEvaluation, CandidateResume, ImportClassification
from agi_talent_radar.core.persons import get_or_create_person
from agi_talent_radar.core.scoring_version import current_scoring_version


def save_candidate(
    session,
    resume: CandidateResume,
    classification: ImportClassification | None = None,
) -> CandidateORM:
    candidate = session.get(CandidateORM, resume.id)
    if candidate is None:
        candidate = CandidateORM(id=resume.id)
        session.add(candidate)

    candidate.name = resume.name or candidate.name
    candidate.target_role = resume.target_role or candidate.target_role
    candidate.stage = resume.stage or candidate.stage
    candidate.raw_text = resume.raw_text or candidate.raw_text
    candidate.education = _json_text(resume.education)
    candidate.directions = _json_text(resume.directions)
    candidate.experiences = _json_text([experience.model_dump() for experience in resume.experiences])
    candidate.projects = _json_text([project.model_dump() for project in resume.projects])
    candidate.publications = _json_text(resume.publications)
    candidate.skills = _json_text(resume.skills)
    candidate.screening_tags = _json_text(resume.screening_tags)
    candidate.source_format = resume.source_format
    candidate.document_analysis = _json_text(resume.document_analysis)

    if classification:
        candidate.import_category = classification.category
        candidate.import_level = classification.level
        candidate.import_confidence = classification.confidence

    session.commit()
    return candidate


def start_evaluation_run(session, candidate_id: str) -> EvaluationORM:
    if session.get(CandidateORM, candidate_id) is None:
        raise ValueError(f"候选人不存在: {candidate_id}")
    evaluation = EvaluationORM(candidate_id=candidate_id, status="running", evaluation_mode="multi_track_v1")
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
    ev.level = evaluation.level
    ev.tier = evaluation.tier
    ev.decision_method = evaluation.decision_method
    ev.one_liner = evaluation.one_liner
    ev.core_strengths = evaluation.core_strengths
    ev.potential_risks = evaluation.potential_risks
    ev.interview_questions = evaluation.interview_questions
    ev.cultivation_direction = evaluation.cultivation_direction
    ev.critic_flags = evaluation.critic_flags
    ev.normalized_education = evaluation.normalized_education
    ev.screening_tags = evaluation.screening_tags
    ev.common_score = evaluation.common_score
    ev.document_score = evaluation.document_score
    ev.routing_confidence = evaluation.routing_confidence
    ev.evaluation_mode = evaluation.evaluation_mode
    ev.config_version = current_scoring_version()
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
    return {
        "overall_score": evaluation.overall_score,
        "level": evaluation.level,
        "tier": evaluation.tier,
        "decision_method": evaluation.decision_method or "",
        "one_liner": evaluation.one_liner or "",
        "core_strengths": evaluation.core_strengths or [],
        "potential_risks": evaluation.potential_risks or [],
        "interview_questions": evaluation.interview_questions or [],
        "cultivation_direction": evaluation.cultivation_direction or [],
        "dimension_scores": common_dimensions,
        "evidence": evidence,
        "critic_flags": evaluation.critic_flags or [],
        "normalized_education": evaluation.normalized_education or [],
        "screening_tags": evaluation.screening_tags or [],
        "common_score": evaluation.common_score or 0,
        "document_score": evaluation.document_score or 0,
        "track_assignments": assignments,
        "track_evaluations": track_evaluations,
        "routing_confidence": evaluation.routing_confidence or 0,
        "evaluation_mode": evaluation.evaluation_mode or "multi_track_v1",
        "status": evaluation.status,
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


def list_candidates_by_group(session, group: str):
    return (
        session.query(CandidateORM)
        .filter_by(group=group)
        .order_by(CandidateORM.import_level.desc(), CandidateORM.created_at.desc())
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
    """把评估挂到人员主档：优先取候选人记录里的姓名和方向。"""
    candidate = session.get(CandidateORM, evaluation.id)
    name = (candidate.name if candidate else "") or evaluation.name
    direction = ""
    if candidate and candidate.directions:
        items = _as_list(candidate.directions)
        if items:
            direction = str(items[0])[:256]
    return get_or_create_person(session, name=name, direction=direction)


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
