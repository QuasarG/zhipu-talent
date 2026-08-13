"""grill SSE 桥接：同步 Agent 循环（回调式 emit）→ 工作线程 + 队列 → generator。

running 标志的抢占由 api 层 try_set_running 完成；worker 跑完负责清零。
"""
from __future__ import annotations

import queue
import threading
from typing import Any, Iterator

from agi_talent_radar.grill import repository


def chat_events(session_id: str, message: str) -> Iterator[dict[str, Any]]:
    from agi_talent_radar.grill.loop import run_agent

    events: queue.Queue = queue.Queue()

    def emit(type_: str, payload: dict[str, Any]) -> None:
        events.put({"type": type_, "payload": payload})

    def worker() -> None:
        try:
            run_agent(session_id, message, emit)
        except Exception as exc:  # noqa: BLE001
            emit("error", {"message": str(exc)})
            emit("done", {"status": "error"})
        finally:
            # SSE 断连不影响 worker：跑完才清 running，前端据此轮询恢复
            repository.clear_running(session_id)
            events.put(None)

    threading.Thread(target=worker, daemon=True).start()
    while True:
        item = events.get()
        if item is None:
            break
        yield item


__all__ = ["chat_events"]
