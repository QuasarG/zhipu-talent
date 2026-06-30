from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from flask import Flask, Response, jsonify, render_template, request, stream_with_context

from agi_talent_radar.core.import_agent import run_import_agent_stream
from agi_talent_radar.core.io import load_resumes
from agi_talent_radar.core.models import CandidateEvaluation, CandidateResume
from agi_talent_radar.core.runner import run_candidate_stream


ROOT = Path(__file__).resolve().parents[2]


def create_app() -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config["JSON_AS_ASCII"] = False

    @app.get("/")
    def index() -> str:
        return render_template("workbench.html")

    @app.get("/api/candidates")
    def list_candidates():
        group = request.args.get("group")
        try:
            from agi_talent_radar.core.database import get_session, list_candidates, list_candidates_by_group

            with get_session() as session:
                if group:
                    if group not in {"pending", "shortlisted", "alternative"}:
                        return jsonify({"detail": "group 必须是 pending/shortlisted/alternative"}), 400
                    rows = list_candidates_by_group(session, group)
                else:
                    rows = list_candidates(session)
                candidates = [_orm_to_brief(row) for row in rows]
            return jsonify(candidates)
        except Exception as exc:
            return jsonify([]), 500

    @app.get("/api/candidates/<candidate_id>")
    def get_candidate(candidate_id: str):
        try:
            from agi_talent_radar.core.database import get_candidate_with_latest_evaluation, get_session

            with get_session() as session:
                candidate_orm, evaluation = get_candidate_with_latest_evaluation(session, candidate_id)
                if not candidate_orm:
                    return jsonify({"detail": "候选人不存在"}), 404
                data = _orm_to_detail(candidate_orm)
                if evaluation:
                    data["latest_evaluation"] = _orm_to_evaluation(evaluation)
                return jsonify(data)
        except Exception as exc:
            return jsonify({"detail": str(exc)}), 500

    @app.post("/api/candidates/<candidate_id>/evaluate")
    def evaluate_candidate(candidate_id: str):
        try:
            from agi_talent_radar.core.database import get_candidate_with_latest_evaluation, get_session

            with get_session() as session:
                candidate_orm, _ = get_candidate_with_latest_evaluation(session, candidate_id)
                if not candidate_orm:
                    return jsonify({"detail": "候选人不存在"}), 404
                resume = _orm_to_resume(candidate_orm)
        except Exception as exc:
            return jsonify({"detail": f"读取候选人失败: {exc}"}), 500

        def generate():
            evaluation = None
            try:
                for event in run_candidate_stream(resume):
                    if event["type"] == "result":
                        evaluation = CandidateEvaluation.model_validate(event["result"])
                        evaluation.id = candidate_id
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

                if evaluation:
                    from agi_talent_radar.core.database import get_session, move_candidate_group, save_evaluation

                    with get_session() as session:
                        save_evaluation(session, evaluation)
                        group = "shortlisted" if evaluation.overall_score >= 60 else "alternative"
                        move_candidate_group(session, candidate_id, group)
            except Exception as exc:
                yield f"data: {json.dumps({'type': 'error', 'message': str(exc)}, ensure_ascii=False)}\n\n"

        response = Response(stream_with_context(generate()), mimetype="text/event-stream")
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["X-Accel-Buffering"] = "no"
        return response

    @app.delete("/api/candidates/<candidate_id>")
    def delete_candidate(candidate_id: str):
        try:
            from agi_talent_radar.core.database import delete_candidate as _delete_candidate, get_session

            with get_session() as session:
                deleted = _delete_candidate(session, candidate_id)
                if not deleted:
                    return jsonify({"detail": "候选人不存在"}), 404
                return jsonify({"id": candidate_id, "deleted": True})
        except Exception as exc:
            return jsonify({"detail": str(exc)}), 500

    @app.post("/api/candidates/<candidate_id>/move")
    def move_candidate(candidate_id: str):
        body = request.get_json(silent=True) or {}
        group = body.get("group")
        if group not in {"pending", "shortlisted", "alternative"}:
            return jsonify({"detail": "group 必须是 pending/shortlisted/alternative"}), 400
        try:
            from agi_talent_radar.core.database import get_session, move_candidate_group

            with get_session() as session:
                moved = move_candidate_group(session, candidate_id, group)
                if not moved:
                    return jsonify({"detail": "候选人不存在"}), 404
                return jsonify({"id": moved.id, "group": moved.group})
        except Exception as exc:
            return jsonify({"detail": str(exc)}), 500

    @app.post("/api/import-file")
    def import_file():
        file = request.files.get("file")
        if not file or not file.filename:
            return jsonify({"detail": "请上传 .jsonl / .md / .txt 简历文件"}), 400
        suffix = Path(file.filename).suffix.lower()
        if suffix not in {".jsonl", ".md", ".txt"}:
            return jsonify({"detail": "仅支持 .jsonl / .md / .txt 文件"}), 400

        # 预先把文件内容读入内存，避免生成器执行时请求上下文已关闭
        file_bytes = file.read()

        def generate():
            try:
                with tempfile.TemporaryDirectory() as temp_dir:
                    temp_path = Path(temp_dir) / f"upload{suffix}"
                    temp_path.write_bytes(file_bytes)
                    resumes = load_resumes(temp_path)
                    resume_by_id = {resume.id: resume for resume in resumes}
                    classifications = list(run_import_agent_stream(resumes, persist=True))
                    total = len(classifications)
                    for index, classification in enumerate(classifications, start=1):
                        resume = resume_by_id[classification.id]
                        payload = {
                            "type": "candidate",
                            "index": index,
                            "total": total,
                            "candidate": {
                                "id": classification.id,
                                "name": classification.name,
                                "role": resume.target_role,
                                "stage": resume.stage,
                                "group": "pending",
                                "category": classification.category,
                                "level": classification.level,
                                "confidence": classification.confidence,
                                "reason": classification.reason,
                                "education": resume.education,
                                "directions": resume.directions,
                                "projects": [project.model_dump() for project in resume.projects],
                                "publications": resume.publications,
                                "skills": resume.skills,
                                "screening_tags": resume.screening_tags,
                                "raw_text": resume.raw_text,
                            },
                        }
                        yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    yield f"data: {json.dumps({'type': 'done', 'total': total}, ensure_ascii=False)}\n\n"
            except Exception as exc:
                yield f"data: {json.dumps({'type': 'error', 'message': str(exc)}, ensure_ascii=False)}\n\n"

        response = Response(stream_with_context(generate()), mimetype="text/event-stream")
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["X-Accel-Buffering"] = "no"
        return response

    return app


def _orm_to_brief(row) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name or row.id,
        "role": row.target_role,
        "stage": row.stage,
        "group": row.group,
        "level": row.import_level,
        "category": row.import_category,
    }


def _orm_to_detail(row) -> dict[str, Any]:
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
        "education": _load_json(row.education),
        "directions": _load_json(row.directions),
        "projects": _load_json(row.projects),
        "publications": _load_json(row.publications),
        "skills": _load_json(row.skills),
        "screening_tags": _load_json(row.screening_tags),
    }


def _orm_to_resume(row) -> CandidateResume:
    return CandidateResume.model_validate({
        "id": row.id,
        "name": row.name,
        "target_role": row.target_role,
        "stage": row.stage,
        "raw_text": row.raw_text,
        "education": _load_json(row.education),
        "directions": _load_json(row.directions),
        "projects": _load_json(row.projects),
        "publications": _load_json(row.publications),
        "skills": _load_json(row.skills),
        "screening_tags": _load_json(row.screening_tags),
    })


def _orm_to_evaluation(row) -> dict[str, Any]:
    return {
        "overall_score": row.overall_score,
        "level": row.level,
        "tier": row.tier,
        "one_liner": row.one_liner,
        "core_strengths": row.core_strengths,
        "potential_risks": row.potential_risks,
        "interview_questions": row.interview_questions,
        "cultivation_direction": row.cultivation_direction,
        "dimension_scores": row.dimension_scores,
        "evidence": row.evidence,
    }


def _load_json(value: str) -> Any:
    if not value:
        return []
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return []


app = create_app()
