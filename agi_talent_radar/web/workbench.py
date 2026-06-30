from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template, request

from agi_talent_radar.core.runner import run_batch_from_file


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = ROOT / "10_ai_phd_resumes.jsonl"
DEFAULT_OUTPUT = ROOT / "outputs" / "talent_evaluations.json"


def create_app() -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config["JSON_AS_ASCII"] = False

    @app.get("/")
    def index() -> str:
        return render_template("workbench.html")

    @app.get("/api/evaluations")
    def evaluations():
        if DEFAULT_OUTPUT.exists():
            return jsonify(_load_json(DEFAULT_OUTPUT))
        result = run_batch_from_file(DEFAULT_INPUT, ROOT / "outputs")
        return jsonify(result.model_dump())

    @app.post("/api/evaluate-sample")
    def evaluate_sample():
        result = run_batch_from_file(DEFAULT_INPUT, ROOT / "outputs")
        return jsonify(result.model_dump())

    @app.post("/api/evaluate-upload")
    def evaluate_upload():
        file = request.files.get("file")
        if not file or not file.filename:
            return jsonify({"detail": "请上传 .jsonl / .md / .txt 简历文件"}), 400
        suffix = Path(file.filename).suffix.lower()
        if suffix not in {".jsonl", ".md", ".txt"}:
            return jsonify({"detail": "仅支持 .jsonl / .md / .txt 文件"}), 400
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir) / f"upload{suffix}"
            file.save(temp_path)
            result = run_batch_from_file(temp_path, Path(temp_dir))
            return jsonify(result.model_dump())

    return app


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


app = create_app()
