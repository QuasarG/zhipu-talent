"""奖学金初筛 API：/api/scholarship/*（鉴权由全局 middleware 负责，
feishu-webhook 例外——凭 URL 内随机 token 自证）。"""
from __future__ import annotations

import logging
import os
import re
import secrets

from flask import Blueprint, Response, jsonify, request

from agi_talent_radar.core.db.runtime import get_session
from agi_talent_radar.core.db.orm import ScholarshipApplicationORM
from agi_talent_radar.scholarship import ingest, pipeline
from agi_talent_radar.scholarship.feishu_pull import FEISHU_FIELD_MAP, feishu_configured
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
        "feishu_record_id": app.feishu_record_id or "",
        "name_en": app.name_en or "",
        "phone": app.phone or "",
        "email": app.email or "",
        "country": app.country or "",
        "lab": app.lab or "",
        "advisor_title": app.advisor_title or "",
        "grade": app.grade or "",
        "research_summary": app.research_summary or "",
        "education_history": app.education_history or "",
        "submitted_at": app.submitted_at.isoformat() if app.submitted_at else None,
        "materials_count": sum(1 for m in app.materials if m.kind != "code"),
        "blind_score": latest_eval.blind_score if latest_eval else None,
        "reputation_adjustment": pipeline.reputation_adjustment(session, app),
        "total_score": pipeline.total_score(session, app),
        "pending_reputation": sum(1 for i in app.reputation_items if i.review_status == "pending"),
    }
    if detail:
        # code 类（工程文件）静默归档：不进前端列表，仅计数披露
        visible_materials = [m for m in app.materials if m.kind != "code"]
        data["materials"] = [
            {
                "id": m.id, "kind": m.kind, "filename": m.filename,
                "advisor_name": m.advisor_name or "",
                "raw_text": m.raw_text or "",
                "has_file": bool((m.file_path or "").strip() and os.path.isfile(m.file_path)),
            }
            for m in visible_materials
        ]
        data["code_files_count"] = sum(1 for m in app.materials if m.kind == "code")
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

    # ---- 飞书问卷自动化 webhook ----
    # 飞书「添加新记录时」发 HTTP POST 到本端点；URL 含随机 token 自证（不走登录会话）。
    # 两种触发模式：
    #   A. 平铺字段：自动化里直接把问卷字段作为 JSON body 发来（键=字段名）；
    #   B. record_id 反查：body 只带 record_id，服务端配了飞书 app 凭证时自动拉全量字段+附件。
    @bp.get("/api/scholarship/feishu-webhook/<token>")
    def feishu_webhook_ping(token: str):
        expected = os.getenv("SCHOLARSHIP_WEBHOOK_TOKEN", "").strip()
        if not expected or not secrets.compare_digest(token, expected):
            return jsonify({"detail": "无效的 webhook token"}), 404
        return jsonify({"ok": True, "pull_mode": feishu_configured()})

    @bp.post("/api/scholarship/feishu-webhook/<token>")
    def feishu_webhook(token: str):
        expected = os.getenv("SCHOLARSHIP_WEBHOOK_TOKEN", "").strip()
        if not expected or not secrets.compare_digest(token, expected):
            return jsonify({"detail": "无效的 webhook token"}), 404
        body = request.get_json(silent=True)
        if body is None:
            # 飞书自动化把多行文本原样插进 JSON 模板会产生非法 JSON（裸换行/未转义引号），
            # json_repair 兜底修复，别让真实问卷在门口 400
            from json_repair import loads as repair_json_loads

            try:
                body = repair_json_loads(request.get_data(as_text=True) or "")
            except Exception:  # noqa: BLE001
                body = None
        if not isinstance(body, dict):
            return jsonify({"detail": "body 必须是 JSON 对象"}), 400
        # 飞书自动化变量里没有「记录ID」：平铺模式用「自动编号」字段做幂等键
        record_id = (
            str(body.get("record_id") or "").strip()
            or str(body.get("自动编号") or "").strip()
        )

        # 模式 B：record_id 反查（凭证齐备时优先，能顺带拉附件）
        payload: dict = {}
        real_id = ""
        if record_id and feishu_configured():
            try:
                from agi_talent_radar.scholarship import feishu_pull

                real_id = record_id
                if not re.fullmatch(r"rec[A-Za-z0-9]+", real_id):
                    # 自动化变量里没有「记录ID」，body 只带「自动编号」业务键，先反解
                    resolved = feishu_pull.resolve_auto_number(real_id)
                    if resolved:
                        real_id = resolved
                        logging.getLogger(__name__).info(
                            "auto-number %s resolved to %s", record_id, real_id)
                payload = feishu_pull.fetch_record(real_id)
                payload["record_id"] = real_id
                if real_id != record_id:
                    # 旧档可能以「自动编号」为幂等键存过，带上让 upsert 迁移，避免重复建档
                    payload["legacy_record_id"] = record_id
            except Exception as exc:  # noqa: BLE001 — 反查失败降级平铺，不阻断推送
                payload = {}
                real_id = ""
                logging.getLogger(__name__).warning("feishu pull failed, fallback to flat body: %s", exc)

        if not payload:
            # 模式 A：平铺字段直收（自动化里把问卷字段原样放进 body）
            from agi_talent_radar.scholarship.feishu_pull import _normalize_text

            payload = {"record_id": record_id}
            for zh, en in FEISHU_FIELD_MAP.items():
                value = body.get(zh)
                if value in (None, ""):
                    continue
                payload[en] = _normalize_text(value)
            if payload.get("expected_graduation"):
                from agi_talent_radar.scholarship.feishu_pull import _normalize_datetime

                month, _ = _normalize_datetime(payload["expected_graduation"])
                if month:
                    payload["expected_graduation"] = month
            if payload.get("advisors"):
                import re as _re

                payload["advisors"] = [
                    a for a in _re.split(r"[、,，;；/]", payload["advisors"]) if a.strip()
                ]
            grade = payload.get("grade") or ""
            if "博士" in grade or "phd" in grade.lower():
                payload["degree_type"] = "phd"
            elif "硕士" in grade or "master" in grade.lower():
                payload["degree_type"] = "master"

        with get_session() as session:
            try:
                app_row, created = ingest.upsert_application_from_feishu(session, payload)
            except ValueError as exc:
                return jsonify({"detail": str(exc)}), 400
            # 新材料进来后回到 imported，随后立即自动筛选
            app_row.status = "imported"
            try:
                screen_result = pipeline.screen_application(session, app_row)
            except Exception as exc:  # noqa: BLE001 — 筛选失败不回滚落库，细节留在状态里
                screen_result = {"status": "imported", "missing": [], "reasons": [f"自动筛选失败: {exc}"]}
                logging.getLogger(__name__).warning("feishu webhook auto-screen failed: %s", exc)
            session.commit()
            # 自动发确认邮件（姓名/邮箱/国家取问卷记录）；首次与修改提交都发，文案区分；
            # MAIL_ENABLED=False 时只记日志不发送；失败不阻断同步
            email_result = {"sent": False}
            from agi_talent_radar.scholarship import mail_sender

            if mail_sender.mail_configured():
                try:
                    email_result = mail_sender.send_confirmation_email(
                        app_row.email or "", app_row.name or "",
                        is_update=not created,
                        country=getattr(app_row, "country", "") or "",
                        applicant_name_en=getattr(app_row, "name_en", "") or "",
                    )
                    if not email_result.get("sent"):
                        logging.getLogger(__name__).warning(
                            "confirmation mail failed: %s %s",
                            app_row.name, email_result.get("error"),
                        )
                    elif not email_result.get("marked"):
                        logging.getLogger(__name__).warning(
                            "table mark failed after mail sent: %s %s",
                            app_row.name, email_result.get("mark_error"),
                        )
                except Exception as exc:  # noqa: BLE001
                    email_result = {"sent": False, "error": str(exc)}
                    logging.getLogger(__name__).warning("confirmation mail error: %s", exc)
        return jsonify({
            "ok": True,
            "duplicate": not created,
            "application_id": app_row.id,
            "status": screen_result.get("status"),
            "email_sent": bool(email_result.get("sent")),
            "table_marked": bool(email_result.get("marked")),
        }), 201 if created else 200

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

    # ---- 材料原件预览 / 下载（浏览器原生渲染 PDF/图片；docx 走下载） ----
    _PREVIEW_MIME = {
        # 文档
        ".pdf": "application/pdf", ".txt": "text/plain; charset=utf-8",
        ".md": "text/plain; charset=utf-8", ".csv": "text/plain; charset=utf-8",
        ".log": "text/plain; charset=utf-8",
        # 图片
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".webp": "image/webp", ".gif": "image/gif", ".bmp": "image/bmp", ".svg": "image/svg+xml",
        # 视频（iframe 原生播放）
        ".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime",
        # 音频
        ".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4",
        # 代码/数据（text/plain 直显；json/jsonl/yaml/toml 也按文本）
        ".py": "text/plain; charset=utf-8", ".sh": "text/plain; charset=utf-8",
        ".ipynb": "text/plain; charset=utf-8", ".json": "text/plain; charset=utf-8",
        ".jsonl": "text/plain; charset=utf-8", ".yaml": "text/plain; charset=utf-8",
        ".yml": "text/plain; charset=utf-8", ".toml": "text/plain; charset=utf-8",
        ".slurm": "text/plain; charset=utf-8", ".gitignore": "text/plain; charset=utf-8",
        ".lock": "text/plain; charset=utf-8", ".html": "text/html; charset=utf-8",
    }

    def _sniff_mime(path: str, filename: str) -> str:
        """无/罕见扩展名按文件头嗅探。"""
        try:
            with open(path, "rb") as fp:
                head = fp.read(16)
        except OSError:
            return "application/octet-stream"
        if head.startswith(b"%PDF"):
            return "application/pdf"
        if head.startswith(b"PK" + bytes([3, 4])):
            return "application/zip"
        if head.startswith(bytes([0xFF, 0xD8, 0xFF])):
            return "image/jpeg"
        if head.startswith(bytes([0x89]) + b"PNG"):
            return "image/png"
        if head.startswith(b"GIF8"):
            return "image/gif"
        if head[4:8] == b"ftyp":
            brand = head[8:12]
            if brand in (b"M4A ", b"M4B "):
                return "audio/mp4"
            return "video/mp4"
        if head.startswith(b"ID3") or head.startswith(bytes([0xFF, 0xFB])):
            return "audio/mpeg"
        if head.startswith(bytes([0x1A, 0x45, 0xDF, 0xA3])):
            return "video/webm"
        try:
            with open(path, "rb") as fp:
                fp.read(2048).decode("utf-8")
            return "text/plain; charset=utf-8"
        except (UnicodeDecodeError, OSError):
            return "application/octet-stream"

    def _docx_preview_html(path: str, title: str) -> Response:
        """docx → HTML（mammoth 保格式转换），iframe 内直接渲染，不触发下载。"""
        import mammoth

        with open(path, "rb") as fp:
            result = mammoth.convert_to_html(fp)
        body = result.value or "<p>（文档为空）</p>"
        html = (
            "<!DOCTYPE html><html><head><meta charset='utf-8'>"
            "<style>"
            "body{font-family:MiSans,system-ui,sans-serif;margin:24px auto;max-width:760px;"
            "color:#0F1115;line-height:1.7;font-size:14px}"
            "img{max-width:100%}table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:6px 10px}"
            "</style></head>"
            f"<title>{title}</title><body>{body}</body></html>"
        )
        return Response(html, mimetype="text/html; charset=utf-8")

    def _material_file_response(material, as_attachment: bool):
        from flask import send_file

        path = (material.file_path or "").strip()
        if not path or not os.path.isfile(path):
            return jsonify({"detail": "原始文件未保存（历史材料仅有提取文本）"}), 404
        # 路径必须落在材料目录内（防穿越）
        if os.path.commonpath([os.path.abspath(path), os.path.abspath(os.path.join(os.getcwd(), "uploads", "scholarship"))]) != os.path.abspath(os.path.join(os.getcwd(), "uploads", "scholarship")):
            return jsonify({"detail": "非法文件路径"}), 400
        ext = "." + path.rsplit(".", 1)[-1].lower() if "." in path else ""
        # docx：预览走 mammoth 转 HTML（浏览器原生不认 docx，直出会变成下载）
        if ext == ".docx" and not as_attachment:
            return _docx_preview_html(path, material.filename or os.path.basename(path))
        mime = _PREVIEW_MIME.get(ext) or _sniff_mime(path, material.filename or "")
        return send_file(
            path,
            mimetype=mime,
            as_attachment=as_attachment,
            download_name=material.filename or os.path.basename(path),
        )

    @bp.get("/api/scholarship/materials/<int:material_id>/preview")
    def material_preview(material_id: int):
        from agi_talent_radar.core.db.orm import ScholarshipMaterialORM

        with get_session() as session:
            material = session.get(ScholarshipMaterialORM, material_id)
            if not material:
                return jsonify({"detail": "材料不存在"}), 404
            return _material_file_response(material, as_attachment=False)

    @bp.get("/api/scholarship/materials/<int:material_id>/download")
    def material_download(material_id: int):
        from agi_talent_radar.core.db.orm import ScholarshipMaterialORM

        with get_session() as session:
            material = session.get(ScholarshipMaterialORM, material_id)
            if not material:
                return jsonify({"detail": "材料不存在"}), 404
            return _material_file_response(material, as_attachment=True)

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

    return bp
