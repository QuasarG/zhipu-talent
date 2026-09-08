from __future__ import annotations

from flask import Blueprint, jsonify, request
from sqlalchemy.orm import Session

from agi_talent_radar.core.collab_events import PROTOCOL, list_collab_events
from agi_talent_radar.core.db.runtime import get_session


def _run_exists(session: Session, run_kind: str, run_id: str) -> bool:
    if run_kind == "panel":
        from agi_talent_radar.core.db.orm import EvaluationORM

        try:
            return session.get(EvaluationORM, int(run_id)) is not None
        except ValueError:
            return False
    from agi_talent_radar.core.db.orm import InterviewAssessmentRunORM

    return session.get(InterviewAssessmentRunORM, run_id) is not None


def _resolve_pair_run_id(session: Session, candidate_id: str, jd_id: str) -> str | None:
    """历史报告回放：按配对找最近一次有事件的运行。"""
    from agi_talent_radar.core.db.orm import AgentCollabEventORM, InterviewAssessmentRunORM

    run = (
        session.query(InterviewAssessmentRunORM)
        .filter(
            InterviewAssessmentRunORM.candidate_id == candidate_id,
            InterviewAssessmentRunORM.jd_id == jd_id,
        )
        .order_by(InterviewAssessmentRunORM.created_at.desc(), InterviewAssessmentRunORM.id.desc())
        .first()
    )
    if run is None:
        return None
    exists = (
        session.query(AgentCollabEventORM.id)
        .filter(AgentCollabEventORM.run_kind == "admission", AgentCollabEventORM.run_id == run.id)
        .limit(1)
        .first()
    )
    return run.id if exists else None


def build_collab_blueprint() -> Blueprint:
    """Agent 协作事件流读取：登录态由全局中间件保证，run 校验防止跨运行读取。"""
    bp = Blueprint("agent_collab", __name__, url_prefix="/api")

    @bp.get("/agent-collab/events")
    def collab_events():
        run_kind = request.args.get("run_kind", "")
        run_id = request.args.get("run_id", "")
        candidate_id = request.args.get("candidate_id", "")
        jd_id = request.args.get("jd_id", "")
        if run_kind not in ("panel", "admission"):
            return jsonify({"detail": "run_kind 仅支持 panel/admission"}), 400
        try:
            after_seq = int(request.args.get("after_seq", "-1"))
            limit = min(max(int(request.args.get("limit", "500")), 1), 2000)
        except ValueError:
            return jsonify({"detail": "after_seq/limit 必须是整数"}), 400

        with get_session() as session:
            if not run_id and candidate_id and jd_id and run_kind == "admission":
                run_id = _resolve_pair_run_id(session, candidate_id, jd_id) or ""
                if not run_id:
                    return jsonify({"detail": "该配对没有事件协议记录"}), 404
            if not run_id or not _run_exists(session, run_kind, run_id):
                return jsonify({"detail": "运行不存在"}), 404
            events, latest_seq = list_collab_events(session, run_kind, run_id, after_seq, limit)
        return jsonify({"protocol": PROTOCOL, "run_id": run_id, "events": events, "latest_seq": latest_seq})

    return bp
