from __future__ import annotations

from flask import Blueprint, jsonify, request


def build_interview_assessment_blueprint() -> Blueprint:
    bp = Blueprint("interview_assessment", __name__, url_prefix="/api")

    @bp.post("/jds/<jd_id>/assessment-card")
    def generate_card(jd_id: str):
        from agi_talent_radar.services.interview_assessment_service import generate_and_store_card

        body = request.get_json(silent=True) or {}
        supplements = body.get("supplements") or []
        if not isinstance(supplements, list):
            return jsonify({"detail": "supplements 必须是字符串数组"}), 400
        try:
            return jsonify(generate_and_store_card(jd_id, supplements))
        except ValueError as exc:
            return jsonify({"detail": str(exc)}), 404 if "不存在" in str(exc) else 400
        except RuntimeError as exc:
            return jsonify({"detail": str(exc)}), 409

    @bp.post("/interview-assessment-batches")
    def create_batch():
        from agi_talent_radar.services.interview_assessment_service import start_batch
        from agi_talent_radar.web.auth import current_user

        body = request.get_json(silent=True) or {}
        candidate_ids = body.get("candidate_ids") or []
        jd_ids = body.get("jd_ids") or []
        force = bool(body.get("force", False))
        if not isinstance(candidate_ids, list) or not isinstance(jd_ids, list):
            return jsonify({"detail": "candidate_ids 和 jd_ids 必须是数组"}), 400
        user = current_user()
        can_force = bool(
            user
            and user.username == "guozexin"
            and user.allow_force_reevaluation
        )
        if force and not can_force:
            return jsonify({"detail": "当前账号未启用强制重评权限"}), 403
        try:
            return jsonify(start_batch(candidate_ids, jd_ids, user.id if user else None, force=force)), 202
        except ValueError as exc:
            return jsonify({"detail": str(exc)}), 409

    @bp.get("/interview-assessment-batches/<batch_id>")
    def read_batch(batch_id: str):
        from agi_talent_radar.services.interview_assessment_service import get_batch

        payload = get_batch(batch_id)
        if payload is None:
            return jsonify({"detail": "评估批次不存在"}), 404
        return jsonify(payload)

    @bp.post("/interview-assessment-batches/<batch_id>/cancel")
    def stop_batch(batch_id: str):
        from agi_talent_radar.services.interview_assessment_service import cancel_batch

        return jsonify({"batch_id": batch_id, "cancelled": cancel_batch(batch_id)})

    @bp.post("/interview-assessment-runs/<run_id>/cancel")
    def stop_run(run_id: str):
        from agi_talent_radar.services.interview_assessment_service import cancel_run

        if not cancel_run(run_id):
            return jsonify({"detail": "运行不存在或已经结束"}), 409
        return jsonify({"run_id": run_id, "cancelled": True})

    @bp.get("/interview-assessments")
    def list_assessments():
        from agi_talent_radar.services.interview_assessment_service import list_current_assessments

        candidate_ids = [item for item in request.args.get("candidate_ids", "").split(",") if item]
        jd_ids = [item for item in request.args.get("jd_ids", "").split(",") if item]
        return jsonify(list_current_assessments(candidate_ids or None, jd_ids or None))

    @bp.get("/interview-assessment-settings")
    def get_settings():
        from agi_talent_radar.web.auth import current_user

        user = current_user()
        can_manage = bool(user and user.username == "guozexin")
        return jsonify(
            {
                "can_manage_force_reevaluation": can_manage,
                "allow_force_reevaluation": bool(can_manage and user.allow_force_reevaluation),
            }
        )

    @bp.put("/interview-assessment-settings")
    def update_settings():
        from agi_talent_radar.core.db.orm import UserORM
        from agi_talent_radar.core.db.runtime import get_session
        from agi_talent_radar.web.auth import current_user

        user = current_user()
        if user is None or user.username != "guozexin":
            return jsonify({"detail": "无权修改该设置"}), 403
        enabled = bool((request.get_json(silent=True) or {}).get("allow_force_reevaluation", False))
        with get_session() as session:
            row = session.get(UserORM, user.id)
            if row is None:
                return jsonify({"detail": "账号不存在"}), 404
            row.allow_force_reevaluation = enabled
            session.commit()
        return jsonify({"can_manage_force_reevaluation": True, "allow_force_reevaluation": enabled})

    return bp
