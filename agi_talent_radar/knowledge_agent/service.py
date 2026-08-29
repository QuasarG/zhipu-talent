"""人才问答 Agent 服务入口：把同步 ReAct 循环桥接成 SSE 事件流。

Agent 循环是同步回调式（emit），用 工作线程 + 队列 转成 generator；
DB session 在工作线程内开启与关闭，不泄漏到 Flask 请求线程。
"""
from __future__ import annotations

import queue
import threading
from typing import Any, Callable, Iterator


def ask_events(conversation_id: str, prompt: str, lang: str = "zh") -> Iterator[dict[str, Any]]:
    """POST /api/knowledge/ask 的事件流。"""
    from agi_talent_radar.knowledge_agent.agent import run_agent

    return _stream(lambda session, emit: run_agent(session, conversation_id, prompt, emit, lang), lang)


def action_events(
    conversation_id: str, action_id: str, decision: dict[str, Any], lang: str = "zh"
) -> Iterator[dict[str, Any]]:
    """POST /api/knowledge/action 的事件流（HITL 决策后续跑）。"""
    from agi_talent_radar.knowledge_agent.agent import resume_agent

    return _stream(
        lambda session, emit: resume_agent(session, conversation_id, action_id, decision, emit, lang),
        lang,
    )


def _stream(run: Callable[[Any, Callable], None], lang: str = "zh") -> Iterator[dict[str, Any]]:
    from agi_talent_radar.core.database import get_session

    events: queue.Queue = queue.Queue()

    def emit(type_: str, payload: dict[str, Any]) -> None:
        events.put({"type": type_, "payload": payload})

    def worker() -> None:
        try:
            with get_session() as session:
                run(session, emit)
        except Exception:  # noqa: BLE001
            message = (
                "本次回答未能完成，请稍后重试"
                if lang == "zh"
                else "This answer could not be completed. Please try again later"
            )
            emit("error", {"message": message})
            emit("done", {"status": "completed"})
        finally:
            events.put(None)

    threading.Thread(target=worker, daemon=True).start()
    while True:
        item = events.get()
        if item is None:
            break
        yield item


__all__ = ["ask_events", "action_events"]
