from __future__ import annotations

import json
import os
import tempfile
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from queue import Queue
from threading import Lock, Thread
from typing import Any

import logging

from werkzeug.exceptions import HTTPException

from flask import Flask, Response, jsonify, render_template, request, stream_with_context

logger = logging.getLogger(__name__)

from agi_talent_radar.core.import_agent import run_import_agent_stream
from agi_talent_radar.core.education import top_school_names
from agi_talent_radar.core.io import load_resumes
from agi_talent_radar.core.models import CandidateEvaluation, CandidateResume
from agi_talent_radar.core.resume_ingestion import (
    MAX_PDF_BYTES,
    extract_image_text,
    extract_pdf_text,
    text_resume,
)
from agi_talent_radar.core.runner import run_candidate_stream
from agi_talent_radar.core.scoring_config import DEFAULT as SCORING_CONFIG
from agi_talent_radar.web.spa_assets import list_dist_assets as _list_dist_assets


ROOT = Path(__file__).resolve().parents[2]
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
VALID_IMPORT_SUFFIXES = {".pdf", ".jsonl", ".md", ".txt"} | IMAGE_SUFFIXES
MAX_BATCH_FILES = 50
MAX_BATCH_BYTES = 200 * 1024 * 1024
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
MAX_PARALLEL_IMPORTS = max(1, min(5, int(os.getenv("IMPORT_CONCURRENCY", "5"))))
_IMPORT_IDENTITY_LOCK = Lock()
_EVALUATION_START_LOCK = Lock()
_ACTIVE_EVALUATIONS_LOCK = Lock()
_ACTIVE_EVALUATIONS: set[int] = set()


class ImportFileError(ValueError):
    def __init__(self, stage: str, message: str):
        super().__init__(message)
        self.stage = stage


def _set_evaluation_active(evaluation_id: int, active: bool) -> None:
    with _ACTIVE_EVALUATIONS_LOCK:
        if active:
            _ACTIVE_EVALUATIONS.add(evaluation_id)
        else:
            _ACTIVE_EVALUATIONS.discard(evaluation_id)


def _is_evaluation_active(evaluation_id: int) -> bool:
    with _ACTIVE_EVALUATIONS_LOCK:
        return evaluation_id in _ACTIVE_EVALUATIONS


def _start_background_evaluation(session, candidate_orm) -> None:
    """启动后台评估线程（不走 SSE，供批量评估调用）。

    复用 evaluate_candidate 的核心逻辑：校验门禁 → start_evaluation_run → daemon Thread。
    调用方负责传入已 attach 到 session 的 candidate_orm。
    """
    from agi_talent_radar.core.database import (
        get_latest_evaluation_run,
        start_evaluation_run,
        fail_evaluation_run,
    )

    latest_run = get_latest_evaluation_run(session, candidate_orm.id)
    if latest_run and latest_run.status == "running":
        if _is_evaluation_active(latest_run.id):
            raise RuntimeError("该候选人的评估正在运行")
        fail_evaluation_run(session, latest_run.id, "服务重启后原评估任务已中断。")

    # 已软移出（dismissed）的候选人被重新评估时回到队列
    if getattr(candidate_orm, "group", "") == "dismissed":
        candidate_orm.group = "pending"
        session.commit()

    resume = _orm_to_resume(candidate_orm)
    academic_report = _evaluation_academic_report(candidate_orm)
    evaluation_run = start_evaluation_run(session, candidate_orm.id)
    evaluation_run_id = evaluation_run.id

    event_queue: Queue = Queue()
    _set_evaluation_active(evaluation_run_id, True)
    worker = Thread(
        target=_run_evaluation_job,
        args=(candidate_orm.id, evaluation_run_id, resume, academic_report, event_queue),
        name=f"evaluation-{evaluation_run_id}",
        daemon=True,
    )
    worker.start()


def _run_evaluation_job(
    candidate_id: str,
    evaluation_run_id: int,
    resume: CandidateResume,
    academic_report: dict[str, Any],
    event_queue: Queue,
) -> None:
    """Run an evaluation independently from the browser's SSE connection."""
    evaluation = None
    try:
        for event in run_candidate_stream(resume, academic_report=academic_report):
            if event["type"] == "node":
                from agi_talent_radar.core.database import get_session, record_node_event

                with get_session() as session:
                    record_node_event(session, evaluation_run_id, event)
                event_queue.put(event)
            elif event["type"] == "result":
                evaluation = CandidateEvaluation.model_validate(event["result"])
                evaluation.id = candidate_id
            else:
                event_queue.put(event)

        if evaluation is None:
            raise RuntimeError("评估流程未返回结果。")

        from agi_talent_radar.core.database import get_session, save_evaluation

        with get_session() as session:
            save_evaluation(session, evaluation, evaluation_id=evaluation_run_id)

        try:
            from agi_talent_radar.services import talent_service

            talent_service.admit_candidate_after_evaluation(evaluation_run_id)
        except (ValueError, RuntimeError):
            pass

        event_queue.put({"type": "result", "result": evaluation.model_dump()})
    except Exception as exc:
        from agi_talent_radar.core.database import fail_evaluation_run, get_session

        with get_session() as session:
            fail_evaluation_run(session, evaluation_run_id, exc)
        event_queue.put({"type": "error", "message": str(exc)})
    finally:
        _set_evaluation_active(evaluation_run_id, False)
        event_queue.put(None)


def _has_structure(resume: CandidateResume) -> bool:
    """判断 resume 是否已有结构化字段（非纯 raw_text）。"""
    return any([
        resume.name, resume.target_role, resume.stage,
        resume.education, resume.directions, resume.experiences,
        resume.projects, resume.publications, resume.skills,
    ])


def _sync_person_vectors_best_effort(person_id: str | None) -> None:
    """导入即入库后把人物写入问答向量库；失败只记日志，不影响导入流程。"""
    if not person_id:
        return
    try:
        from agi_talent_radar.core.database import get_session
        from agi_talent_radar.core.vector_store import QdrantVectorStore
        from agi_talent_radar.knowledge_agent.vector_sync import sync_person_vectors

        with get_session() as session:
            sync_person_vectors(session, person_id, QdrantVectorStore())
    except Exception:
        logger.warning("person %s 导入后向量同步失败，等待后续重试", person_id, exc_info=True)


def create_app() -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config["JSON_AS_ASCII"] = False

    # 阶段 8：鉴权 + 配置蓝图接入。
    # 未配置 APP_AUTH_PASSWORD 时鉴权 fail-closed，本地开发需显式设置。
    from agi_talent_radar.web.auth import (
        build_auth_blueprint,
        configure_app_session,
        install_auth_middleware,
    )
    from agi_talent_radar.web.config_api import build_config_blueprint
    from agi_talent_radar.web.knowledge_api import build_knowledge_blueprint
    from agi_talent_radar.web.interview_assessment_api import build_interview_assessment_blueprint
    from agi_talent_radar.scholarship.api import build_scholarship_blueprint
    from agi_talent_radar.grill.api import build_grill_blueprint

    configure_app_session(app)

    # 统一 500 兜底：不外泄异常文本（traceback/内部路径），只记日志 + 返回稳定 detail。
    # 400/404 保持各路由自带的明确文案；这里只兜未捕获异常。
    import logging

    _logger = logging.getLogger(__name__)

    @app.errorhandler(Exception)
    def handle_uncaught(exc):
        if isinstance(exc, HTTPException):
            return jsonify({"detail": exc.description}), exc.code
        _logger.exception("unhandled error")
        return jsonify({"detail": "服务器内部错误，请稍后重试"}), 500

    app.register_blueprint(build_auth_blueprint())
    app.register_blueprint(build_config_blueprint())
    app.register_blueprint(build_knowledge_blueprint())
    app.register_blueprint(build_interview_assessment_blueprint())
    app.register_blueprint(build_scholarship_blueprint())
    app.register_blueprint(build_grill_blueprint())
    install_auth_middleware(app)

    # SPA 页面路由：所有前端页面统一返回 React SPA shell。
    # React Router 接管 / /knowledge /talent-pool /review /settings。
    import os
    from pathlib import Path

    dist_dir = Path(app.static_folder) / "dist"
    vite_dev = os.getenv("VITE_DEV", "").strip() == "1"

    def render_spa() -> str:
        assets = [] if vite_dev else _list_dist_assets(dist_dir)
        return render_template("index.html", vite_dev=vite_dev, dist_assets=assets)

    @app.get("/")
    def index() -> str:
        return render_spa()

    @app.get("/knowledge")
    @app.get("/talent-pool")
    @app.get("/talent-pool/<path:person_path>")
    @app.get("/review")
    @app.get("/settings")
    @app.get("/resume-evaluate")
    @app.get("/interview-admission")
    def spa_pages() -> str:
        return render_spa()

    @app.get("/api/candidates")
    def list_candidates():
        """统一人才目录：已入库或拥有准入报告的候选人（docs/rebuild.md §2.1）。

        队列语义已移除：导入即入库，与人才库列表同源，不再按保留期/软移出过滤。
        """
        try:
            from agi_talent_radar.core.database import get_session
            from agi_talent_radar.core.db.repository import list_evaluation_directory_rows

            with get_session() as session:
                rows = list_evaluation_directory_rows(session)
                briefs = []
                for row in rows:
                    brief = _orm_to_brief(row)
                    # 姓名为空返回空串，前端显示"未命名"，不回退内部 ID（rebuild.md §5.3）
                    brief["name"] = row.name or ""
                    briefs.append(brief)
            return jsonify(briefs)
        except Exception as exc:
            return jsonify([]), 500

    @app.get("/api/candidates/<candidate_id>")
    def get_candidate(candidate_id: str):
        try:
            from agi_talent_radar.core.database import (
                evaluation_run_to_dict,
                fail_evaluation_run,
                get_candidate_with_latest_evaluation,
                get_latest_evaluation_run,
                get_session,
            )

            with get_session() as session:
                candidate_orm, evaluation = get_candidate_with_latest_evaluation(session, candidate_id)
                if not candidate_orm:
                    return jsonify({"detail": "候选人不存在"}), 404
                latest_run = get_latest_evaluation_run(session, candidate_id)
                if (
                    latest_run
                    and latest_run.status == "running"
                    and not _is_evaluation_active(latest_run.id)
                ):
                    fail_evaluation_run(session, latest_run.id, "服务重启或连接恢复时发现评估任务已中断。")
                    session.refresh(latest_run)
                data = _orm_to_detail(candidate_orm)
                if evaluation:
                    data["evaluation"] = _orm_to_evaluation(evaluation)
                    data["latest_evaluation"] = data["evaluation"]
                if latest_run is not None and getattr(latest_run, "status", None) in {"running", "completed", "failed"}:
                    data["evaluation_run"] = evaluation_run_to_dict(latest_run)
                return jsonify(data)
        except Exception as exc:
            logger.exception("route error in workbench"); return jsonify({"detail": "服务器内部错误，请稍后重试"}), 500

    @app.post("/api/candidates/<candidate_id>/evaluate")
    def evaluate_candidate(candidate_id: str):
        try:
            from agi_talent_radar.core.database import (
                fail_evaluation_run,
                get_candidate_with_latest_evaluation,
                get_latest_evaluation_run,
                get_session,
                start_evaluation_run,
            )

            with _EVALUATION_START_LOCK:
                with get_session() as session:
                    candidate_orm, _ = get_candidate_with_latest_evaluation(session, candidate_id)
                    if not candidate_orm:
                        return jsonify({"detail": "候选人不存在"}), 404
                    latest_run = get_latest_evaluation_run(session, candidate_id)
                    if latest_run and latest_run.status == "running":
                        if _is_evaluation_active(latest_run.id):
                            return jsonify({
                                "detail": "该候选人的评估正在后台运行。",
                                "evaluation_id": latest_run.id,
                            }), 409
                        fail_evaluation_run(session, latest_run.id, "服务重启后原评估任务已中断。")

                    resume = _orm_to_resume(candidate_orm)
                    academic_report = _evaluation_academic_report(candidate_orm)
                    evaluation_run = start_evaluation_run(session, candidate_id)
                    evaluation_run_id = evaluation_run.id

                event_queue: Queue = Queue()
                _set_evaluation_active(evaluation_run_id, True)
                worker = Thread(
                    target=_run_evaluation_job,
                    args=(candidate_id, evaluation_run_id, resume, academic_report, event_queue),
                    name=f"evaluation-{evaluation_run_id}",
                    daemon=True,
                )
                worker.start()
        except Exception as exc:
            return jsonify({"detail": f"读取候选人失败: {exc}"}), 500

        def generate():
            yield f"data: {json.dumps({'type': 'started', 'evaluation_id': evaluation_run_id}, ensure_ascii=False)}\n\n"
            while True:
                event = event_queue.get()
                if event is None:
                    break
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        response = Response(stream_with_context(generate()), mimetype="text/event-stream")
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["X-Accel-Buffering"] = "no"
        return response

    @app.patch("/api/candidates/<candidate_id>/supplementary")
    def update_supplementary_info(candidate_id: str):
        """保存 HR 手动补充的信息（简历上没有的），评估时并入输入。"""
        body = request.get_json(silent=True) or {}
        content = str(body.get("content", ""))[:4000]
        try:
            from agi_talent_radar.core.database import get_session
            from agi_talent_radar.core.db.orm import CandidateJdAssessmentORM, CandidateORM
            from agi_talent_radar.services.interview_assessment_service import assert_candidate_editable

            with get_session() as session:
                candidate = session.get(CandidateORM, candidate_id)
                if not candidate:
                    return jsonify({"detail": "候选人不存在"}), 404
                assert_candidate_editable(session, candidate_id)
                candidate.supplementary_info = content
                session.query(CandidateJdAssessmentORM).filter_by(candidate_id=candidate_id, is_valid=True).update(
                    {
                        CandidateJdAssessmentORM.is_valid: False,
                        CandidateJdAssessmentORM.invalid_reason: "候选人补充信息已更新",
                    },
                    synchronize_session=False,
                )
                session.commit()
                return jsonify({"id": candidate_id, "supplementary_info": candidate.supplementary_info})
        except RuntimeError as exc:
            return jsonify({"detail": str(exc)}), 409
        except Exception as exc:
            logger.exception("route error in workbench"); return jsonify({"detail": "服务器内部错误，请稍后重试"}), 500

    @app.post("/api/candidates/<candidate_id>/publications/<int:alignment_index>/review")
    def review_publication(candidate_id: str, alignment_index: int):
        """人工裁决论文自述：unverifiable 可确认/驳回；mismatch 可由 HR 平反（confirmed）。"""
        body = request.get_json(silent=True) or {}
        action = str(body.get("action", "")).strip()
        reviewer = str(body.get("reviewer", "")).strip()
        note = str(body.get("note", "")).strip()
        if action not in {"confirmed", "dismissed"}:
            return jsonify({"detail": "action 必须是 confirmed 或 dismissed"}), 400
        if not reviewer:
            return jsonify({"detail": "reviewer 不能为空"}), 400

        try:
            from agi_talent_radar.core.db.orm import CandidateORM
            from agi_talent_radar.core.db.runtime import get_session

            with get_session() as session:
                candidate = session.get(CandidateORM, candidate_id)
                if not candidate:
                    return jsonify({"detail": "候选人不存在"}), 404
                if getattr(candidate, "academic_check_status", "none") != "done":
                    return jsonify({"detail": "论文机器核验尚未完成"}), 409

                report = deepcopy(_load_json(getattr(candidate, "academic_report", "")) or {})
                alignments = report.get("alignments", [])
                if alignment_index < 0 or alignment_index >= len(alignments):
                    return jsonify({"detail": "论文核验项不存在"}), 404
                alignment = alignments[alignment_index]
                # HR 可裁决任意论文的核验结论（verified/mismatch/unverifiable 均可），
                # 语义改为"判 AI 核验结论对不对"，不限 verdict 状态。

                alignment.update({
                    "human_status": action,
                    "human_reviewer": reviewer,
                    "human_note": note,
                    "human_reviewed_at": datetime.now(timezone.utc).isoformat(),
                })
                candidate.academic_report = report
                session.commit()

                return jsonify({
                    "candidate_id": candidate_id,
                    "alignment_index": alignment_index,
                    "human_status": action,
                    "verification_result": _verification_result(candidate),
                    "evaluable": _is_evaluable(candidate),
                })
        except Exception as exc:
            logger.exception("route error in workbench"); return jsonify({"detail": "服务器内部错误，请稍后重试"}), 500

    @app.get("/api/candidates/<candidate_id>/pdf")
    def get_candidate_pdf(candidate_id: str):
        """流式返回候选人原始简历文件（PDF/图片/MD/TXT 等按实际后缀）。
        历史数据无原件时返回 404，前端回退到 raw_text。"""
        from flask import send_from_directory

        from agi_talent_radar.core.pdf_storage import _ROOT, get_resume_original_path

        try:
            original_path = get_resume_original_path(candidate_id)
            if original_path is None:
                return jsonify({"detail": "该候选人无原始简历文件（可能是历史数据）"}), 404
            mimetype = {
                ".pdf": "application/pdf",
                ".png": "image/png",
                ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".webp": "image/webp",
                ".md": "text/markdown", ".txt": "text/plain",
                ".jsonl": "application/jsonl",
            }.get(original_path.suffix.lower(), "application/octet-stream")
            return send_from_directory(_ROOT, original_path.name, mimetype=mimetype)
        except Exception as exc:
            logger.exception("route error in workbench"); return jsonify({"detail": "服务器内部错误，请稍后重试"}), 500

    @app.patch("/api/candidates/<candidate_id>/engagement-status")
    def update_engagement_status(candidate_id: str):
        """阶段 1：人工修改 HR 跟进状态。强制 changed_by。"""
        body = request.get_json(silent=True) or {}
        status = body.get("status")
        changed_by = body.get("changed_by", "")
        note = body.get("note", "")
        try:
            from agi_talent_radar.services import talent_service

            result = talent_service.update_engagement_status(
                candidate_id=candidate_id,
                status=status,
                changed_by=changed_by,
                note=note,
            )
            return jsonify(result.model_dump(mode="json"))
        except ValueError as exc:
            return jsonify({"detail": str(exc)}), 400
        except Exception as exc:
            logger.exception("route error in workbench"); return jsonify({"detail": "服务器内部错误，请稍后重试"}), 500

    @app.get("/api/candidates/<candidate_id>/engagement-history")
    def list_engagement_history(candidate_id: str):
        """返回 HR 跟进状态变更的不可变审计记录。"""
        try:
            from agi_talent_radar.core.database import get_session
            from agi_talent_radar.core.db.repository import list_engagement_history

            with get_session() as session:
                history = list_engagement_history(session, candidate_id)
                return jsonify([
                    {
                        "previous_status": h.previous_status,
                        "current_status": h.current_status,
                        "changed_by": h.changed_by,
                        "note": h.note,
                        "changed_at": h.created_at.isoformat() if h.created_at else None,
                    }
                    for h in history
                ])
        except Exception as exc:
            logger.exception("route error in workbench"); return jsonify({"detail": "服务器内部错误，请稍后重试"}), 500

    @app.post("/api/persons/<person_id>/admit")
    def admit_person_to_pool(person_id: str):
        """阶段 1：HR 显式把已知人物加入人才库。"""
        body = request.get_json(silent=True) or {}
        changed_by = body.get("changed_by", "")
        note = body.get("note", "")
        try:
            from agi_talent_radar.services import talent_service

            result = talent_service.manual_admit_person_to_pool(
                person_id=person_id,
                changed_by=changed_by,
                note=note,
            )
            return jsonify(result)
        except ValueError as exc:
            return jsonify({"detail": str(exc)}), 400
        except Exception as exc:
            logger.exception("route error in workbench"); return jsonify({"detail": "服务器内部错误，请稍后重试"}), 500

    @app.post("/api/persons")
    def create_person_view():
        """HR 手动把人物加入人才库：固定 guest 类型，不参与 Track 分类。"""
        body = request.get_json(silent=True) or {}
        name = (body.get("name") or "").strip()
        if not name:
            return jsonify({"detail": "姓名必填"}), 400
        try:
            from agi_talent_radar.core.database import get_session
            from agi_talent_radar.core.persons import get_or_create_person

            with get_session() as session:
                person = get_or_create_person(
                    session,
                    name=name,
                    org=(body.get("org") or "").strip(),
                    direction=(body.get("direction") or "").strip(),
                    person_type="guest",
                )
                session.commit()
                return jsonify(_person_to_brief(person)), 201
        except Exception as exc:
            logger.exception("route error in workbench"); return jsonify({"detail": "服务器内部错误，请稍后重试"}), 500

    @app.get("/api/persons")
    def list_persons_view():
        person_type = request.args.get("person_type", "")
        name = request.args.get("name", "")
        q = request.args.get("q", "")
        level = request.args.get("level", "")
        group_id = request.args.get("group_id", "")
        try:
            from agi_talent_radar.core.database import get_session, list_persons
            from agi_talent_radar.core.db.repository import find_candidate_by_person

            with get_session() as session:
                rows = list_persons(session, person_type=person_type, name=name, q=q, level=level, group_id=group_id)
                # person→candidate 映射一次批量查，替代逐人 find_candidate_by_person 的 N+1
                candidate_map = {}
                if rows:
                    from agi_talent_radar.core.db.orm import CandidateORM

                    for c in (
                        session.query(CandidateORM)
                        .filter(CandidateORM.person_id.in_([r.id for r in rows]))
                        .all()
                    ):
                        candidate_map[c.person_id] = c
                return jsonify([
                    _person_to_brief(row, candidate_map.get(row.id))
                    for row in rows
                ])
        except Exception as exc:
            logger.exception("route error in workbench"); return jsonify({"detail": "服务器内部错误，请稍后重试"}), 500

    @app.get("/api/persons/<person_id>")
    def get_person_view(person_id: str):
        try:
            from agi_talent_radar.core.database import get_person_detail, get_session
            from agi_talent_radar.core.db.repository import find_candidate_by_person

            with get_session() as session:
                person = get_person_detail(session, person_id)
                if not person:
                    return jsonify({"detail": "人员不存在"}), 404
                candidate = find_candidate_by_person(session, person.id)
                return jsonify(_person_to_detail(person, candidate))
        except Exception as exc:
            logger.exception("route error in workbench"); return jsonify({"detail": "服务器内部错误，请稍后重试"}), 500

    # ---- 人才档案只读分享（v1：token 链接） ----

    @app.get("/share/<token>")
    def share_page(token: str):
        """只读分享页（React 路由接管，token 由前端调公开 API 校验）。"""
        return render_spa()

    @app.post("/api/persons/<person_id>/share")
    def create_person_share(person_id: str):
        """生成（或复用未过期未吊销的）只读分享令牌，返回完整 URL 路径。"""
        import secrets
        from datetime import datetime, timedelta

        from agi_talent_radar.core.database import get_person_detail, get_session
        from agi_talent_radar.core.db.orm import ShareTokenORM

        try:
            with get_session() as session:
                if not get_person_detail(session, person_id):
                    return jsonify({"detail": "人员不存在"}), 404
                existing = (
                    session.query(ShareTokenORM)
                    .filter(
                        ShareTokenORM.person_id == person_id,
                        ShareTokenORM.revoked.is_(False),
                    )
                    .order_by(ShareTokenORM.created_at.desc())
                    .first()
                )
                if existing is not None:
                    token = existing.token
                else:
                    token = secrets.token_urlsafe(32)
                    session.add(
                        ShareTokenORM(
                            token=token,
                            person_id=person_id,
                            created_by=(current_user_display_name() or "web"),
                            expires_at=datetime.utcnow() + timedelta(days=30),
                        )
                    )
                    session.commit()
                return jsonify({"share_path": f"/share/{token}", "token": token})
        except Exception as exc:
            logger.exception("route error in workbench"); return jsonify({"detail": "服务器内部错误，请稍后重试"}), 500

    @app.delete("/api/persons/<person_id>/share")
    def revoke_person_share(person_id: str):
        from agi_talent_radar.core.database import get_session
        from agi_talent_radar.core.db.orm import ShareTokenORM

        try:
            with get_session() as session:
                session.query(ShareTokenORM).filter(ShareTokenORM.person_id == person_id).update(
                    {"revoked": True}
                )
                session.commit()
            return jsonify({"revoked": True})
        except Exception as exc:
            logger.exception("route error in workbench"); return jsonify({"detail": "服务器内部错误，请稍后重试"}), 500

    @app.get("/api/share/<token>")
    def get_shared_person(token: str):
        """公开只读：凭 token 返回该 person 完整档案（含评估历史）。不含任何他人数据。"""
        from datetime import datetime

        from agi_talent_radar.core.database import get_person_detail, get_session
        from agi_talent_radar.core.db.orm import ShareTokenORM
        from agi_talent_radar.core.db.repository import find_candidate_by_person

        try:
            with get_session() as session:
                row = session.query(ShareTokenORM).filter_by(token=token).first()
                if row is None or row.revoked:
                    return jsonify({"detail": "链接无效或已被撤销"}), 404
                if row.expires_at is not None and row.expires_at < datetime.utcnow():
                    return jsonify({"detail": "链接已过期"}), 404
                person = get_person_detail(session, row.person_id)
                if person is None:
                    return jsonify({"detail": "人员不存在"}), 404
                candidate = find_candidate_by_person(session, person.id)
                data = _person_to_detail(person, candidate)
                return jsonify(data)
        except Exception as exc:
            logger.exception("route error in workbench"); return jsonify({"detail": "服务器内部错误，请稍后重试"}), 500

    @app.get("/api/persons/<person_id>/resume")
    def get_person_resume_view(person_id: str):
        """按 person 取关联候选人完整详情（滑轨对比卡数据源）。

        与评估页 /api/candidates/:id 同构：detail + 最新 evaluation + evaluation_run，
        保证滑轨卡四个 tab 与评估页/完整档案页数据完全一致。
        """
        try:
            from agi_talent_radar.core.database import (
                evaluation_run_to_dict,
                get_candidate_with_latest_evaluation,
                get_latest_evaluation_run,
                get_session,
            )
            from agi_talent_radar.core.db.repository import find_candidate_by_person

            with get_session() as session:
                candidate = find_candidate_by_person(session, person_id)
                if candidate is None:
                    return jsonify({"detail": "该人员没有关联简历档案"}), 404
                data = _orm_to_detail(candidate)
                _, evaluation = get_candidate_with_latest_evaluation(session, candidate.id)
                if evaluation:
                    data["evaluation"] = _orm_to_evaluation(evaluation)
                    data["latest_evaluation"] = data["evaluation"]
                latest_run = get_latest_evaluation_run(session, candidate.id)
                if latest_run is not None and getattr(latest_run, "status", None) in {"running", "completed", "failed"}:
                    data["evaluation_run"] = evaluation_run_to_dict(latest_run)
                return jsonify(data)
        except Exception as exc:
            logger.exception("route error in workbench"); return jsonify({"detail": "服务器内部错误，请稍后重试"}), 500

    @app.get("/api/persons/<person_id>/resume-versions")
    def list_resume_versions_view(person_id: str):
        """返回某人物的所有简历版本（每次导入一条），供前端对比。"""
        try:
            from agi_talent_radar.core.database import get_session
            from agi_talent_radar.core.db.repository import list_person_resume_versions

            with get_session() as session:
                return jsonify(list_person_resume_versions(session, person_id))
        except Exception as exc:
            logger.exception("route error in workbench"); return jsonify({"detail": "服务器内部错误，请稍后重试"}), 500

    @app.get("/api/persons/<person_id>/reputation")
    def list_person_reputation(person_id: str):
        try:
            from agi_talent_radar.core.database import PersonORM, get_session

            with get_session() as session:
                person = session.get(PersonORM, person_id)
                if not person:
                    return jsonify({"detail": "人员不存在"}), 404
                reports = sorted(person.reputation_reports, key=lambda r: r.created_at, reverse=True)
                return jsonify([_reputation_report_to_dict(r) for r in reports])
        except Exception as exc:
            logger.exception("route error in workbench"); return jsonify({"detail": "服务器内部错误，请稍后重试"}), 500

    @app.delete("/api/persons/<person_id>")
    def delete_person(person_id: str):
        try:
            from agi_talent_radar.core.db.repository import delete_person as _delete_person
            from agi_talent_radar.core.db.runtime import get_session

            with get_session() as session:
                deleted = _delete_person(session, person_id)
                if not deleted:
                    return jsonify({"detail": "人员不存在"}), 404
                try:
                    from agi_talent_radar.core.vector_store import QdrantVectorStore
                    from agi_talent_radar.knowledge_agent.vector_sync import delete_person_vectors

                    delete_person_vectors(person_id, QdrantVectorStore())
                except Exception:
                    pass
                return jsonify({"id": person_id, "deleted": True})
        except Exception as exc:
            logger.exception("route error in workbench"); return jsonify({"detail": "服务器内部错误，请稍后重试"}), 500

    # ---- 人才库分组（手工分类，一对多，全局共享）----

    @app.get("/api/talent-groups")
    def list_talent_groups():
        from agi_talent_radar.core.persons import count_persons_by_group, list_talent_groups as _list
        from agi_talent_radar.core.db.runtime import get_session

        with get_session() as session:
            groups = _list(session)
            return jsonify([
                {
                    "id": g.id,
                    "name": g.name,
                    "sort_order": g.sort_order,
                    "count": count_persons_by_group(session, g.id),
                }
                for g in groups
            ])

    @app.post("/api/talent-groups")
    def create_talent_group():
        from agi_talent_radar.core.db.orm import TalentGroupORM
        from agi_talent_radar.core.db.runtime import get_session
        from agi_talent_radar.core.persons import list_talent_groups

        body = request.get_json(silent=True) or {}
        name = str(body.get("name", "")).strip()
        if not name:
            return jsonify({"detail": "name 不能为空"}), 400
        with get_session() as session:
            max_order = max((g.sort_order for g in list_talent_groups(session)), default=-1)
            group = TalentGroupORM(name=name[:64], sort_order=max_order + 1)
            session.add(group)
            session.commit()
            return jsonify({"id": group.id, "name": group.name, "sort_order": group.sort_order, "count": 0}), 201

    @app.patch("/api/talent-groups/<group_id>")
    def rename_talent_group(group_id: str):
        from agi_talent_radar.core.db.orm import TalentGroupORM
        from agi_talent_radar.core.db.runtime import get_session

        body = request.get_json(silent=True) or {}
        name = str(body.get("name", "")).strip()
        if not name:
            return jsonify({"detail": "name 不能为空"}), 400
        with get_session() as session:
            group = session.get(TalentGroupORM, group_id)
            if group is None:
                return jsonify({"detail": "分组不存在"}), 404
            group.name = name[:64]
            session.commit()
            return jsonify({"id": group.id, "name": group.name, "sort_order": group.sort_order})

    @app.delete("/api/talent-groups/<group_id>")
    def delete_talent_group(group_id: str):
        from agi_talent_radar.core.db.orm import PersonORM, TalentGroupORM
        from agi_talent_radar.core.db.runtime import get_session

        with get_session() as session:
            group = session.get(TalentGroupORM, group_id)
            if group is None:
                return jsonify({"detail": "分组不存在"}), 404
            # 删除前把该分组的人退回未分组（FK ondelete SET NULL 也兜底）
            session.query(PersonORM).filter_by(group_id=group_id).update(
                {PersonORM.group_id: None}, synchronize_session=False
            )
            session.delete(group)
            session.commit()
            return jsonify({"id": group_id, "deleted": True})

    # ---- JD 池：JD 原文管理 + track spec 起草/激活（驱动动态 track 评估）----

    @app.get("/api/jds")
    def list_jds_view():
        from agi_talent_radar.core.db.repository import jd_to_dict, list_jds
        from agi_talent_radar.core.db.runtime import get_session

        with get_session() as session:
            return jsonify([jd_to_dict(row) for row in list_jds(session)])

    @app.post("/api/jds")
    def create_jd_view():
        from agi_talent_radar.agents.interview_admission import generate_assessment_card
        from agi_talent_radar.core.db.repository import create_jd, jd_to_dict, replace_jd_assessment_card
        from agi_talent_radar.core.db.runtime import get_session

        body = request.get_json(silent=True) or {}
        title = str(body.get("title", "")).strip()
        raw_text = str(body.get("raw_text", "")).strip()
        if not title or not raw_text:
            return jsonify({"detail": "title 和 raw_text 不能为空"}), 400
        trace: list[dict[str, Any]] = []
        model_usage: list[dict[str, str]] = []
        try:
            card = generate_assessment_card(
                title[:200],
                str(body.get("team", "")).strip()[:200],
                raw_text,
                [],
                on_event=trace.append,
                on_call=model_usage.append,
            )
        except Exception as exc:
            return jsonify({"detail": f"岗位评估卡生成失败：{exc}"}), 502
        with get_session() as session:
            row = create_jd(session, title[:200], str(body.get("team", "")).strip()[:200], raw_text)
            row = replace_jd_assessment_card(
                session, row.id, [], card.model_dump(), trace, model_usage
            )
            return jsonify(jd_to_dict(row)), 201

    @app.patch("/api/jds/<jd_id>")
    def update_jd_view(jd_id: str):
        from agi_talent_radar.agents.interview_admission import generate_assessment_card
        from agi_talent_radar.core.db.orm import JdEntryORM
        from agi_talent_radar.core.db.repository import jd_to_dict, replace_jd_assessment_card
        from agi_talent_radar.core.db.runtime import get_session
        from agi_talent_radar.services.interview_assessment_service import assert_jd_editable

        body = request.get_json(silent=True) or {}
        title = str(body.get("title", "")).strip()[:200]
        team = str(body.get("team", "")).strip()[:200]
        raw_text = str(body.get("raw_text", "")).strip()
        supplements = body.get("supplements") or []
        if not title or not raw_text or not isinstance(supplements, list):
            return jsonify({"detail": "title、raw_text 不能为空，supplements 必须是数组"}), 400
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
        except Exception as exc:
            return jsonify({"detail": f"岗位评估卡生成失败，原 JD 未修改：{exc}"}), 502
        with get_session() as session:
            try:
                assert_jd_editable(session, jd_id)
            except RuntimeError as exc:
                return jsonify({"detail": str(exc)}), 409
            row = session.get(JdEntryORM, jd_id)
            if row is None:
                return jsonify({"detail": "JD 不存在"}), 404
            row.title = title
            row.team = team
            row.raw_text = raw_text
            row = replace_jd_assessment_card(
                session, jd_id, supplements, card.model_dump(), trace, model_usage
            )
            return jsonify(jd_to_dict(row))

    @app.delete("/api/jds/<jd_id>")
    def delete_jd_view(jd_id: str):
        from agi_talent_radar.core.db.repository import delete_jd
        from agi_talent_radar.core.db.runtime import get_session
        from agi_talent_radar.services.interview_assessment_service import assert_jd_editable

        with get_session() as session:
            try:
                assert_jd_editable(session, jd_id)
            except RuntimeError as exc:
                return jsonify({"detail": str(exc)}), 409
            if not delete_jd(session, jd_id):
                return jsonify({"detail": "JD 不存在"}), 404
            return jsonify({"id": jd_id, "deleted": True})

    @app.post("/api/jds/<jd_id>/generate-spec")
    def generate_jd_spec_view(jd_id: str):
        """旧端点兼容：改为重新生成当前岗位评估卡。"""
        from agi_talent_radar.services.interview_assessment_service import generate_and_store_card
        body = request.get_json(silent=True) or {}
        try:
            return jsonify(generate_and_store_card(jd_id, body.get("supplements") or []))
        except Exception as exc:
            logger.exception("route error in workbench")
            return jsonify({"detail": str(exc)}), 409

    @app.post("/api/jds/<jd_id>/status")
    def set_jd_status_view(jd_id: str):
        from agi_talent_radar.core.db.orm import JdEntryORM
        from agi_talent_radar.core.db.repository import jd_to_dict
        from agi_talent_radar.core.db.runtime import get_session

        body = request.get_json(silent=True) or {}
        status = str(body.get("status", "")).strip()
        if status not in {"draft", "active", "archived"}:
            return jsonify({"detail": "status 必须是 archived 或恢复可见"}), 400
        with get_session() as session:
            row = session.get(JdEntryORM, jd_id)
            if row is None:
                return jsonify({"detail": "JD 不存在"}), 404
            row.archived = status == "archived"
            session.commit()
            session.refresh(row)
            return jsonify(jd_to_dict(row))

    @app.post("/api/jds/parse")
    def parse_jd_view():
        """智能解析粘贴的 JD 全文 → {title, team}，供表单预填。"""
        from agi_talent_radar.agents.jd_spec import parse_jd_brief

        body = request.get_json(silent=True) or {}
        text = str(body.get("text", "")).strip()
        if not text:
            return jsonify({"detail": "text 不能为空"}), 400
        try:
            return jsonify(parse_jd_brief(text))
        except Exception:
            logger.exception("route error in workbench"); return jsonify({"detail": "服务器内部错误，请稍后重试"}), 500

    @app.get("/api/tracks/active")
    def list_active_tracks_view():
        """当前参与准入评估的 JD，兼容旧的 track 筛选接口。"""
        from agi_talent_radar.core.db.repository import list_active_jds
        from agi_talent_radar.core.db.runtime import get_session

        with get_session() as session:
            rows = list_active_jds(session)
            return jsonify([{"key": row.id, "label": row.title} for row in rows])

    @app.post("/api/persons/<person_id>/move")
    def move_person(person_id: str):
        from agi_talent_radar.core.db.runtime import get_session
        from agi_talent_radar.core.persons import move_person_to_group

        body = request.get_json(silent=True) or {}
        group_id = body.get("group_id")  # None = 移到未分组
        with get_session() as session:
            ok = move_person_to_group(session, person_id, group_id)
            if not ok:
                return jsonify({"detail": "人员不存在"}), 404
            return jsonify({"id": person_id, "group_id": group_id})

    @app.post("/api/persons/batch-move")
    def batch_move_persons_view():
        from agi_talent_radar.core.db.runtime import get_session
        from agi_talent_radar.core.persons import batch_move_persons

        body = request.get_json(silent=True) or {}
        person_ids = body.get("person_ids") or []
        group_id = body.get("group_id")  # None = 移到未分组
        if not isinstance(person_ids, list) or not person_ids:
            return jsonify({"detail": "person_ids 不能为空"}), 400
        with get_session() as session:
            n = batch_move_persons(session, person_ids, group_id)
            return jsonify({"moved": n, "group_id": group_id})

    @app.post("/api/persons/batch-evaluate")
    def batch_evaluate_persons():
        """按 person_id 批量启动后台评估（非 SSE，后台跑）。"""
        from agi_talent_radar.core.db.orm import PersonORM
        from agi_talent_radar.core.db.runtime import get_session
        from agi_talent_radar.core.db.repository import find_candidate_by_person

        body = request.get_json(silent=True) or {}
        person_ids = body.get("person_ids") or []
        if not isinstance(person_ids, list) or not person_ids:
            return jsonify({"detail": "person_ids 不能为空"}), 400

        results: list[dict] = []
        for pid in person_ids:
            with get_session() as session:
                person = session.get(PersonORM, pid)
                if not person:
                    results.append({"person_id": pid, "status": "not_found"})
                    continue
                if person.person_type == "guest":
                    results.append({"person_id": pid, "status": "skipped", "reason": "guest"})
                    continue
                candidate = find_candidate_by_person(session, pid)
                if not candidate:
                    results.append({"person_id": pid, "status": "no_candidate"})
                    continue
                # 复用单条评估逻辑（启动后台线程）
                try:
                    _start_background_evaluation(session, candidate)
                    results.append({"person_id": pid, "status": "started", "candidate_id": candidate.id})
                except Exception as exc:
                    results.append({"person_id": pid, "status": "failed", "detail": str(exc)})
        started = sum(1 for r in results if r["status"] == "started")
        return jsonify({"started": started, "total": len(person_ids), "results": results})

    @app.post("/api/reputation/<int:report_id>/review")
    def review_reputation(report_id: int):
        body = request.get_json(silent=True) or {}
        action = body.get("action")
        reviewer = body.get("reviewer", "")
        note = body.get("note", "")
        try:
            from agi_talent_radar.core.database import get_session
            from agi_talent_radar.core.reputation_service import review_reputation_report

            with get_session() as session:
                report = review_reputation_report(session, report_id, action, reviewer=reviewer, note=note)
                if not report:
                    return jsonify({"detail": "舆情报告不存在"}), 404
                return jsonify(_reputation_report_to_dict(report))
        except ValueError as exc:
            return jsonify({"detail": str(exc)}), 400
        except Exception as exc:
            logger.exception("route error in workbench"); return jsonify({"detail": "服务器内部错误，请稍后重试"}), 500

    @app.post("/api/import-file")
    def import_file():
        uploaded_files = request.files.getlist("files")
        if not uploaded_files:
            single_file = request.files.get("file")
            uploaded_files = [single_file] if single_file else []
        uploaded_files = [file for file in uploaded_files if file and file.filename]
        if not uploaded_files:
            return jsonify({"detail": "请上传 .pdf / .jsonl / .md / .txt / .png / .jpg / .jpeg / .webp 简历文件"}), 400
        if len(uploaded_files) > MAX_BATCH_FILES:
            return jsonify({"detail": f"单次最多导入 {MAX_BATCH_FILES} 份简历"}), 400

        uploads: list[tuple[str, str, bytes, str]] = []
        total_bytes = 0
        for index, file in enumerate(uploaded_files, start=1):
            filename = file.filename
            file_bytes = file.read()
            total_bytes += len(file_bytes)
            uploads.append((f"file-{index}", filename, file_bytes, Path(filename).suffix.lower()))
        if total_bytes > MAX_BATCH_BYTES:
            return jsonify({"detail": f"单次导入总大小不能超过 {MAX_BATCH_BYTES // 1024 // 1024} MB"}), 400

        def generate():
            imported_candidates = 0
            imported_files = 0
            failed_files = 0
            file_total = len(uploads)
            event_queue: Queue[dict[str, Any]] = Queue()
            worker_count = min(MAX_PARALLEL_IMPORTS, file_total)
            with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="resume-import") as executor:
                for file_index, upload in enumerate(uploads, start=1):
                    executor.submit(
                        _run_import_worker,
                        event_queue,
                        upload,
                        file_index,
                        file_total,
                    )

                completed_files = 0
                while completed_files < file_total:
                    event = event_queue.get()
                    if event["type"] == "_file_complete":
                        completed_files += 1
                        if event["success"]:
                            imported_files += 1
                        else:
                            failed_files += 1
                        continue
                    if event["type"] == "candidate":
                        imported_candidates += 1
                    yield _sse_payload(event)
            yield _sse_event(
                "done",
                total=imported_candidates,
                imported_files=imported_files,
                failed_files=failed_files,
                file_total=file_total,
                message=f"导入完成：{imported_files} 份成功，{failed_files} 份失败，生成 {imported_candidates} 条候选人记录。",
            )

        response = Response(stream_with_context(generate()), mimetype="text/event-stream")
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["X-Accel-Buffering"] = "no"
        return response

    return app


def _run_import_worker(
    event_queue: Queue[dict[str, Any]],
    upload: tuple[str, str, bytes, str],
    file_index: int,
    file_total: int,
) -> None:
    file_id, filename, file_bytes, suffix = upload
    success = False
    try:
        for event in _stream_import_upload(
            file_id,
            filename,
            file_bytes,
            suffix,
            file_index,
            file_total,
        ):
            event_queue.put(event)
        success = True
    except Exception as exc:
        event_queue.put(
            _file_event(
                "error",
                file_id,
                filename,
                file_index,
                file_total,
                stage=getattr(exc, "stage", "validation"),
                message=str(exc),
                retryable=True,
            )
        )
    finally:
        event_queue.put({"type": "_file_complete", "file_id": file_id, "success": success})


def _candidate_identity_context() -> list[dict[str, Any]]:
    """给初筛 Agent 提供已有候选人的身份证据，不包含历史评分。"""
    from agi_talent_radar.core.db.orm import CandidateORM
    from agi_talent_radar.core.db.runtime import get_session

    def decode(value: Any) -> list:
        if isinstance(value, list):
            return value
        if not isinstance(value, str) or not value:
            return []
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []

    with get_session() as session:
        rows = session.query(CandidateORM).order_by(CandidateORM.updated_at.desc()).all()
        return [
            {
                "id": row.id,
                "name": row.name or "",
                "target_role": row.target_role or "",
                "stage": row.stage or "",
                "education": decode(row.education)[:6],
                "directions": decode(row.directions)[:8],
                "experiences": decode(row.experiences)[:6],
                "publications": decode(row.publications)[:12],
                "person_id": row.person_id or "",
            }
            for row in rows
        ]


def _stream_import_upload(
    file_id: str,
    filename: str,
    file_bytes: bytes,
    suffix: str,
    file_index: int,
    file_total: int,
):
    current_stage = "validation"
    try:
        if suffix not in VALID_IMPORT_SUFFIXES:
            raise ValueError("仅支持 .pdf / .jsonl / .md / .txt / .png / .jpg / .jpeg / .webp 文件")
        if not file_bytes:
            raise ValueError("文件内容为空")
        yield _file_event(
            "stage",
            file_id,
            filename,
            file_index,
            file_total,
            stage=current_stage,
            status="done",
            message=f"已接收 {filename}，文件校验通过。",
        )
        if suffix == ".pdf":
            if len(file_bytes) > MAX_PDF_BYTES:
                raise ValueError(f"PDF 超过 {MAX_PDF_BYTES // 1024 // 1024} MB 限制。")
            current_stage = "extracting"
            yield _file_event(
                "stage",
                file_id,
                filename,
                file_index,
                file_total,
                stage=current_stage,
                status="running",
                message="正在提取 PDF 文本，扫描页自动走本地 OCR。",
            )
            raw_text, ocr_pages = extract_pdf_text(file_bytes)
            if not raw_text.strip():
                raise ValueError("PDF 未能提取到任何文字内容。")
            resumes = [text_resume(raw_text, filename, ocr_pages=ocr_pages)]
            message = f"已提取 {raw_text.count('[第 ')} 页文本。"
            if ocr_pages:
                message += f"第 {', '.join(map(str, ocr_pages))} 页为扫描件，已本地 OCR。"
            yield _file_event(
                "stage",
                file_id,
                filename,
                file_index,
                file_total,
                stage=current_stage,
                status="done",
                message=message,
            )
        elif suffix in IMAGE_SUFFIXES:
            current_stage = "extracting"
            yield _file_event(
                "stage",
                file_id,
                filename,
                file_index,
                file_total,
                stage=current_stage,
                status="running",
                message="正在对图片简历进行本地 OCR。",
            )
            raw_text = extract_image_text(file_bytes)
            if not raw_text.strip():
                raise ValueError("图片未能提取到任何文字内容。")
            resumes = [text_resume(raw_text, filename, ocr_pages=[1])]
            yield _file_event(
                "stage",
                file_id,
                filename,
                file_index,
                file_total,
                stage=current_stage,
                status="done",
                message="图片 OCR 完成。",
            )
        else:
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir) / f"upload{suffix}"
                temp_path.write_bytes(file_bytes)
                resumes = load_resumes(temp_path)
        current_stage = "structuring"
        yield _file_event(
            "stage",
            file_id,
            filename,
            file_index,
            file_total,
            stage=current_stage,
            status="running",
            message=f"正在解析 {len(resumes)} 份简历的结构化字段。",
        )
        from agi_talent_radar.agents.resume_parser import iter_parse_resume_chunks
        from agi_talent_radar.core.resume_ingestion import take_last_ocr_sections
        structured_inputs: list[CandidateResume] = []
        for resume in resumes:
            if resume.raw_text and not _has_structure(resume):
                merged = resume
                # 5V-Turbo 分节作为版面提示；GLM-5.3 仍在单次调用中读取完整 raw_text
                pre_sections = take_last_ocr_sections() if resume.ocr_pages else None
                for kind, section_name, done, total, payload in iter_parse_resume_chunks(
                    resume.id, resume.raw_text, has_ocr=bool(resume.ocr_pages), pre_sections=pre_sections
                ):
                    if kind == "section":
                        yield _file_event(
                            "structure",
                            file_id,
                            filename,
                            file_index,
                            file_total,
                            stage=current_stage,
                            status="running",
                            section=str(section_name),
                            fields=payload.model_dump(mode="json"),
                            done=done,
                            total=total,
                        )
                    else:
                        merged = payload
                resume = merged.model_copy(
                    update={
                        "source_format": resume.source_format,
                        "document_analysis": resume.document_analysis,
                        "ocr_pages": resume.ocr_pages,
                    }
                )
            structured_inputs.append(resume)
        yield _file_event(
            "stage",
            file_id,
            filename,
            file_index,
            file_total,
            stage=current_stage,
            status="done",
            message=f"已完成 {len(structured_inputs)} 份简历的结构化解析。",
        )

        current_stage = "classification"
        yield _file_event(
            "stage",
            file_id,
            filename,
            file_index,
            file_total,
            stage=current_stage,
            status="running",
            message=f"初筛 Agent 正在分类并判定是否属于已有人才。",
        )

        from agi_talent_radar.core.database import get_session, save_candidate
        from agi_talent_radar.core.db.repository import create_resume_version, save_resume_submission
        import uuid

        structured_by_id = {resume.id: resume for resume in structured_inputs}
        classifications = []
        structured_resumes: list[CandidateResume] = []
        admitted_person_ids: list[str] = []
        with _IMPORT_IDENTITY_LOCK:
            identity_candidates = _candidate_identity_context()
            agent_results = list(
                run_import_agent_stream(
                    structured_inputs,
                    persist=False,
                    identity_candidates=identity_candidates,
                )
            )
            for classification in agent_results:
                source_id = classification.id
                resume = structured_by_id[source_id]
                decision = getattr(classification, "identity_decision", "new_person")
                matched_id = getattr(classification, "matched_candidate_id", "")
                decision = decision if decision in {"same_person", "new_person"} else "new_person"
                matched_id = matched_id if isinstance(matched_id, str) else ""
                if decision == "same_person" and matched_id:
                    # 硬性护栏：LLM 身份误判的代价远高于重复建档。
                    # 新简历无姓名（OCR 质量差无法核验身份）、或姓名与目标候选人不同，
                    # 一律强制 new_person，不允许并档覆盖。
                    from agi_talent_radar.core.db.orm import CandidateORM as _CandidateORM

                    with get_session() as session:
                        existing = session.get(_CandidateORM, matched_id)
                    new_name = (resume.name or "").strip()
                    existing_name = (existing.name or "").strip() if existing else ""
                    if not new_name or (existing_name and new_name != existing_name):
                        decision = "new_person"
                        matched_id = ""
                canonical_id = matched_id if decision == "same_person" and matched_id else source_id
                if canonical_id != source_id:
                    resume = resume.model_copy(update={"id": canonical_id})
                    classification = classification.model_copy(update={"id": canonical_id})

                with get_session() as session:
                    saved = save_candidate(session, resume, classification)
                    saved.group = "pending"
                    identity_confidence = getattr(classification, "identity_confidence", 0)
                    identity_evidence = getattr(classification, "identity_evidence", [])
                    identity_conflicts = getattr(classification, "identity_conflicts", [])
                    identity_payload = {
                        "decision": decision,
                        "matched_candidate_id": matched_id,
                        "confidence": identity_confidence if isinstance(identity_confidence, (int, float)) else 0,
                        "evidence": identity_evidence if isinstance(identity_evidence, list) else [],
                        "conflicts": identity_conflicts if isinstance(identity_conflicts, list) else [],
                    }
                    submission = save_resume_submission(
                        session,
                        resume_id=uuid.uuid4().hex,
                        source_format=resume.source_format,
                        raw_text=resume.raw_text,
                        structured={**resume.model_dump(mode="json"), "identity_resolution": identity_payload},
                        filename=filename,
                        parse_status="done",
                        candidate_id=saved.id,
                        person_id=saved.person_id,
                    )
                    version = create_resume_version(
                        session,
                        submission_id=submission.id,
                        raw_text=resume.raw_text,
                        structured=resume.model_dump(mode="json"),
                        note="导入初筛 Agent 完成身份判定",
                    )
                    saved.current_resume_version_id = version.id
                    session.commit()

                    # 导入即入库：立即关联/创建人物主档，与人才库列表合并（docs/rebuild.md §2.1）
                    from agi_talent_radar.services import talent_service

                    direction = str(resume.directions[0]).strip() if resume.directions else ""
                    person_id = talent_service.admit_candidate_from_import(session, saved, direction)
                    if person_id:
                        admitted_person_ids.append(person_id)
                classifications.append(classification)
                structured_resumes.append(resume)

        candidate_total = len(classifications)
        yield _file_event(
            "stage",
            file_id,
            filename,
            file_index,
            file_total,
            stage="classification",
            status="done",
            message=f"初筛 Agent 已完成 {candidate_total} 份分类与身份判定。",
        )

        # 原始简历落盘：PDF/图片/MD 等都保存原件，前端按格式智能渲染
        if suffix in VALID_IMPORT_SUFFIXES:
            from agi_talent_radar.core.pdf_storage import save_resume_original

            for classification in classifications:
                save_resume_original(classification.id, file_bytes, suffix)

        # 每份简历结构化完立刻 yield + 落库（academic_check_status=none）。
        # 导入流程到这里就结束了——论文核验在后台自动进行，不阻塞导入卡片。
        for candidate_index, (classification, resume) in enumerate(zip(classifications, structured_resumes), start=1):
            yield _file_event(
                "candidate",
                file_id,
                filename,
                file_index,
                file_total,
                index=candidate_index,
                total=candidate_total,
                candidate=_imported_candidate_payload(classification, resume, {}),
            )

        # 导入即入库后的向量同步：best-effort，失败不阻塞导入收尾
        for person_id in admitted_person_ids:
            _sync_person_vectors_best_effort(person_id)

        # 论文核验在后台线程池异步进行，不阻塞导入 SSE 流。
        # 导入卡片此时已经关闭，核验结果通过前端轮询候选人列表刷新。
        from agi_talent_radar.core.background import trigger_publication_verification
        for classification, resume in zip(classifications, structured_resumes):
            pubs = [str(p) for p in (resume.publications or []) if str(p).strip()]
            if pubs:
                trigger_publication_verification(classification.id, resume.name, pubs, resume.raw_text)
            else:
                # 没有论文直接标记 done
                try:
                    from agi_talent_radar.core.db.runtime import get_session
                    from agi_talent_radar.core.db.orm import CandidateORM
                    from datetime import datetime, timezone
                    with get_session() as session:
                        cand = session.get(CandidateORM, classification.id)
                        if cand:
                            cand.academic_check_status = "done"
                            cand.academic_check_at = datetime.now(timezone.utc)
                            session.commit()
                except Exception:
                    pass
    except Exception as exc:
        if isinstance(exc, ImportFileError):
            raise
        raise ImportFileError(current_stage, str(exc)) from exc


def _file_event(
    event_type: str,
    file_id: str,
    file_name: str,
    file_index: int,
    file_total: int,
    **payload: Any,
) -> dict[str, Any]:
    return {
        "type": event_type,
        "file_id": file_id,
        "file_name": file_name,
        "file_index": file_index,
        "file_total": file_total,
        **payload,
    }


def _imported_candidate_payload(classification, resume: CandidateResume, academic_report: dict | None = None) -> dict[str, Any]:
    return {
        "id": classification.id,
        "name": classification.name,
        "role": resume.target_role,
        "stage": resume.stage,
        "group": "pending",
        "category": classification.category,
        # ImportClassification 无 level 字段；初筛阶段尚未定级，返回空串
        "level": getattr(classification, "level", ""),
        "confidence": classification.confidence,
        "reason": classification.reason,
        "education": resume.education,
        "directions": resume.directions,
        "experiences": [experience.model_dump() for experience in resume.experiences],
        "projects": [project.model_dump() for project in resume.projects],
        "publications": resume.publications,
        "skills": resume.skills,
        "screening_tags": resume.screening_tags,
        "raw_text": resume.raw_text,
        "source_format": resume.source_format,
        "document_analysis": resume.document_analysis,
        "academic_report": academic_report or {},
    }


def _candidate_search_text(row) -> str:
    """拼接候选人可搜字段（学校/机构/方向/论文），供前端全文搜索。"""
    parts = [row.name or "", row.target_role or "", row.stage or ""]
    # education: list[dict|str]，提取学校名
    edu = getattr(row, "education", None) or []
    if isinstance(edu, list):
        for item in edu:
            if isinstance(item, dict):
                parts.append(str(item.get("school") or ""))
            else:
                parts.append(str(item))
    # directions: list[str]
    dirs = getattr(row, "directions", None) or []
    if isinstance(dirs, list):
        parts.extend(str(d) for d in dirs)
    # publications: list[str]
    pubs = getattr(row, "publications", None) or []
    if isinstance(pubs, list):
        parts.extend(str(p) for p in pubs)
    return " ".join(p for p in parts if p)


def current_user_display_name() -> str:
    """当前登录用户显示名（分享记录 created_by 用）；无会话时空串。"""
    try:
        from flask import session as flask_session

        uid = flask_session.get("user_id")
        if not uid:
            return ""
        from agi_talent_radar.core.database import get_session
        from agi_talent_radar.core.db.orm import UserORM

        with get_session() as s:
            user = s.get(UserORM, uid)
            return (user.display_name or user.username) if user else ""
    except Exception:
        return ""


def _orm_to_brief(row) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name or row.id,
        "role": row.target_role,
        "stage": row.stage,
        "group": row.group,
        "level": row.import_level,
        "category": row.import_category,
        # 阶段 1 新字段：HR 跟进状态 + 来源
        "engagement_status": getattr(row, "engagement_status", "newly_admitted"),
        "admitted_at": _iso(getattr(row, "admitted_at", None)),
        "person_id": getattr(row, "person_id", None),
        # 队列用：是否已评估，决定删除/移出语义（未评估=物理删，已评估=仅移出列表）
        "evaluated": bool(getattr(row, "evaluated", False)),
        # 论文核验状态：none | running | done
        "academic_check_status": getattr(row, "academic_check_status", "none"),
        # 核验结果：none | running | verified | rejected | needs_review
        "verification_result": _verification_result(row),
        # 能否进入评估：只有核验通过才可
        "evaluable": _is_evaluable(row),
        "evaluation_status": getattr(row, "evaluation_status", "idle"),
        "evaluation_run_id": getattr(row, "evaluation_run_id", None),
        # 搜索用文本（学校/机构/方向/论文，客户端全文搜索）
        "search_text": _candidate_search_text(row),
    }


def _verification_result(row) -> str:
    """根据 academic_check_status + alignments 计算最终核验状态。
    none / running / verified / rejected / needs_review
    """
    status = getattr(row, "academic_check_status", "none")
    if status == "none":
        return "none"
    if status == "running":
        return "running"
    # done：根据 verdict 判断
    report = _load_json(getattr(row, "academic_report", "")) or {}
    aligns = report.get("alignments", [])
    if not aligns:
        # 区分"真无论文"（publications 空 → verified）和"有论文但报告缺失"（→ needs_review）
        pubs = _load_json(getattr(row, "publications", "")) or []
        return "verified" if not pubs else "needs_review"
    # 草稿/未发表的论文不参与门禁（查不到记录是正常的，不该阻断）
    actionable = [a for a in aligns if str(a.get("claim", {}).get("claimed_status", "")).strip() not in ("草稿", "draft", "未发表", "under review", "在投", "投稿中")]
    if not actionable:
        return "verified"
    verdicts = [_effective_alignment_verdict(a) for a in actionable]
    # 门禁优先级：未裁决的 unverifiable 最优先阻断（必须人工全部裁决）；
    # 再看 mismatch（冲突可不平反也能评估，进评估 prompt 作风险）。
    if any(v == "unverifiable" for v in verdicts):
        return "needs_review"
    if any(v == "mismatch" for v in verdicts):
        return "rejected"
    return "verified"


def _effective_alignment_verdict(alignment: dict[str, Any]) -> str:
    human_status = alignment.get("human_status", "unreviewed")
    if human_status == "confirmed":
        return "verified"
    if human_status == "dismissed":
        return "mismatch"
    return alignment.get("verdict", "unverifiable")


def _evaluation_academic_report(row) -> dict[str, Any]:
    """生成送入评估图的报告副本，并应用人工裁决的有效 verdict 与人工备注。"""
    report = deepcopy(_load_json(getattr(row, "academic_report", "")) or {})
    for alignment in report.get("alignments", []):
        effective_verdict = _effective_alignment_verdict(alignment)
        if effective_verdict == alignment.get("verdict"):
            continue
        alignment["machine_verdict"] = alignment.get("verdict", "unverifiable")
        alignment["verdict"] = effective_verdict
        human_note = str(alignment.get("human_note", "")).strip()
        if effective_verdict == "mismatch":
            discrepancies = list(alignment.get("discrepancies", []))
            discrepancies.append("人工核验认为 AI 判定有误")
            alignment["discrepancies"] = list(dict.fromkeys(discrepancies))
        # 人工裁决与备注显式并入 note，后续评估 agent 可见
        label = "人工核验认同 AI 判定" if effective_verdict == "verified" else "人工核验认为 AI 判定有误"
        stamped = label + (f"：{human_note}" if human_note else "")
        alignment["note"] = " ".join(x for x in [str(alignment.get("note", "")).strip(), stamped] if x).strip()
    return report


def _is_evaluable(row) -> bool:
    """论文核验不再阻断评估:任何核验状态均可进入评估流程。

    核验结果只作风险提示(经 global_critic 进入 potential_risks),不影响能否评估。
    """
    return True


def _iso(value) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _orm_to_detail(row) -> dict[str, Any]:
    from agi_talent_radar.core.graph import evaluation_graph_catalog

    return {
        "id": row.id,
        "name": row.name or row.id,
        "role": row.target_role,
        "stage": row.stage,
        "group": row.group,
        "level": row.import_level,
        "category": row.import_category,
        "confidence": row.import_confidence,
        "raw_text": row.raw_text,
        "supplementary_info": _string_attr(row, "supplementary_info", ""),
        "education": _load_json(row.education),
        "directions": _load_json(row.directions),
        "experiences": _load_json(getattr(row, "experiences", "")),
        "projects": _load_json(row.projects),
        "publications": _load_json(row.publications),
        "skills": _load_json(row.skills),
        "screening_tags": _load_json(row.screening_tags),
        "source_format": _string_attr(row, "source_format", "text"),
        "document_analysis": _load_json(getattr(row, "document_analysis", "")) or {},
        # 导入阶段论文核验结果
        "academic_report": _evaluation_academic_report(row),
        "evaluation_graph": evaluation_graph_catalog(),
        # 论文核验状态 + 结果 + 可评估标记
        "academic_check_status": getattr(row, "academic_check_status", "none"),
        "verification_result": _verification_result(row),
        "evaluable": _is_evaluable(row),
        # 阶段 1 新字段：HR 跟进状态 + 来源 + 入库时间
        "person_id": getattr(row, "person_id", None),
        "engagement_status": getattr(row, "engagement_status", "newly_admitted"),
        "admitted_at": _iso(getattr(row, "admitted_at", None)),
        "person_id": getattr(row, "person_id", None),
        "sources": [s.source_kind for s in (row.sources or [])],
    }


def _dominant_track(evaluation) -> tuple[str, float]:
    best_fit_jd_id = str(getattr(evaluation, "best_fit_jd_id", "") or "")
    if best_fit_jd_id:
        assessments = getattr(evaluation, "job_fit_assessments", None) or []
        best = next(
            (item for item in assessments if str(item.get("jd_id", "")) == best_fit_jd_id),
            {},
        )
        return best_fit_jd_id, float(best.get("fit_score", 0) or 0) / 100
    assignments = getattr(evaluation, "track_assignments", None) or []
    if not assignments:
        return "", 0.0
    best = max(assignments, key=lambda item: float(getattr(item, "weight", 0) or 0))
    return str(getattr(best, "track", "") or ""), float(getattr(best, "weight", 0) or 0)


def _person_candidate_fields(candidate, latest_eval) -> dict[str, Any]:
    track, weight = _dominant_track(latest_eval)
    return {
        "candidate_id": getattr(candidate, "id", None),
        "engagement_status": getattr(candidate, "engagement_status", "newly_admitted"),
        "source_kinds": [source.source_kind for source in (getattr(candidate, "sources", None) or [])],
        "dominant_track": track,
        "dominant_track_weight": weight,
    }


def _person_to_brief(person, candidate=None) -> dict[str, Any]:
    """人才库列表项：主档摘要 + 最新评估/舆情快照。"""
    latest_eval = _latest_evaluation(person)
    latest_rep = _latest_reputation(person)
    return {
        "id": person.id,
        "name": person.name or person.id,
        "org": person.org or "",
        "direction": person.direction or "",
        "person_type": person.person_type,
        "group_id": person.group_id,
        "schools": getattr(person, "schools", None) or [],
        "top_schools": top_school_names(getattr(person, "schools", None) or []),
        "overall_score": latest_eval.overall_score if latest_eval else None,
        "level": latest_eval.level if latest_eval else None,
        "reputation_level": latest_rep.level if latest_rep else None,
        "reputation_status": latest_rep.review_status if latest_rep else None,
        "updated_at": person.updated_at.isoformat() if person.updated_at else None,
        **_person_candidate_fields(candidate, latest_eval),
    }


def _person_to_detail(person, candidate=None) -> dict[str, Any]:
    """人才详情：主档 + 评估历史 + 舆情报告列表。"""
    latest_eval = _latest_evaluation(person)
    return {
        "id": person.id,
        "name": person.name or person.id,
        "org": person.org or "",
        "direction": person.direction or "",
        "person_type": person.person_type,
        "schools": getattr(person, "schools", None) or [],
        "top_schools": top_school_names(getattr(person, "schools", None) or []),
        "created_at": person.created_at.isoformat() if person.created_at else None,
        "updated_at": person.updated_at.isoformat() if person.updated_at else None,
        "evaluations": [_orm_to_evaluation(ev) for ev in sorted(person.evaluations, key=lambda e: e.id, reverse=True)],
        "reputation_reports": [_reputation_report_to_dict(r) for r in sorted(person.reputation_reports, key=lambda r: r.created_at, reverse=True)],
        **_person_candidate_fields(candidate, latest_eval),
    }


def _reputation_report_to_dict(report) -> dict[str, Any]:
    """舆情报告序列化。"""
    return {
        "id": report.id,
        "person_id": report.person_id,
        "level": report.level,
        "events": report.events or [],
        "review_status": report.review_status,
        "reviewer": report.reviewer or "",
        "review_note": report.review_note or "",
        "created_at": report.created_at.isoformat() if report.created_at else None,
        "reviewed_at": report.reviewed_at.isoformat() if report.reviewed_at else None,
    }


def _latest_evaluation(person):
    completed = [e for e in person.evaluations if e.status == "completed"]
    if not completed:
        return None
    return max(completed, key=lambda e: e.id)


def _latest_reputation(person):
    if not person.reputation_reports:
        return None
    return max(person.reputation_reports, key=lambda r: r.created_at)


def _orm_to_resume(row) -> CandidateResume:
    raw_text = row.raw_text or ""
    supplementary = _string_attr(row, "supplementary_info", "").strip()
    if supplementary:
        # HR 补充的信息（简历上没有的）并入评估输入
        raw_text = f"{raw_text}\n\n[HR 补充信息]\n{supplementary}" if raw_text else f"[HR 补充信息]\n{supplementary}"
    return CandidateResume.model_validate({
        "id": row.id,
        "name": row.name,
        "target_role": row.target_role,
        "stage": row.stage,
        "raw_text": row.raw_text,
        "education": _load_json(row.education),
        "directions": _load_json(row.directions),
        "experiences": _load_json(getattr(row, "experiences", "")),
        "projects": _load_json(row.projects),
        "publications": _load_json(row.publications),
        "skills": _load_json(row.skills),
        "screening_tags": _load_json(row.screening_tags),
        "source_format": _string_attr(row, "source_format", "text"),
        "document_analysis": _load_json(getattr(row, "document_analysis", "")) or {},
    })


def _orm_to_evaluation(row) -> dict[str, Any]:
    from agi_talent_radar.core.database import EvaluationORM, evaluation_to_dict

    if isinstance(row, EvaluationORM):
        return evaluation_to_dict(row)
    return {
        "overall_score": row.overall_score,
        "level": row.level,
        "tier": row.tier,
        "decision_method": row.decision_method or "",
        "one_liner": row.one_liner,
        "core_strengths": row.core_strengths or [],
        "potential_risks": row.potential_risks or [],
        "interview_questions": row.interview_questions or [],
        "cultivation_direction": row.cultivation_direction or [],
        "dimension_scores": row.dimension_scores or [],
        "evidence": row.evidence or [],
        "critic_flags": row.critic_flags or [],
        "normalized_education": row.normalized_education or [],
        "screening_tags": row.screening_tags or [],
        "common_score": _number_attr(row, "common_score"),
        "document_score": _number_attr(row, "document_score"),
        "track_assignments": _list_attr(row, "track_assignments"),
        "track_evaluations": _list_attr(row, "track_evaluations"),
        "routing_confidence": _number_attr(row, "routing_confidence"),
        "evaluation_mode": row.evaluation_mode,
    }


def _load_json(value: str) -> Any:
    if isinstance(value, (list, dict)):
        return value
    if not isinstance(value, str):
        return []
    if not value:
        return []
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return []


def _string_attr(row, name: str, default: str = "") -> str:
    value = getattr(row, name, default)
    return value if isinstance(value, str) else default


def _number_attr(row, name: str, default: float = 0) -> float:
    value = getattr(row, name, default)
    return float(value) if isinstance(value, (int, float)) else default


def _list_attr(row, name: str) -> list:
    value = getattr(row, name, [])
    return value if isinstance(value, list) else []


def _sse_event(event_type: str, **payload: Any) -> str:
    return _sse_payload({"type": event_type, **payload})


def _sse_payload(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


app = create_app()
