"""人才问答 Agent + 简历评估 API 蓝图。

- POST /api/knowledge/ask           SSE 流式问答（ReAct Agent）
- POST /api/knowledge/action        SSE 流式续跑（HITL 决策回填）
- GET/POST /api/conversations       会话列表 / 新建
- GET/PATCH/DELETE /api/conversations/<id>  消息列表 / 重命名 / 删除
- POST /api/resume-submissions/<id>/evaluate  同步评估 + 入库
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

from agi_talent_radar.core.database import get_session
from agi_talent_radar.core.db.orm import ChatMessageORM, ConversationORM
from agi_talent_radar.knowledge_agent.service import action_events, ask_events
from agi_talent_radar.services import talent_service
from agi_talent_radar.web.auth import current_user

KNOWLEDGE_BP_NAME = "knowledge"


def _sse_response(events) -> Response:
    def generate():
        for event in events:
            yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"

    response = Response(stream_with_context(generate()), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    return response


def _segment_text(message: ChatMessageORM) -> str:
    segments = (message.content or {}).get("segments") or []
    return "".join(
        str(seg.get("text") or "") for seg in segments if seg.get("type") == "text"
    )


def _conversation_to_dict(conv: ConversationORM) -> dict[str, Any]:
    last = conv.messages[-1] if conv.messages else None
    return {
        "id": conv.id,
        "title": conv.title,
        "created_at": str(conv.created_at or ""),
        "updated_at": str(conv.updated_at or ""),
        "message_count": len(conv.messages),
        "last_message": _segment_text(last)[:60] if last else "",
    }


def _message_to_dict(message: ChatMessageORM) -> dict[str, Any]:
    pending = dict(message.pending_action or {})
    pending.pop("llm_messages", None)  # 快照体积大，不下发
    return {
        "id": message.id,
        "conversation_id": message.conversation_id,
        "role": message.role,
        "content": message.content or {"segments": []},
        "citations": message.citations or [],
        "status": message.status,
        "pending_action": pending or None,
        "created_at": str(message.created_at or ""),
    }


def build_knowledge_blueprint():
    bp = Blueprint(KNOWLEDGE_BP_NAME, __name__)

    @bp.post("/api/knowledge/ask")
    def knowledge_ask():
        body = request.get_json(silent=True) or {}
        prompt = str(body.get("prompt", "")).strip()
        conversation_id = str(body.get("conversation_id") or "").strip()
        if not prompt:
            return jsonify({"detail": "prompt 不能为空。"}), 400
        user = current_user()
        with get_session() as session:
            conv = session.get(ConversationORM, conversation_id)
            if conv is None or conv.owner_id != user.id:
                return jsonify({"detail": "会话不存在。"}), 404
        return _sse_response(ask_events(conversation_id, prompt))

    @bp.post("/api/knowledge/action")
    def knowledge_action():
        body = request.get_json(silent=True) or {}
        conversation_id = str(body.get("conversation_id") or "").strip()
        action_id = str(body.get("action_id") or "").strip()
        decision = body.get("decision") or {}
        if not conversation_id or not action_id:
            return jsonify({"detail": "conversation_id 与 action_id 必填。"}), 400
        if not isinstance(decision, dict):
            return jsonify({"detail": "decision 必须是对象。"}), 400
        user = current_user()
        with get_session() as session:
            conv = session.get(ConversationORM, conversation_id)
            if conv is None or conv.owner_id != user.id:
                return jsonify({"detail": "会话不存在。"}), 404
        return _sse_response(action_events(conversation_id, action_id, decision))

    @bp.get("/api/conversations")
    def list_conversations():
        user = current_user()
        with get_session() as session:
            convs = (
                session.query(ConversationORM)
                .filter(ConversationORM.owner_id == user.id)
                .order_by(ConversationORM.updated_at.desc())
                .limit(100)
                .all()
            )
            return jsonify([_conversation_to_dict(conv) for conv in convs])

    @bp.post("/api/conversations")
    def create_conversation():
        user = current_user()
        with get_session() as session:
            conv = ConversationORM(owner_id=user.id)
            session.add(conv)
            session.commit()
            return jsonify(_conversation_to_dict(conv)), 201

    @bp.get("/api/conversations/<conversation_id>/messages")
    def list_messages(conversation_id: str):
        user = current_user()
        with get_session() as session:
            conv = session.get(ConversationORM, conversation_id)
            if conv is None or conv.owner_id != user.id:
                return jsonify({"detail": "会话不存在。"}), 404
            return jsonify([_message_to_dict(message) for message in conv.messages])

    @bp.patch("/api/conversations/<conversation_id>")
    def rename_conversation(conversation_id: str):
        body = request.get_json(silent=True) or {}
        title = str(body.get("title") or "").strip()
        if not title:
            return jsonify({"detail": "title 不能为空。"}), 400
        user = current_user()
        with get_session() as session:
            conv = session.get(ConversationORM, conversation_id)
            if conv is None or conv.owner_id != user.id:
                return jsonify({"detail": "会话不存在。"}), 404
            conv.title = title[:200]
            session.commit()
            return jsonify(_conversation_to_dict(conv))

    @bp.delete("/api/conversations/<conversation_id>")
    def delete_conversation(conversation_id: str):
        user = current_user()
        with get_session() as session:
            conv = session.get(ConversationORM, conversation_id)
            if conv is None or conv.owner_id != user.id:
                return jsonify({"detail": "会话不存在。"}), 404
            session.delete(conv)
            session.commit()
            return jsonify({"id": conversation_id, "deleted": True})

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
