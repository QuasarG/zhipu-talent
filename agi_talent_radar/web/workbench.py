from __future__ import annotations

import json
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from queue import Queue
from typing import Any

from flask import Flask, Response, jsonify, render_template, request, stream_with_context

from agi_talent_radar.core.import_agent import run_import_agent_stream
from agi_talent_radar.core.io import load_resumes
from agi_talent_radar.core.models import CandidateEvaluation, CandidateResume
from agi_talent_radar.core.resume_ingestion import MAX_PDF_BYTES, analyze_resume_pages, render_pdf_pages
from agi_talent_radar.core.runner import run_candidate_stream


ROOT = Path(__file__).resolve().parents[2]
VALID_GROUPS = {"pending", "shortlisted", "alternative", "rejected"}
VALID_IMPORT_SUFFIXES = {".pdf", ".jsonl", ".md", ".txt"}
MAX_BATCH_FILES = 50
MAX_BATCH_BYTES = 200 * 1024 * 1024
MAX_PARALLEL_IMPORTS = 5


class ImportFileError(ValueError):
    def __init__(self, stage: str, message: str):
        super().__init__(message)
        self.stage = stage


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
            from agi_talent_radar.core.database import (
                get_candidate_with_latest_evaluation,
                get_session,
                start_evaluation_run,
            )

            with get_session() as session:
                candidate_orm, _ = get_candidate_with_latest_evaluation(session, candidate_id)
                if not candidate_orm:
                    return jsonify({"detail": "候选人不存在"}), 404
                resume = _orm_to_resume(candidate_orm)
                evaluation_run = start_evaluation_run(session, candidate_id)
                evaluation_run_id = evaluation_run.id
        except Exception as exc:
            return jsonify({"detail": f"读取候选人失败: {exc}"}), 500

        def generate():
            evaluation = None
            try:
                for event in run_candidate_stream(resume):
                    if event["type"] == "node":
                        from agi_talent_radar.core.database import get_session, record_node_event

                        with get_session() as session:
                            record_node_event(session, evaluation_run_id, event)
                    if event["type"] == "result":
                        evaluation = CandidateEvaluation.model_validate(event["result"])
                        evaluation.id = candidate_id
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

                if evaluation:
                    from agi_talent_radar.core.database import get_session, move_candidate_group, save_evaluation

                    with get_session() as session:
                        save_evaluation(session, evaluation, evaluation_id=evaluation_run_id)
                        group = _group_for_score(evaluation.overall_score)
                        move_candidate_group(session, candidate_id, group)
            except Exception as exc:
                from agi_talent_radar.core.database import fail_evaluation_run, get_session

                with get_session() as session:
                    fail_evaluation_run(session, evaluation_run_id, exc)
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
        uploaded_files = request.files.getlist("files")
        if not uploaded_files:
            single_file = request.files.get("file")
            uploaded_files = [single_file] if single_file else []
        uploaded_files = [file for file in uploaded_files if file and file.filename]
        if not uploaded_files:
            return jsonify({"detail": "请上传 .pdf / .jsonl / .md / .txt 简历文件"}), 400
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
            raise ValueError("仅支持 .pdf / .jsonl / .md / .txt 文件")
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
            current_stage = "rendering"
            yield _file_event(
                "stage",
                file_id,
                filename,
                file_index,
                file_total,
                stage=current_stage,
                status="running",
                message="正在将 PDF 渲染为逐页图像。",
            )
            pages = render_pdf_pages(file_bytes)
            yield _file_event(
                "stage",
                file_id,
                filename,
                file_index,
                file_total,
                stage=current_stage,
                status="done",
                message=f"已渲染 {len(pages)} 页 PDF。",
                page_count=len(pages),
            )
            current_stage = "vision"
            yield _file_event(
                "stage",
                file_id,
                filename,
                file_index,
                file_total,
                stage=current_stage,
                status="running",
                message=f"正在调用视觉 MCP 解析 {len(pages)} 页内容和版式。",
                page_count=len(pages),
            )
            resumes = [analyze_resume_pages(pages, filename)]
            yield _file_event(
                "stage",
                file_id,
                filename,
                file_index,
                file_total,
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
        yield _file_event(
            "stage",
            file_id,
            filename,
            file_index,
            file_total,
            stage=current_stage,
            status="running",
            message=f"正在对 {len(resumes)} 份简历进行初筛分类。",
        )
        resume_by_id = {resume.id: resume for resume in resumes}
        classifications = list(run_import_agent_stream(resumes, persist=True))
        candidate_total = len(classifications)
        for candidate_index, classification in enumerate(classifications, start=1):
            resume = resume_by_id[classification.id]
            yield _file_event(
                "candidate",
                file_id,
                filename,
                file_index,
                file_total,
                index=candidate_index,
                total=candidate_total,
                candidate=_imported_candidate_payload(classification, resume),
            )
        yield _file_event(
            "stage",
            file_id,
            filename,
            file_index,
            file_total,
            stage=current_stage,
            status="done",
            message=f"已完成 {candidate_total} 位候选人的初筛分类。",
        )
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


def _imported_candidate_payload(classification, resume: CandidateResume) -> dict[str, Any]:
    return {
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
    }


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


def _group_for_score(score: int) -> str:
    if score >= 80:
        return "shortlisted"
    if score >= 60:
        return "alternative"
    return "rejected"
