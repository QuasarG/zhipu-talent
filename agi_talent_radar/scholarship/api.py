"""奖学金初筛 API：/api/scholarship/*（鉴权由全局 middleware 负责，
feishu-webhook 例外——凭 URL 内随机 token 自证）。"""
from __future__ import annotations

import json
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

# 发信门比对字段：问卷里申请人真正会改的东西（材料文件变化走 12h 冷却兜底）
_MAIL_DIFF_FIELDS = (
    "name", "name_en", "email", "country", "school", "lab", "direction",
    "grade", "expected_graduation", "research_summary", "education_history",
)
_MAIL_COOLDOWN_HOURS = 12


def _feishu_fields_changed(app: ScholarshipApplicationORM, payload: dict) -> bool:
    """推送字段与库内存档是否有实质差异（None/缺键视为未变）。"""
    for field in _MAIL_DIFF_FIELDS:
        incoming = payload.get(field)
        if incoming in (None, ""):
            continue
        stored = getattr(app, field, None)
        if isinstance(stored, list):
            stored = "、".join(str(x) for x in stored)
        if str(incoming).strip() != str(stored or "").strip():
            return True
    incoming_advisors = payload.get("advisors")
    if isinstance(incoming_advisors, list):
        stored_advisors = "、".join(str(a) for a in (app.advisors or []))
        if "、".join(str(a) for a in incoming_advisors).strip() != stored_advisors.strip():
            return True
    return False


def _within_mail_cooldown(last_mail_at: str) -> bool:
    """上次发信时间在冷却窗口内则 True（解析失败按无冷却处理）。"""
    if not last_mail_at:
        return False
    from datetime import datetime, timedelta

    try:
        sent = datetime.fromisoformat(last_mail_at)
    except ValueError:
        return False
    return datetime.now() - sent < timedelta(hours=_MAIL_COOLDOWN_HOURS)


def _eval_to_dict(evaluation) -> dict:
    final_segment = next((s for s in reversed(evaluation.trace or []) if s.get("type") == "final"), None)
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
        "trace": evaluation.trace or [],
        "recommend_tier": (final_segment or {}).get("recommend_tier") or "",
        "reputation_findings": (final_segment or {}).get("reputation_findings") or [],
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
        "updated_at": app.updated_at.isoformat() if app.updated_at else None,
        "evaluating": any(e.status == "running" for e in app.evaluations),
        "materials_count": sum(1 for m in app.materials if m.kind != "code"),
        "blind_score": latest_eval.blind_score if latest_eval else None,
        "total_score": pipeline.total_score(session, app),
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

        # LLM 语义解析层：导师连写拆分/职务重排/方向分隔符清洗/年级毕业时间规范化。
        # 只对原文做重排（字符多重集校验防幻觉），失败逐字段降级，永不阻断入库
        try:
            from agi_talent_radar.scholarship import field_parser

            raw_fields = {
                "advisors_raw": "、".join(payload.get("advisors") or []),
                "advisor_title_raw": payload.get("advisor_title") or "",
                "direction_raw": payload.get("direction") or "",
                "grade_raw": payload.get("grade") or "",
                "school_raw": payload.get("school") or "",
                "lab_raw": payload.get("lab") or "",
                "grad_raw": payload.get("expected_graduation") or "",
            }
            if field_parser.wants_parsing(raw_fields):
                patch = field_parser.parse_fields(raw_fields)
                payload.update(patch)
        except Exception as exc:  # noqa: BLE001
            logging.getLogger(__name__).warning("field parse failed, keep raw: %s", exc)

        with get_session() as session:
            # 发信门用：upsert 前拍已有档字段快照（upsert 会覆盖，事后没法 diff）
            pre_fields_changed = False
            if payload.get("record_id"):
                existing = (
                    session.query(ScholarshipApplicationORM)
                    .filter(ScholarshipApplicationORM.feishu_record_id == str(payload["record_id"]))
                    .first()
                )
                if existing is not None:
                    pre_fields_changed = _feishu_fields_changed(existing, payload)
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
            # 确认邮件草稿生成门（三重闸，2026-09-01 重复发信事故后加死）：
            # ① 新档才生成首封；② 已有档仅在问卷字段有实质变化时生成更新版；
            # ③ 12 小时冷却兜底。草稿只进草稿箱，人工审核后手动发送。
            email_result = {"drafted": False, "skipped": "no-change"}
            from agi_talent_radar.scholarship import mail_sender

            if not created and pre_fields_changed:
                email_result = {"drafted": False}
            if (created or pre_fields_changed) and mail_sender.mail_configured():
                last_draft_at = str(((app_row.screening_detail or {}).get("last_draft_at") or ""))
                cooled = _within_mail_cooldown(last_draft_at)
                if cooled:
                    email_result = {"drafted": False, "skipped": "cooldown"}
                    logging.getLogger(__name__).info(
                        "confirmation draft cooldown skip: %s", app_row.name)
                else:
                    try:
                        email_result = mail_sender.create_confirmation_draft(
                            app_row.email or "", app_row.name or "",
                            is_update=not created,
                            country=getattr(app_row, "country", "") or "",
                            applicant_name_en=getattr(app_row, "name_en", "") or "",
                        )
                        if not email_result.get("drafted"):
                            logging.getLogger(__name__).warning(
                                "confirmation draft failed: %s %s",
                                app_row.name, email_result.get("error"),
                            )
                        elif not email_result.get("marked"):
                            logging.getLogger(__name__).warning(
                                "table mark failed after draft created: %s %s",
                                app_row.name, email_result.get("mark_error"),
                            )
                    except Exception as exc:  # noqa: BLE001
                        email_result = {"drafted": False, "error": str(exc)}
                        logging.getLogger(__name__).warning("confirmation draft error: %s", exc)
                    finally:
                        if email_result.get("drafted"):
                            from datetime import datetime as _dt

                            detail = dict(app_row.screening_detail or {})
                            detail["last_draft_at"] = _dt.now().isoformat(timespec="seconds")
                            app_row.screening_detail = detail
                            session.commit()
        # 自动评估：资格筛过（eligible/scored）即自动发起后台评分 agent，
        # 不等人工点「开始评估」。材料不齐/不合格的档跳过；失败可人工重发。
        auto_eval_id = None
        if screen_result.get("status") in ("eligible", "scored"):
            try:
                auto_eval_id = _launch_background_evaluation(app_row.id)
                if auto_eval_id:
                    logging.getLogger(__name__).info(
                        "auto evaluation launched: %s (eval=%s)", app_row.name, auto_eval_id)
            except Exception as exc:  # noqa: BLE001 — 自动评估失败不影响同步
                logging.getLogger(__name__).warning("auto evaluation launch failed: %s", exc)
        return jsonify({
            "ok": True,
            "duplicate": not created,
            "application_id": app_row.id,
            "status": screen_result.get("status"),
            "email_drafted": bool(email_result.get("drafted")),
            "table_marked": bool(email_result.get("marked")),
            "evaluation_started": auto_eval_id is not None,
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

    # ---- 后台评估调度：webhook 自动触发 & 并发评估共用 ----
    # 独立 daemon 线程跑 agent（gunicorn gthread 单进程内，跨档并发天然支持，
    # LLM 信号量 50 封顶限流；同档去重由 evaluate 端点的 running 锁保证）
    def _launch_background_evaluation(app_id: str) -> int | None:
        """发起后台评估，返回 evaluation_id；已有 running（重复触发）返回 None。"""
        import threading as _threading

        from agi_talent_radar.core.db.orm import ScholarshipEvaluationORM as _EvalORM

        with get_session() as session:
            app = session.get(ScholarshipApplicationORM, app_id)
            if not app:
                return None
            if app.status not in ("eligible", "scored", "finalized"):
                return None
            running = (
                session.query(_EvalORM)
                .filter_by(application_id=app_id, status="running")
                .first()
            )
            if running is not None:
                return None
            evaluation = _EvalORM(application_id=app_id, config_version="", status="running")
            session.add(evaluation)
            session.commit()
            eval_id = evaluation.id

        def _bg_worker() -> None:
            from agi_talent_radar.scholarship.scorer_agent import run_scorer_agent

            try:
                with get_session() as session:
                    app = session.get(ScholarshipApplicationORM, app_id)
                    evaluation = session.get(_EvalORM, eval_id)
                    run_scorer_agent(session, app, evaluation, lambda t, p: None)
            except Exception:  # noqa: BLE001
                logging.getLogger(__name__).exception("后台评分失败 eval=%s", eval_id)
                try:
                    with get_session() as session:
                        evaluation = session.get(_EvalORM, eval_id)
                        evaluation.status = "failed"
                        evaluation.error_message = "后台评估线程异常"
                        session.commit()
                except Exception:  # noqa: BLE001
                    pass

        _threading.Thread(target=_bg_worker, daemon=True).start()
        return eval_id

    @bp.post("/api/scholarship/applications/<app_id>/evaluate")
    def evaluate(app_id: str):
        """评分 ReAct agent 的 SSE 事件流：tool_start/tool_end/final/done。"""
        from flask import Response, stream_with_context

        from agi_talent_radar.core.db.orm import ScholarshipEvaluationORM

        with get_session() as session:
            app = session.get(ScholarshipApplicationORM, app_id)
            if not app:
                return jsonify({"detail": "申请人不存在"}), 404
            if app.status not in ("eligible", "scored", "finalized"):
                return jsonify({"detail": "请先通过资格与材料筛选再评估"}), 409
            # 防重复锁：同档已有 running 评估（进程内线程在跑）时拒绝，防止并行双跑+重复扣费
            from agi_talent_radar.core.db.orm import ScholarshipEvaluationORM as _EvalORM

            running = (
                session.query(_EvalORM)
                .filter_by(application_id=app.id, status="running")
                .first()
            )
            if running is not None:
                return jsonify({"detail": "该申请人已有评估正在进行中，请等待完成后再发起"}), 409
            evaluation = ScholarshipEvaluationORM(
                application_id=app.id, config_version="", status="running"
            )
            session.add(evaluation)
            session.commit()
            eval_id = evaluation.id

        import queue
        import threading

        events: queue.Queue = queue.Queue()

        def emit(type_: str, payload: dict) -> None:
            events.put({"type": type_, "payload": payload})

        def worker() -> None:
            from agi_talent_radar.scholarship.scorer_agent import run_scorer_agent

            try:
                with get_session() as session:
                    app = session.get(ScholarshipApplicationORM, app_id)
                    evaluation = session.get(ScholarshipEvaluationORM, eval_id)
                    run_scorer_agent(session, app, evaluation, emit)
            except Exception as exc:  # noqa: BLE001
                logging.getLogger(__name__).exception("评分 agent worker 失败")
                emit("error", {"message": str(exc)[:200]})
            finally:
                events.put(None)

        threading.Thread(target=worker, daemon=True).start()

        def generate():
            while True:
                item = events.get()
                if item is None:
                    break
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
            # 结束时给前端最新评估快照（分数/维度/trace 已落库）
            with get_session() as session:
                evaluation = session.get(ScholarshipEvaluationORM, eval_id)
                payload = _eval_to_dict(evaluation)
            yield f"data: {json.dumps({'type': 'done', 'payload': payload}, ensure_ascii=False)}\n\n"

        return Response(stream_with_context(generate()), mimetype="text/event-stream")

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
        # 路径必须落在材料存储根内（防穿越；基准与落盘同源，不随 release 切换漂移）
        material_root = ingest.material_dir()
        if os.path.commonpath([os.path.abspath(path), material_root]) != material_root:
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

    # 视觉 API 拉取视频用的公网素材端点：凭 SCHOLARSHIP_WEBHOOK_TOKEN 自证
    # （同 webhook 的鉴权模型：URL 内随机 token；限视频/图片扩展名）
    @bp.get("/api/scholarship/materials-file/<path:name>")
    def materials_file_public(name: str):
        from flask import send_file

        allowed = {".mp4", ".webm", ".mov", ".mkv", ".png", ".jpg", ".jpeg", ".webp"}
        token = request.args.get("token", "")
        expected = os.getenv("SCHOLARSHIP_WEBHOOK_TOKEN", "").strip()
        ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if not expected or not secrets.compare_digest(token, expected) or ext not in allowed:
            return jsonify({"detail": "无效的素材访问 token"}), 404
        base_dir = ingest.material_dir()
        path = os.path.abspath(os.path.join(base_dir, os.path.basename(name)))
        if not path.startswith(base_dir + os.sep) or not os.path.isfile(path):
            return jsonify({"detail": "文件不存在"}), 404
        return send_file(path, mimetype="application/octet-stream")

    return bp
