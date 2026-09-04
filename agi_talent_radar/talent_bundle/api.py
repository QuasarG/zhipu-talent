"""人才材料包 API：批量上传（一人一 zip）/ 列表 / 详情 / 解析（SSE 双 agent）。"""
from __future__ import annotations

import json
import logging
import os
import urllib.parse

from flask import Blueprint, jsonify, request

from agi_talent_radar.core.db.orm import TalentBundleORM
from agi_talent_radar.talent_bundle.ingest import locate_resume

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
                    duplicate = (
                        session.query(TalentBundleORM)
                        .filter_by(filename=storage.filename)
                        .filter(TalentBundleORM.status != "failed")
                        .first()
                    )
                    if duplicate is not None:
                        errors.append({"filename": storage.filename, "error": "同名材料包已存在，请先处理或改名后再传"})
                        continue
                    bundle = create_bundle(storage.filename or "bundle.zip", storage.read())
                    resume_rel = locate_resume(bundle.id)
                    if not resume_rel:
                        bundle.status = "noresume"
                        bundle.error_message = "未定位到简历文件，请在文件列表中选择一份设为简历"
                    else:
                        bundle.resume_file = resume_rel
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
            # 存量候选人 = 目录里只有一份简历的材料包：把简历原件作为唯一材料条目
            from agi_talent_radar.core.pdf_storage import get_resume_original_path

            files = []
            original = get_resume_original_path(candidate_id)
            if original and original.is_file():
                files.append({
                    "file": original.name,
                    "size_kb": max(1, original.stat().st_size // 1024),
                    "url": f"/api/candidates/{candidate_id}/original-file",
                })
            return jsonify({
                "bundle_id": None,
                "storage_kind": "legacy_resume",
                "resume_file": original.name if original and original.is_file() else "",
                "files": files,
            })
        ctx = BundleContext(bundle.id)
        files = []
        for rel in walk_files(ctx):
            path = ctx.resolve(rel)
            files.append({
                "file": rel,
                "size_kb": max(1, os.path.getsize(path) // 1024) if path and os.path.isfile(path) else 0,
                "url": f"/api/talent-bundles/{bundle.id}/file?path={urllib.parse.quote(rel)}",
            })
        return jsonify({
            "bundle_id": bundle.id,
            "storage_kind": "material_bundle",
            "status": bundle.status,
            "resume_file": bundle.resume_file or locate_resume(bundle.id) or "",
            "files": files,
        })

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

    @bp.post("/api/talent-bundles/<bundle_id>/use-as-resume")
    def use_as_resume(bundle_id: str):
        """人工指定包内某文件为简历（自动定位失败时的兜底），路径持久化。"""
        from agi_talent_radar.core.db.runtime import get_session
        from agi_talent_radar.talent_bundle.tools import BundleContext

        body = request.get_json(silent=True) or {}
        rel = str(body.get("path") or "").strip()
        with get_session() as session:
            bundle = session.get(TalentBundleORM, bundle_id)
            if bundle is None:
                return jsonify({"detail": "材料包不存在"}), 404
            ctx = BundleContext(bundle_id)
            path = ctx.resolve(rel)
            if not path or not os.path.isfile(path):
                return jsonify({"detail": "文件不存在"}), 404
            bundle.resume_file = rel
            session.commit()
            return jsonify({"ok": True, "resume_file": rel})

    @bp.get("/api/talent-bundles/<bundle_id>")
    def get_bundle(bundle_id: str):
        from agi_talent_radar.core.db.runtime import get_session

        with get_session() as session:
            bundle = session.get(TalentBundleORM, bundle_id)
            if bundle is None:
                return jsonify({"detail": "材料包不存在"}), 404
            return jsonify(_to_dict(bundle, with_trace=True))

    @bp.post("/api/talent-bundles/<bundle_id>/link")
    def link_bundle(bundle_id: str):
        """导入链路完成后把候选人与包关联（status=imported）。"""
        from agi_talent_radar.core.db.orm import CandidateORM
        from agi_talent_radar.core.db.runtime import get_session

        body = request.get_json(silent=True) or {}
        candidate_id = str(body.get("candidate_id") or "").strip()
        if not candidate_id:
            return jsonify({"detail": "candidate_id 必填"}), 400
        with get_session() as session:
            bundle = session.get(TalentBundleORM, bundle_id)
            if bundle is None:
                return jsonify({"detail": "材料包不存在"}), 404
            candidate = session.get(CandidateORM, candidate_id)
            if candidate is None:
                return jsonify({"detail": "候选人不存在"}), 404
            bundle.candidate_id = candidate_id
            bundle.person_id = candidate.person_id
            bundle.status = "imported"
            session.commit()
            return jsonify(_to_dict(bundle))

    return bp


def _bundle_files(bundle: TalentBundleORM) -> list[dict]:
    """包内文件清单（相对路径+大小+预览 url）。"""
    from agi_talent_radar.talent_bundle.tools import BundleContext, walk_files

    try:
        ctx = BundleContext(bundle.id)
    except Exception:  # noqa: BLE001
        return []
    files = []
    for rel in walk_files(ctx):
        path = ctx.resolve(rel)
        files.append({
            "file": rel,
            "size_kb": max(1, os.path.getsize(path) // 1024) if path and os.path.isfile(path) else 0,
            "url": f"/api/talent-bundles/{bundle.id}/file?path={urllib.parse.quote(rel)}",
        })
    return files


def _to_dict(bundle: TalentBundleORM, with_trace: bool = False) -> dict:
    data = {
        "id": bundle.id,
        "filename": bundle.filename,
        "status": bundle.status,
        "person_id": bundle.person_id,
        "candidate_id": bundle.candidate_id,
        "error_message": bundle.error_message or "",
        "resume_file": bundle.resume_file or (locate_resume(bundle.id) if bundle.status in ("unpacked", "noresume") else ""),
        "files": _bundle_files(bundle),
        "file_count": bundle.file_count or 0,
        "total_bytes": bundle.total_bytes or 0,
        "created_at": bundle.created_at.isoformat() if bundle.created_at else None,
    }
    if with_trace:
        data["trace"] = bundle.trace or []
        data["profile"] = bundle.profile
    return data
