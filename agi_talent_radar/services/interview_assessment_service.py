from __future__ import annotations

import hashlib
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import and_, or_

from agi_talent_radar.agents.interview_admission import (
    AssessmentCard,
    evaluate_candidate_for_job,
    generate_assessment_card,
)
from agi_talent_radar.core.db.orm import (
    CandidateJdAssessmentORM,
    CandidateORM,
    InterviewAssessmentBatchORM,
    InterviewAssessmentPairLockORM,
    InterviewAssessmentRunORM,
    JdEntryORM,
)
from agi_talent_radar.core.db.repository import create_interview_assessment_batch
from agi_talent_radar.core.db.repository import replace_jd_assessment_card
from agi_talent_radar.core.db.runtime import get_session
from agi_talent_radar.core.models import CandidateResume


ASSESSMENT_RULE_VERSION = "interview-admission-v1"
MAX_BATCH_PAIRS = max(1, int(os.getenv("ADMISSION_MAX_BATCH_PAIRS", "20")))
_PAIR_EXECUTOR = ThreadPoolExecutor(
    max_workers=max(1, int(os.getenv("ADMISSION_PAIR_CONCURRENCY", "50"))),
    thread_name_prefix="admission-pair",
)
_RUN_LOCKS: dict[str, threading.Lock] = {}
_RUN_LOCKS_GUARD = threading.Lock()


class AssessmentCancelled(RuntimeError):
    pass


def generate_and_store_card(jd_id: str, supplements: list[str]) -> dict[str, Any]:
    """生成、质检并原子晋升岗位卡；失败时保留已有卡和已有报告。"""
    with get_session() as session:
        assert_jd_editable(session, jd_id)
        jd = session.get(JdEntryORM, jd_id)
        if jd is None:
            raise ValueError("JD 不存在。")
        title, team, raw_text = jd.title, jd.team or "", jd.raw_text or ""
        had_card = bool(jd.assessment_card)
        jd.card_status = "generating"
        jd.card_error = ""
        session.commit()

    trace: list[dict[str, Any]] = []
    model_usage: list[dict[str, str]] = []
    try:
        card = generate_assessment_card(
            title,
            team,
            raw_text,
            supplements,
            on_event=trace.append,
            on_call=model_usage.append,
        )
        with get_session() as session:
            row = replace_jd_assessment_card(
                session,
                jd_id,
                supplements,
                card.model_dump(),
                trace,
                model_usage,
            )
            if row is None:
                raise ValueError("JD 不存在。")
            from agi_talent_radar.core.db.repository import jd_to_dict

            return jd_to_dict(row)
    except Exception as exc:
        with get_session() as session:
            row = session.get(JdEntryORM, jd_id)
            if row is not None:
                row.card_status = "ready" if had_card else "failed"
                row.card_error = str(exc)
                row.card_run_trace = trace
                row.card_model_usage = model_usage
                session.commit()
        raise


def start_batch(
    candidate_ids: list[str],
    jd_ids: list[str],
    owner_id: str | None,
    *,
    pairs: list[tuple[str, str]] | None = None,
    request_id: str | None = None,
    force_reason: str = "",
) -> dict[str, Any]:
    normalized_pairs = list(dict.fromkeys(
        pairs if pairs is not None else [
            (candidate_id, jd_id)
            for candidate_id in candidate_ids
            for jd_id in jd_ids
        ]
    ))
    if not normalized_pairs:
        raise ValueError("至少选择一个候选人–JD 配对。")
    if len(normalized_pairs) > MAX_BATCH_PAIRS:
        raise ValueError(f"单批最多允许 {MAX_BATCH_PAIRS} 个配对。")
    normalized_request_id = (request_id or uuid4().hex).strip()
    if len(normalized_request_id) > 64:
        raise ValueError("request_id 最长 64 个字符。")

    with get_session() as session:
        existing_batch = (
            session.query(InterviewAssessmentBatchORM)
            .filter_by(request_id=normalized_request_id)
            .first()
        )
        if existing_batch is not None:
            existing_pairs = {
                (row.candidate_id, row.jd_id)
                for row in session.query(InterviewAssessmentRunORM)
                .filter_by(batch_id=existing_batch.id)
                .all()
            }
            if existing_pairs != set(normalized_pairs):
                raise ValueError("request_id 已用于另一组评估配对。")
            return batch_to_dict(existing_batch)

        running = (
            session.query(InterviewAssessmentRunORM)
            .filter(
                or_(*[
                    and_(
                        InterviewAssessmentRunORM.candidate_id == candidate_id,
                        InterviewAssessmentRunORM.jd_id == jd_id,
                    )
                    for candidate_id, jd_id in normalized_pairs
                ]),
                InterviewAssessmentRunORM.status.in_(("queued", "running")),
            )
            .first()
        )
        if running is not None:
            raise ValueError("所选候选人–JD 配对正在评估，请等待当前运行结束。")
        repeated = (
            session.query(CandidateJdAssessmentORM)
            .filter(
                or_(*[
                    and_(
                        CandidateJdAssessmentORM.candidate_id == candidate_id,
                        CandidateJdAssessmentORM.jd_id == jd_id,
                    )
                    for candidate_id, jd_id in normalized_pairs
                ]),
                CandidateJdAssessmentORM.is_valid.is_(True),
            )
            .count()
        )
        normalized_force_reason = force_reason.strip()
        if repeated and not normalized_force_reason:
            raise ValueError("所选配对包含已有有效报告；强制重评必须填写原因。")
        batch = create_interview_assessment_batch(
            session,
            candidate_ids,
            jd_ids,
            owner_id,
            pairs=normalized_pairs,
            request_id=normalized_request_id,
            config_version=ASSESSMENT_RULE_VERSION,
            force_reason=normalized_force_reason,
        )
        batch.status = "running"
        batch.started_at = _now()
        run_ids = [row.id for row in session.query(InterviewAssessmentRunORM).filter_by(batch_id=batch.id).all()]
        session.commit()
        payload = batch_to_dict(batch)

    for run_id in run_ids:
        _PAIR_EXECUTOR.submit(_run_pair, run_id)
    return payload


def get_batch(batch_id: str) -> dict[str, Any] | None:
    with get_session() as session:
        batch = session.get(InterviewAssessmentBatchORM, batch_id)
        if batch is None:
            return None
        runs = (
            session.query(InterviewAssessmentRunORM)
            .filter_by(batch_id=batch_id)
            .order_by(InterviewAssessmentRunORM.created_at, InterviewAssessmentRunORM.id)
            .all()
        )
        names, titles = _candidate_jd_labels(
            session,
            {row.candidate_id for row in runs},
            {row.jd_id for row in runs},
        )
        return {
            **batch_to_dict(batch),
            "runs": [
                run_to_dict(row, candidate_name=names.get(row.candidate_id, ""), jd_title=titles.get(row.jd_id, ""))
                for row in runs
            ],
        }


def list_active_runs() -> list[dict[str, Any]]:
    """返回全局活动配对（含候选人姓名与 JD 标题），供所有用户同步互斥状态。"""
    with get_session() as session:
        # 兼容旧版本留下的半取消状态：用户已经发出停止请求时，
        # 查询活动任务也必须先把运行记录推进到终态并释放配对锁。
        pending_cancellations = (
            session.query(InterviewAssessmentRunORM)
            .filter(
                InterviewAssessmentRunORM.status.in_(("queued", "running")),
                InterviewAssessmentRunORM.cancellation_requested.is_(True),
            )
            .all()
        )
        affected_batches = {row.batch_id for row in pending_cancellations}
        for row in pending_cancellations:
            _mark_run_cancelled(session, row)
        if pending_cancellations:
            session.commit()
            for batch_id in affected_batches:
                _refresh_batch(session, batch_id)

        rows = (
            session.query(InterviewAssessmentRunORM)
            .filter(InterviewAssessmentRunORM.status.in_(("queued", "running")))
            .order_by(InterviewAssessmentRunORM.created_at, InterviewAssessmentRunORM.id)
            .all()
        )
        names, titles = _candidate_jd_labels(
            session,
            {row.candidate_id for row in rows},
            {row.jd_id for row in rows},
        )
        return [
            run_to_dict(row, candidate_name=names.get(row.candidate_id, ""), jd_title=titles.get(row.jd_id, ""))
            for row in rows
        ]


def cancel_run(run_id: str) -> bool:
    with get_session() as session:
        run = session.get(InterviewAssessmentRunORM, run_id)
        if run is None or run.status not in {"queued", "running"}:
            return False
        run.cancellation_requested = True
        batch_id = run.batch_id
        _mark_run_cancelled(session, run)
        session.commit()
        _refresh_batch(session, batch_id)
        return True


def cancel_batch(batch_id: str) -> int:
    with get_session() as session:
        runs = (
            session.query(InterviewAssessmentRunORM)
            .filter(
                InterviewAssessmentRunORM.batch_id == batch_id,
                InterviewAssessmentRunORM.status.in_(("queued", "running")),
            )
            .all()
        )
        for run in runs:
            run.cancellation_requested = True
            _mark_run_cancelled(session, run)
        session.commit()
        _refresh_batch(session, batch_id)
        return len(runs)


def list_current_assessments(
    candidate_ids: list[str] | None = None,
    jd_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    with get_session() as session:
        query = session.query(CandidateJdAssessmentORM)
        if candidate_ids:
            query = query.filter(CandidateJdAssessmentORM.candidate_id.in_(candidate_ids))
        if jd_ids:
            query = query.filter(CandidateJdAssessmentORM.jd_id.in_(jd_ids))
        rows = query.order_by(
            CandidateJdAssessmentORM.jd_id,
            CandidateJdAssessmentORM.decision.asc(),
            CandidateJdAssessmentORM.total_score.desc(),
        ).all()
        names, titles = _candidate_jd_labels(
            session,
            {row.candidate_id for row in rows},
            {row.jd_id for row in rows},
        )
        return [
            assessment_to_dict(
                row,
                candidate_name=names.get(row.candidate_id, ""),
                jd_title=titles.get(row.jd_id, ""),
            )
            for row in rows
        ]


def assert_candidate_editable(session, candidate_id: str) -> None:
    active = session.query(InterviewAssessmentRunORM.id).filter(
        InterviewAssessmentRunORM.candidate_id == candidate_id,
        InterviewAssessmentRunORM.status.in_(("queued", "running")),
    ).first()
    if active is not None:
        raise RuntimeError("该候选人正在进行面试准入评估，请先停止相关配对。")


def assert_jd_editable(session, jd_id: str) -> None:
    active = session.query(InterviewAssessmentRunORM.id).filter(
        InterviewAssessmentRunORM.jd_id == jd_id,
        InterviewAssessmentRunORM.status.in_(("queued", "running")),
    ).first()
    if active is not None:
        raise RuntimeError("该 JD 正在用于面试准入评估，请先停止相关配对。")


def _run_pair(run_id: str) -> None:
    try:
        with get_session() as session:
            run = session.get(InterviewAssessmentRunORM, run_id)
            if run is None or run.status == "cancelled" or run.cancellation_requested:
                return
            candidate = session.get(CandidateORM, run.candidate_id)
            jd = session.get(JdEntryORM, run.jd_id)
            if candidate is None or jd is None:
                raise ValueError("候选人或 JD 已不存在。")
            if jd.card_status != "ready" or not jd.assessment_card:
                raise ValueError("岗位评估卡未就绪。")
            resume = _candidate_to_resume(candidate)
            card = AssessmentCard.model_validate(jd.assessment_card)
            fingerprint = _input_fingerprint(resume, jd, card)
            run.status = "running"
            run.started_at = _now()
            run.input_fingerprint = fingerprint
            session.commit()

        result = evaluate_candidate_for_job(
            resume,
            jd.id,
            card,
            on_event=lambda event: _append_run_event(run_id, event),
        )

        with get_session() as session:
            run = session.get(InterviewAssessmentRunORM, run_id)
            candidate = session.get(CandidateORM, run.candidate_id) if run else None
            jd = session.get(JdEntryORM, run.jd_id) if run else None
            if run is None or candidate is None or jd is None:
                return
            if run.cancellation_requested:
                _discard_cancelled_run(session, run)
                return
            current_fingerprint = _input_fingerprint(_candidate_to_resume(candidate), jd, AssessmentCard.model_validate(jd.assessment_card))
            if current_fingerprint != run.input_fingerprint:
                raise RuntimeError("评估输入在运行期间发生变化，本次结果已作废。")
            _promote_result(session, run, result.model_dump())
    except AssessmentCancelled:
        with get_session() as session:
            run = session.get(InterviewAssessmentRunORM, run_id)
            if run is not None:
                _discard_cancelled_run(session, run)
    except Exception as exc:  # noqa: BLE001
        with get_session() as session:
            run = session.get(InterviewAssessmentRunORM, run_id)
            if run is not None:
                if run.cancellation_requested or run.status == "cancelled":
                    _discard_cancelled_run(session, run)
                else:
                    run.status = "failed"
                    run.error_message = str(exc)
                    run.staged_result = {}
                    run.completed_at = _now()
                    _release_pair_lock(session, run)
                    session.commit()
                    _refresh_batch(session, run.batch_id)


def _append_run_event(run_id: str, event: dict[str, Any]) -> None:
    lock = _run_lock(run_id)
    with lock, get_session() as session:
        run = session.get(InterviewAssessmentRunORM, run_id)
        if run is None or run.cancellation_requested:
            raise AssessmentCancelled("评估已取消。")
        run.current_node = str(event.get("node_id", ""))
        run.run_trace = [*(run.run_trace or []), event]
        session.commit()


def _promote_result(session, run: InterviewAssessmentRunORM, result: dict[str, Any]) -> None:
    current = session.query(CandidateJdAssessmentORM).filter_by(
        candidate_id=run.candidate_id,
        jd_id=run.jd_id,
    ).first()
    if current is None:
        current = CandidateJdAssessmentORM(candidate_id=run.candidate_id, jd_id=run.jd_id, decision=result["decision"])
        session.add(current)
    current.status = "completed"
    current.is_valid = True
    current.invalid_reason = ""
    current.decision = result["decision"]
    current.total_score = result["total_score"]
    current.task_assessments = result["task_assessments"]
    current.review_corrections = result["review_corrections"]
    current.interview_focus = result["interview_focus"]
    current.model_usage = result["model_usage"]
    current.run_trace = result["run_trace"]
    current.input_fingerprint = run.input_fingerprint
    run.status = "completed"
    run.current_node = "admission_decision"
    run.model_usage = result["model_usage"]
    run.run_trace = result["run_trace"]
    run.staged_result = {}
    run.completed_at = _now()
    _release_pair_lock(session, run)
    session.commit()
    _refresh_batch(session, run.batch_id)


def _discard_cancelled_run(session, run: InterviewAssessmentRunORM) -> None:
    batch_id = run.batch_id
    _mark_run_cancelled(session, run)
    session.commit()
    _refresh_batch(session, batch_id)


def _mark_run_cancelled(session, run: InterviewAssessmentRunORM) -> None:
    """在当前事务中丢弃运行产物并释放锁；由调用方统一提交和刷新批次。"""
    run.cancellation_requested = True
    run.status = "cancelled"
    run.current_node = ""
    run.staged_result = {}
    run.run_trace = []
    run.model_usage = []
    run.error_message = ""
    run.completed_at = _now()
    _release_pair_lock(session, run)


def _refresh_batch(session, batch_id: str) -> None:
    batch = session.get(InterviewAssessmentBatchORM, batch_id)
    if batch is None:
        return
    statuses = [
        value
        for (value,) in session.query(InterviewAssessmentRunORM.status).filter_by(batch_id=batch_id).all()
    ]
    batch.completed_pairs = statuses.count("completed")
    batch.failed_pairs = statuses.count("failed")
    batch.cancelled_pairs = statuses.count("cancelled")
    if statuses and all(status in {"completed", "failed", "cancelled"} for status in statuses):
        batch.status = "completed" if batch.completed_pairs else "failed"
        batch.completed_at = _now()
    session.commit()


def _candidate_to_resume(row: CandidateORM) -> CandidateResume:
    raw_text = row.raw_text or ""
    supplementary = (row.supplementary_info or "").strip()
    if supplementary:
        raw_text = f"{raw_text}\n\n[HR 补充信息]\n{supplementary}"
    return CandidateResume.model_validate(
        {
            "id": row.id,
            "name": row.name or "",
            "target_role": row.target_role or "",
            "stage": row.stage or "",
            "raw_text": raw_text,
            "education": _load_json(row.education),
            "directions": _load_json(row.directions),
            "experiences": _load_json(row.experiences),
            "projects": _load_json(row.projects),
            "publications": _load_json(row.publications),
            "skills": _load_json(row.skills),
            "screening_tags": _load_json(row.screening_tags),
            "source_format": row.source_format or "text",
            "document_analysis": _load_json(row.document_analysis) or {},
        }
    )


def _input_fingerprint(resume: CandidateResume, jd: JdEntryORM, card: AssessmentCard) -> str:
    payload = {
        "resume": resume.model_dump(),
        "jd": {"raw_text": jd.raw_text, "supplements": jd.supplements or [], "card": card.model_dump()},
        "rules": ASSESSMENT_RULE_VERSION,
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def batch_to_dict(row: InterviewAssessmentBatchORM) -> dict[str, Any]:
    return {
        "id": row.id,
        "request_id": row.request_id or "",
        "config_version": row.config_version or "",
        "force_reason": row.force_reason or "",
        "status": row.status,
        "candidate_ids": list(row.candidate_ids or []),
        "jd_ids": list(row.jd_ids or []),
        "total_pairs": row.total_pairs,
        "completed_pairs": row.completed_pairs,
        "failed_pairs": row.failed_pairs,
        "cancelled_pairs": row.cancelled_pairs,
        "created_at": _iso(row.created_at),
        "started_at": _iso(row.started_at),
        "completed_at": _iso(row.completed_at),
    }


def run_to_dict(
    row: InterviewAssessmentRunORM,
    *,
    candidate_name: str = "",
    jd_title: str = "",
) -> dict[str, Any]:
    return {
        "id": row.id,
        "batch_id": row.batch_id,
        "candidate_id": row.candidate_id,
        "candidate_name": candidate_name,
        "jd_id": row.jd_id,
        "jd_title": jd_title,
        "status": row.status,
        "current_node": row.current_node or "",
        "run_trace": list(row.run_trace or []),
        "model_usage": list(row.model_usage or []),
        "error_message": row.error_message or "",
        "cancellation_requested": bool(row.cancellation_requested),
    }


def assessment_to_dict(
    row: CandidateJdAssessmentORM,
    *,
    candidate_name: str = "",
    jd_title: str = "",
) -> dict[str, Any]:
    return {
        "id": row.id,
        "candidate_id": row.candidate_id,
        "candidate_name": candidate_name,
        "jd_id": row.jd_id,
        "jd_title": jd_title,
        "status": row.status,
        "is_valid": bool(row.is_valid),
        "invalid_reason": row.invalid_reason or "",
        "decision": row.decision,
        "total_score": row.total_score,
        "task_assessments": list(row.task_assessments or []),
        "review_corrections": list(row.review_corrections or []),
        "interview_focus": list(row.interview_focus or []),
        "model_usage": list(row.model_usage or []),
        "run_trace": list(row.run_trace or []),
        "updated_at": _iso(row.updated_at),
    }


def _candidate_jd_labels(session, candidate_ids: set[str], jd_ids: set[str]) -> tuple[dict[str, str], dict[str, str]]:
    """按 id 批量取候选人姓名与 JD 标题；报告接口直接返回展示名，前端不再回退到内部 ID。"""
    names: dict[str, str] = {}
    titles: dict[str, str] = {}
    if candidate_ids:
        for row in (
            session.query(CandidateORM.id, CandidateORM.name)
            .filter(CandidateORM.id.in_(candidate_ids))
            .all()
        ):
            names[row.id] = row.name or ""
    if jd_ids:
        for row in (
            session.query(JdEntryORM.id, JdEntryORM.title)
            .filter(JdEntryORM.id.in_(jd_ids))
            .all()
        ):
            titles[row.id] = row.title or ""
    return names, titles


def _run_lock(run_id: str) -> threading.Lock:
    with _RUN_LOCKS_GUARD:
        return _RUN_LOCKS.setdefault(run_id, threading.Lock())


def _release_pair_lock(session, run: InterviewAssessmentRunORM) -> None:
    session.query(InterviewAssessmentPairLockORM).filter_by(run_id=run.id).delete(
        synchronize_session=False
    )


def _load_json(value: Any) -> Any:
    if not value:
        return []
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return []


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None
