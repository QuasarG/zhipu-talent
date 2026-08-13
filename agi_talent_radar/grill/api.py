"""grill 画像澄清 API：/api/grill/*（鉴权由全局 middleware 负责，会话按 owner 隔离）。"""
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

from agi_talent_radar.grill import repository
from agi_talent_radar.grill.agent import chat_events
from agi_talent_radar.web.auth import current_user

GRILL_BP_NAME = "grill"


def _sse_response(events) -> Response:
    def generate():
        for event in events:
            yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"

    response = Response(stream_with_context(generate()), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    return response


def _require_owned_session(sid: str) -> tuple[dict[str, Any] | None, Any]:
    """取会话并校验属主；返回 (sess, None) 或 (None, error_response)。"""
    sess = repository.get_session_by_id(sid)
    if sess is None or sess.get("owner_id") != current_user().id:
        return None, (jsonify({"detail": "会话不存在"}), 404)
    return sess, None


def build_grill_blueprint() -> Blueprint:
    bp = Blueprint(GRILL_BP_NAME, __name__)

    # 进程启动清零：重启意味着所有 worker 线程已死，清掉残留 running 标志
    try:
        repository.clear_all_running()
    except Exception:  # noqa: BLE001 DB 尚未就绪时跳过
        pass

    @bp.post("/api/grill/sessions")
    def create_session():
        sess = repository.create_session(current_user().id)
        return jsonify({"session_id": sess["session_id"]}), 201

    @bp.get("/api/grill/sessions")
    def list_sessions():
        return jsonify({"sessions": repository.list_sessions(current_user().id)})

    @bp.delete("/api/grill/sessions/<sid>")
    def delete_session(sid: str):
        n = repository.delete_sessions([sid], current_user().id)
        if n == 0:
            return jsonify({"detail": "会话不存在"}), 404
        return jsonify({"deleted": n})

    @bp.post("/api/grill/sessions/batch-delete")
    def batch_delete_sessions():
        body = request.get_json(silent=True) or {}
        sids = [str(s) for s in body.get("session_ids") or [] if str(s).strip()]
        if not sids:
            return jsonify({"detail": "session_ids 必填"}), 400
        return jsonify({"deleted": repository.delete_sessions(sids, current_user().id)})

    @bp.get("/api/grill/sessions/<sid>/state")
    def get_state(sid: str):
        sess, err = _require_owned_session(sid)
        if err is not None:
            return err
        return jsonify(sess)

    @bp.get("/api/grill/sessions/<sid>/deliverables")
    def get_deliverables(sid: str):
        sess, err = _require_owned_session(sid)
        if err is not None:
            return err
        if not sess["deliverables"]:
            return jsonify({"detail": "尚未生成需求包"}), 404
        return jsonify(sess["deliverables"])

    @bp.post("/api/grill/sessions/<sid>/deliverables/regenerate")
    def regenerate_deliverables(sid: str):
        sess, err = _require_owned_session(sid)
        if err is not None:
            return err
        if not sess["deliverables"]:
            return jsonify({"detail": "需求包尚未生成，无法重新生成"}), 400
        from agi_talent_radar.grill.tools import generate_deliverables

        try:
            deliverables = generate_deliverables(sess)
        except Exception as exc:  # noqa: BLE001 失败不动旧 deliverables
            return jsonify({"detail": f"生成失败：{exc}"}), 500
        repository.save_session(sid, deliverables=deliverables)
        return jsonify(deliverables)

    @bp.post("/api/grill/chat")
    def chat():
        body = request.get_json(silent=True) or {}
        sid = str(body.get("session_id") or "").strip()
        message = str(body.get("message") or "").strip()
        if not sid or not message:
            return jsonify({"detail": "session_id 与 message 必填"}), 400
        sess, err = _require_owned_session(sid)
        if err is not None:
            return err
        # 并发闸门：抢占 running 标志，同一会话上一条还在跑则拒绝
        if not repository.try_set_running(sid):
            return jsonify({"detail": "上一条回复还在生成中，请稍候"}), 409
        return _sse_response(chat_events(sid, message))

    return bp
