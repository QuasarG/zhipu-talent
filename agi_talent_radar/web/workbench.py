from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from flask import Flask, Response, jsonify, render_template, request, stream_with_context

from agi_talent_radar.core.import_agent import run_import_agent_stream
from agi_talent_radar.core.io import load_resumes
from agi_talent_radar.core.models import CandidateEvaluation, CandidateResume
from agi_talent_radar.core.resume_ingestion import MAX_PDF_BYTES, analyze_resume_pages, render_pdf_pages
from agi_talent_radar.core.runner import run_candidate_stream


ROOT = Path(__file__).resolve().parents[2]
VALID_GROUPS = {"pending", "shortlisted", "alternative", "rejected"}


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
                    if group not in VALID_GROUPS:
                        return jsonify({"detail": "group 必须是 pending/shortlisted/alternative/rejected"}), 400
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
                    data["evaluation"] = _orm_to_evaluation(evaluation)
                    data["latest_evaluation"] = data["evaluation"]
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
                        group = _group_for_score(evaluation.overall_score)
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
        if group not in VALID_GROUPS:
            return jsonify({"detail": "group 必须是 pending/shortlisted/alternative/rejected"}), 400
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
            return jsonify({"detail": "请上传 .pdf / .jsonl / .md / .txt 简历文件"}), 400
        suffix = Path(file.filename).suffix.lower()
        if suffix not in {".pdf", ".jsonl", ".md", ".txt"}:
            return jsonify({"detail": "仅支持 .pdf / .jsonl / .md / .txt 文件"}), 400

        # 预先把文件内容读入内存，避免生成器执行时请求上下文已关闭
        file_bytes = file.read()
        filename = file.filename

        def generate():
            current_stage = "validation"
            try:
                yield _sse_event(
                    "stage",
                    stage=current_stage,
                    status="done",
                    message=f"已接收 {filename}，文件校验通过。",
                )
                if suffix == ".pdf":
                    if len(file_bytes) > MAX_PDF_BYTES:
                        raise ValueError(f"PDF 超过 {MAX_PDF_BYTES // 1024 // 1024} MB 限制。")
                    current_stage = "rendering"
                    yield _sse_event(
                        "stage",
                        stage=current_stage,
                        status="running",
                        message="正在将 PDF 渲染为逐页图像。",
                    )
                    pages = render_pdf_pages(file_bytes)
                    yield _sse_event(
                        "stage",
                        stage=current_stage,
                        status="done",
                        message=f"已渲染 {len(pages)} 页 PDF。",
                        page_count=len(pages),
                    )
                    current_stage = "vision"
                    yield _sse_event(
                        "stage",
                        stage=current_stage,
                        status="running",
                        message=f"正在调用视觉 MCP 解析 {len(pages)} 页内容和版式。",
                        page_count=len(pages),
                    )
                    resumes = [analyze_resume_pages(pages, filename)]
                    yield _sse_event(
                        "stage",
                        stage=current_stage,
                        status="done",
                        message="视觉内容和排版证据已结构化。",
                        page_count=len(pages),
                    )
                else:
                    with tempfile.TemporaryDirectory() as temp_dir:
                        temp_path = Path(temp_dir) / f"upload{suffix}"
                        temp_path.write_bytes(file_bytes)
                        resumes = load_resumes(temp_path)
                current_stage = "classification"
                yield _sse_event(
                    "stage",
                    stage=current_stage,
                    status="running",
                    message=f"正在对 {len(resumes)} 份简历进行初筛分类。",
                )
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
                            "source_format": resume.source_format,
                            "document_analysis": resume.document_analysis,
                        },
                    }
                    yield _sse_payload(payload)
                yield _sse_event(
                    "stage",
                    stage=current_stage,
                    status="done",
                    message=f"已完成 {total} 位候选人的初筛分类。",
                )
                yield _sse_event("done", total=total, message=f"导入完成，共 {total} 份简历。")
            except Exception as exc:
                yield _sse_event(
                    "error",
                    stage=current_stage,
                    message=str(exc),
                    retryable=current_stage in {"rendering", "vision", "classification"},
                )

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
        "source_format": _string_attr(row, "source_format", "text"),
        "document_analysis": _load_json(getattr(row, "document_analysis", "")) or {},
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
        "source_format": _string_attr(row, "source_format", "text"),
        "document_analysis": _load_json(getattr(row, "document_analysis", "")) or {},
    })


def _orm_to_evaluation(row) -> dict[str, Any]:
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


def _group_for_score(score: int) -> str:
    if score >= 80:
        return "shortlisted"
    if score >= 60:
        return "alternative"
    return "rejected"
