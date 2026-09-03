"""人才材料包 API：批量上传（一人一 zip）/ 列表 / 详情 / 解析（SSE 双 agent）。"""
from __future__ import annotations

import json
import logging
import os
import queue
import threading

from flask import Blueprint, Response, jsonify, request, stream_with_context

from agi_talent_radar.core.db.orm import TalentBundleORM

logger = logging.getLogger(__name__)


def build_bundle_blueprint() -> Blueprint:
    bp = Blueprint("talent_bundle_api", __name__)

    @bp.get("/api/talent-bundles")
    def list_bundles():
        from agi_talent_radar.core.db.runtime import get_session

        with get_session() as session:
            rows = session.query(TalentBundleORM).order_by(TalentBundleORM.id.desc()).limit(100).all()
            return jsonify([_to_dict(b, with_trace=False) for b in rows])

    @bp.post("/api/talent-bundles")
    def upload_bundles():
        """批量上传：每个 zip = 一人。系统只解最外层（分人），内层包留给 agent。"""
        from agi_talent_radar.core.db.runtime import get_session
        from agi_talent_radar.talent_bundle.ingest import create_bundle

        files = request.files.getlist("files") or []
        if not files:
            return jsonify({"detail": "请选择 zip 文件（可多选，一人一包）"}), 400
        created, errors = [], []
        with get_session() as session:
            for storage in files:
                try:
                    bundle = create_bundle(storage.filename or "bundle.zip", storage.read())
                    session.add(bundle)
                    session.commit()
                    created.append(_to_dict(bundle))
                except Exception as exc:  # noqa: BLE001 — 单包失败不拖垮整批
                    logger.warning("材料包 %s 入库失败：%s", storage.filename, exc)
                    errors.append({"filename": storage.filename, "error": str(exc)[:200]})
        return jsonify({"created": created, "errors": errors}), 201

    @bp.get("/api/talent-bundles/by-candidate/<candidate_id>")
    def bundle_by_candidate(candidate_id: str):
        """按候选人查材料包文件清单（无包返回空列表——存量单简历候选人走原件预览）。"""
        from agi_talent_radar.core.db.runtime import get_session
        from agi_talent_radar.talent_bundle.tools import BundleContext, walk_files

        with get_session() as session:
            bundle = (
                session.query(TalentBundleORM)
                .filter_by(candidate_id=candidate_id)
                .order_by(TalentBundleORM.id.desc())
                .first()
            )
        if bundle is None:
            return jsonify({"bundle_id": None, "files": []})
        ctx = BundleContext(bundle.id)
        files = []
        for rel in walk_files(ctx):
            path = ctx.resolve(rel)
            files.append({
                "file": rel,
                "size_kb": max(1, os.path.getsize(path) // 1024) if path and os.path.isfile(path) else 0,
            })
        return jsonify({"bundle_id": bundle.id, "status": bundle.status, "files": files})

    @bp.get("/api/talent-bundles/<bundle_id>/file")
    def bundle_file(bundle_id: str):
        """包内文件预览/下载（path 相对工作区，防穿越）。"""
        from flask import send_file

        from agi_talent_radar.talent_bundle.tools import BundleContext

        ctx = BundleContext(bundle_id)
        path = ctx.resolve(request.args.get("path", ""))
        if not path or not os.path.isfile(path):
            return jsonify({"detail": "文件不存在"}), 404
        return send_file(path)

    @bp.get("/api/talent-bundles/<bundle_id>")
    def get_bundle(bundle_id: str):
        from agi_talent_radar.core.db.runtime import get_session

        with get_session() as session:
            bundle = session.get(TalentBundleORM, bundle_id)
            if bundle is None:
                return jsonify({"detail": "材料包不存在"}), 404
            return jsonify(_to_dict(bundle, with_trace=True))

    @bp.post("/api/talent-bundles/<bundle_id>/evaluate")
    def evaluate_bundle(bundle_id: str):
        """SSE：双 agent（评估+督导）解析过程直播。重复请求时若已在跑直接拒绝。"""
        from agi_talent_radar.core.db.runtime import get_session

        with get_session() as session:
            bundle = session.get(TalentBundleORM, bundle_id)
            if bundle is None:
                return jsonify({"detail": "材料包不存在"}), 404
            if bundle.status == "profiling":
                return jsonify({"detail": "该包正在解析中"}), 409

        events: queue.Queue = queue.Queue()

        def emit(type_: str, payload: dict) -> None:
            events.put({"type": type_, "payload": payload})

        def worker() -> None:
            from agi_talent_radar.talent_bundle.agent import run_bundle_agent

            try:
                with get_session() as session:
                    bundle = session.get(TalentBundleORM, bundle_id)
                    run_bundle_agent(session, bundle, emit)
            except Exception as exc:  # noqa: BLE001
                logger.exception("材料包解析 worker 失败")
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
            with get_session() as session:
                bundle = session.get(TalentBundleORM, bundle_id)
                payload = _to_dict(bundle, with_trace=True) if bundle else {"status": "failed"}
            yield f"data: {json.dumps({'type': 'done', 'payload': payload}, ensure_ascii=False)}\n\n"

        return Response(stream_with_context(generate()), mimetype="text/event-stream")

    return bp


def _to_dict(bundle: TalentBundleORM, with_trace: bool = False) -> dict:
    data = {
        "id": bundle.id,
        "filename": bundle.filename,
        "status": bundle.status,
        "person_id": bundle.person_id,
        "candidate_id": bundle.candidate_id,
        "error_message": bundle.error_message or "",
        "file_count": bundle.file_count or 0,
        "total_bytes": bundle.total_bytes or 0,
        "created_at": bundle.created_at.isoformat() if bundle.created_at else None,
    }
    if with_trace:
        data["trace"] = bundle.trace or []
        data["profile"] = bundle.profile
    return data
