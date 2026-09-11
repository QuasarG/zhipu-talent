"""评估与问答共用的事件词汇；快照只保存 text/tool/spawn 段。"""
from __future__ import annotations

from copy import deepcopy
from queue import Queue
from threading import Thread
from typing import Any


def apply_event(segments: list[dict[str, Any]], event: dict[str, Any]) -> None:
    kind, payload = event["type"], event.get("payload", {})
    spawn_id = payload.get("spawn_id")
    spawn = next((s for s in segments if s.get("type") == "spawn"
                  and s.get("spawn_id") == spawn_id), None) if spawn_id else None
    if kind == "spawn_start":
        if spawn is None:
            spawn = {"type": "spawn", "children": []}
            segments.append(spawn)
        spawn.update(payload, status="running", summary="")
        return
    if kind == "spawn_end":
        if spawn is not None:
            spawn.update(payload)
        return
    target = spawn["children"] if spawn is not None else segments
    if spawn_id and spawn is None:
        raise ValueError(f"Unknown spawn: {spawn_id}")
    if kind in {"answer_delta", "thinking_delta"}:
        segment_type = "text" if kind == "answer_delta" else "thinking"
        key = payload.get("segment_id")
        existing = next((s for s in target if key and s.get("_key") == key), None)
        if existing is None and not key and target and target[-1]["type"] == segment_type:
            existing = target[-1]
        if existing is None:
            existing = {"type": segment_type, "text": ""}
            if key:
                existing["_key"] = key
            target.append(existing)
        existing["text"] = ("" if payload.get("replace") else existing["text"]) + payload.get("text", "")
    elif kind == "tool_start":
        target.append({"type": "tool", **{k: v for k, v in payload.items() if k != "spawn_id"}})
    elif kind == "tool_end":
        tool = next((s for s in reversed(target) if s.get("type") == "tool"
                     and s.get("call_id") == payload.get("call_id")), None)
        if tool is not None:
            tool.update({k: v for k, v in payload.items() if k != "spawn_id"})


def stream_call(messages, tools, **kwargs):
    """把模型回调桥接为实时 generator，保留最终工具调用和异常。"""
    from agi_talent_radar.core.llm_client import call_llm_tools

    queue: Queue = Queue()
    def work():
        seen = False
        def delta(text):
            nonlocal seen
            seen = True
            queue.put({"type": "sse", "event": {"type": "answer_delta", "payload": {"text": text}}})
        try:
            result = call_llm_tools(messages, tools, on_delta=delta, **kwargs)
            if not seen and result.get("text"):
                delta(str(result["text"]))
            queue.put((result, None))
        except Exception as exc:
            queue.put((None, exc))
    Thread(target=work, daemon=True).start()
    while True:
        item = queue.get()
        if isinstance(item, tuple):
            result, error = item
            if error:
                raise error
            return result
        yield deepcopy(item)
