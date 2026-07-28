"""人才知识 Agent + 简历评估 API 蓝图（阶段 5/4 集成）。

把 knowledge_agent.service 和 talent_service.evaluate_resume 挂到 HTTP：

- POST /api/knowledge/ask           SSE 流式知识问答
- POST /api/resume-submissions/<id>/evaluate  同步评估 + 入库（封装 evaluate_resume）
"""
from __future__ import annotations

import json
from typing import Any

from flask import (  # type: ignore[import-not-found]
    Blueprint,
    Response,
    jsonify,
    request,
    stream_with_context,
)

from agi_talent_radar.knowledge_agent import ask_talent_knowledge
from agi_talent_radar.services import talent_service


KNOWLEDGE_BP_NAME = "knowledge"


def build_knowledge_blueprint():
    bp = Blueprint(KNOWLEDGE_BP_NAME, __name__)

    @bp.post("/api/knowledge/ask")
    def knowledge_ask():
        body = request.get_json(silent=True) or {}
        prompt = str(body.get("prompt", "")).strip()
        conversation_id = str(body.get("conversation_id") or "default")

        if not prompt:
            return jsonify({"detail": "prompt 不能为空。"}), 400

        connectors = None  # 默认走真实连接器；测试可注入

        def generate():
            for event in ask_talent_knowledge(
                conversation_id=conversation_id,
                prompt=prompt,
                connectors=connectors,
            ):
                yield f"data: {json.dumps(event.model_dump(), ensure_ascii=False)}\n\n"

        response = Response(stream_with_context(generate()), mimetype="text/event-stream")
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["X-Accel-Buffering"] = "no"
        return response

    @bp.post("/api/resume-submissions/<submission_id>/evaluate")
    def evaluate_submission(submission_id: str):
        """同步评估 + 入库（封装 talent_service.evaluate_resume）。

        评估失败时返回 500 + error_message；不创建 Candidate。
        """
        try:
            result = talent_service.evaluate_resume(submission_id)
            return jsonify(result)
        except ValueError as exc:
            return jsonify({"detail": str(exc)}), 404
        except Exception as exc:  # noqa: BLE001
            return jsonify({"detail": f"评估失败：{exc}"}), 500

    return bp


__all__ = [
    "KNOWLEDGE_BP_NAME",
    "build_knowledge_blueprint",
]