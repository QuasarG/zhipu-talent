"""奖学金初筛 API：/api/scholarship/*（鉴权由全局 middleware 负责）。"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from agi_talent_radar.core.db.runtime import get_session
from agi_talent_radar.core.db.orm import ScholarshipApplicationORM
from agi_talent_radar.scholarship import ingest, pipeline
from agi_talent_radar.scholarship.scoring import MAX_LETTERS

SCHOLARSHIP_BP_NAME = "scholarship"


def _eval_to_dict(evaluation) -> dict:
    return {
        "id": evaluation.id,
        "config_version": evaluation.config_version,
        "status": evaluation.status,
        "blind_score": evaluation.blind_score,
        "dimensions": evaluation.dimensions or [],
        "highlights": evaluation.highlights or [],
        "risks": evaluation.risks or [],
        "error_message": evaluation.error_message or "",
        "created_at": evaluation.created_at.isoformat() if evaluation.created_at else None,
    }


def _rep_to_dict(item) -> dict:
    return {
        "id": item.id,
        "subject": item.subject,
        "subject_role": item.subject_role,
        "sentiment": item.sentiment,
        "title": item.title,
        "url": item.url,
        "snippet": item.snippet,
        "concern": item.concern,
        "review_status": item.review_status,
        "adjustment": item.adjustment,
        "reviewer": item.reviewer or "",
    }


def _app_to_dict(session, app: ScholarshipApplicationORM, detail: bool = False) -> dict:
    latest_eval = next(
        (e for e in reversed(app.evaluations) if e.status == "completed"), None
    )
    data = {
        "id": app.id,
        "name": app.name,
        "degree_type": app.degree_type,
        "expected_graduation": app.expected_graduation,
        "direction": app.direction,
        "school": app.school,
        "advisors": app.advisors or [],
        "status": app.status,
        "screening_detail": app.screening_detail or {},
        "brand_bonus": app.brand_bonus or 0.0,
        "brand_note": app.brand_note or "",
        "materials_count": len(app.materials),
        "blind_score": latest_eval.blind_score if latest_eval else None,
        "reputation_adjustment": pipeline.reputation_adjustment(session, app),
        "total_score": pipeline.total_score(session, app),
        "pending_reputation": sum(1 for i in app.reputation_items if i.review_status == "pending"),
    }
    if detail:
        data["materials"] = [
            {
                "id": m.id, "kind": m.kind, "filename": m.filename,
                "advisor_name": m.advisor_name or "",
                "raw_text": m.raw_text or "",
            }
            for m in app.materials
        ]
        data["evaluations"] = [_eval_to_dict(e) for e in app.evaluations]
        data["reputation_items"] = [_rep_to_dict(i) for i in app.reputation_items]
    return data


def build_scholarship_blueprint() -> Blueprint:
    bp = Blueprint(SCHOLARSHIP_BP_NAME, __name__)

    @bp.get("/api/scholarship/applications")
    def list_applications():
        with get_session() as session:
            apps = (
                session.query(ScholarshipApplicationORM)
                .order_by(ScholarshipApplicationORM.created_at.desc())
                .all()
            )
            rows = [_app_to_dict(session, a) for a in apps]
        # 有总分的排前面，按总分降序
        rows.sort(key=lambda r: (r["total_score"] is None, -(r["total_score"] or 0)))
        return jsonify(rows)

    @bp.post("/api/scholarship/applications")
    def create_application():
        body = request.get_json(silent=True) or {}
        try:
            with get_session() as session:
                app = ingest.create_application_from_payload(session, body)
                return jsonify(_app_to_dict(session, app)), 201
        except ValueError as exc:
            return jsonify({"detail": str(exc)}), 400

    @bp.get("/api/scholarship/applications/<app_id>")
    def get_application(app_id: str):
        with get_session() as session:
            app = session.get(ScholarshipApplicationORM, app_id)
            if not app:
                return jsonify({"detail": "申请人不存在"}), 404
            return jsonify(_app_to_dict(session, app, detail=True))

    @bp.delete("/api/scholarship/applications/<app_id>")
    def delete_application(app_id: str):
        with get_session() as session:
            app = session.get(ScholarshipApplicationORM, app_id)
            if not app:
                return jsonify({"detail": "申请人不存在"}), 404
            session.delete(app)
            session.commit()
        return jsonify({"deleted": True})

    @bp.post("/api/scholarship/applications/<app_id>/materials")
    def upload_materials(app_id: str):
        files = request.files.getlist("files")
        if not files:
            return jsonify({"detail": "请上传材料文件"}), 400
        with get_session() as session:
            app = session.get(ScholarshipApplicationORM, app_id)
            if not app:
                return jsonify({"detail": "申请人不存在"}), 404
            added = []
            try:
                for f in files:
                    filename = f.filename or "unnamed"
                    blob = f.read()
                    if filename.lower().endswith(".zip"):
                        added.extend(ingest.add_materials_from_zip(session, app, blob))
                    else:
                        kind = request.form.get(f"kind_{filename}") or None
                        added.append(ingest.add_material(session, app, filename, blob, kind=kind))
            except ValueError as exc:
                return jsonify({"detail": str(exc)}), 400
            # 新材料进来后回到 imported 待重筛
            app.status = "imported"
            session.commit()
            return jsonify({"added": len(added), "max_letters": MAX_LETTERS})

    @bp.post("/api/scholarship/applications/<app_id>/screen")
    def screen(app_id: str):
        with get_session() as session:
            app = session.get(ScholarshipApplicationORM, app_id)
            if not app:
                return jsonify({"detail": "申请人不存在"}), 404
            return jsonify(pipeline.screen_application(session, app))

    @bp.post("/api/scholarship/applications/<app_id>/evaluate")
    def evaluate(app_id: str):
        with get_session() as session:
            app = session.get(ScholarshipApplicationORM, app_id)
            if not app:
                return jsonify({"detail": "申请人不存在"}), 404
            if app.status not in ("eligible", "scored", "finalized"):
                return jsonify({"detail": "请先通过资格与材料筛选再评估"}), 409
            evaluation = pipeline.evaluate_application(session, app)
            return jsonify(_eval_to_dict(evaluation))

    @bp.post("/api/scholarship/applications/<app_id>/reputation-scan")
    def reputation_scan(app_id: str):
        with get_session() as session:
            app = session.get(ScholarshipApplicationORM, app_id)
            if not app:
                return jsonify({"detail": "申请人不存在"}), 404
            items = pipeline.run_reputation_scan(session, app)
            return jsonify({"created": len(items), "items": [_rep_to_dict(i) for i in items]})

    @bp.post("/api/scholarship/reputation-items/<int:item_id>/review")
    def review_reputation(item_id: int):
        body = request.get_json(silent=True) or {}
        try:
            with get_session() as session:
                item = pipeline.review_reputation_item(
                    session, item_id, str(body.get("action") or ""), reviewer=str(body.get("reviewer") or "hr")
                )
                if not item:
                    return jsonify({"detail": "舆情条目不存在"}), 404
                return jsonify(_rep_to_dict(item))
        except ValueError as exc:
            return jsonify({"detail": str(exc)}), 400

    @bp.post("/api/scholarship/applications/<app_id>/brand")
    def set_brand_bonus(app_id: str):
        body = request.get_json(silent=True) or {}
        with get_session() as session:
            app = session.get(ScholarshipApplicationORM, app_id)
            if not app:
                return jsonify({"detail": "申请人不存在"}), 404
            try:
                app.brand_bonus = max(-10.0, min(10.0, float(body.get("bonus") or 0)))
            except (TypeError, ValueError):
                return jsonify({"detail": "bonus 必须是数字"}), 400
            app.brand_note = str(body.get("note") or "")
            if app.status == "scored":
                app.status = "finalized"
            session.commit()
            return jsonify(_app_to_dict(session, app))

    return bp
