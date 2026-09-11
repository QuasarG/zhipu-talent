# -*- coding: utf-8 -*-
"""Agent 协作事件流（agent-collab/v1）：把两条评估链路的真实执行事件翻译成统一信封。

契约见 docs/agent-collab-event-protocol.md。写入是旁路动作：不修改链路行为、
不参与评分；旧 JSON 轨迹（panel_trace / run_trace）保持原样继续工作。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import func
from sqlalchemy.orm import Session

from agi_talent_radar.core.db.orm import AgentCollabEventORM

PROTOCOL = "agent-collab/v1"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class _BaseTranslator:
    """公共信封状态：运行内 seq 分配、事件 ID、实例登记。"""

    def __init__(self, run_id: str, run_kind: str) -> None:
        self.run_id = str(run_id)
        self.run_kind = run_kind
        self._seq = -1
        self.instances: dict[str, dict[str, Any]] = {}

    def _envelope(
        self,
        event: dict[str, Any],
        *,
        at: str | None = None,
        instance_id: str | None = None,
        agent_type: str | None = None,
        task_id: str | None = None,
        task_kind: str | None = None,
        turn_no: int | None = None,
        message_id: str | None = None,
        cause_event_id: str | None = None,
    ) -> dict[str, Any]:
        self._seq += 1
        return {
            "protocol": PROTOCOL,
            "run_id": self.run_id,
            "run_kind": self.run_kind,
            "event_id": uuid4().hex,
            "seq": self._seq,
            "at": at or _now_iso(),
            "instance_id": instance_id,
            "agent_type": agent_type,
            "task_id": task_id,
            "task_kind": task_kind,
            "turn_no": turn_no,
            "message_id": message_id,
            "cause_event_id": cause_event_id,
            "event": event,
        }

    def run_event(self, event_type: str, **payload: Any) -> dict[str, Any]:
        """运行级事件（run.started/completed/failed/cancelled）。"""
        return self._envelope({"type": event_type, **payload})

    def ensure_instance(
        self, instance_id: str, agent_type: str, at: str | None = None,
    ) -> dict[str, Any] | None:
        """首次出现发 instance.created；重复出现返回 None（续派不新建实例）。"""
        if instance_id in self.instances:
            return None
        self.instances[instance_id] = {"agent_type": agent_type, "turns": 0}
        return self._envelope(
            {"type": "instance.created", "agent_type": agent_type},
            at=at, instance_id=instance_id, agent_type=agent_type,
        )


class PanelCollabTranslator(_BaseTranslator):
    """评审团链路：panel.py 原始 node 事件 → v1 信封。

    消费的原始字段：agent_id/agent_type/event_kind/status/message/target_id/
    detail/tool/call_id/mission_type/mission_goal/mission_status/ts。
    """

    def __init__(self, run_id: str) -> None:
        super().__init__(run_id, "panel")
        self._chair_round = 0
        self._planning_open = False
        self._dispatch_of: dict[str, dict[str, str]] = {}  # mission_id -> {event_id, message_id}

    def feed(self, raw: dict[str, Any]) -> list[dict[str, Any]]:
        if raw.get("type") != "node" or raw.get("phase") != "assessment":
            return []
        agent_id = str(raw.get("agent_id") or "")
        kind = str(raw.get("event_kind") or "status")
        status = str(raw.get("status") or "")
        at = str(raw.get("ts") or "") or None

        if agent_id == "chair":
            return self._feed_chair(raw, kind, status, at)
        if agent_id and agent_id in self.instances:
            return self._feed_worker(raw, agent_id, kind, status, at)
        return []  # 未见创建事件的孤立 worker 事件：跳过，不虚构实例

    def _feed_worker(
        self, raw: dict[str, Any], agent_id: str, kind: str, status: str, at: str | None,
    ) -> list[dict[str, Any]]:
        info = self.instances[agent_id]
        dispatch = self._dispatch_of.get(agent_id, {})
        task = dict(
            instance_id=agent_id, agent_type=info["agent_type"], task_id=agent_id,
            task_kind="mission", turn_no=max(info["turns"], 1),
        )
        detail = raw.get("detail") or {}
        out: list[dict[str, Any]] = []

        if kind == "request":
            out.append(self._envelope({"type": "task.started"}, at=at,
                                      cause_event_id=dispatch.get("event_id"), **task))
        elif kind == "message":
            message_id = uuid4().hex
            out.append(self._envelope(
                {"type": "message.started", "sender": agent_id, "receiver": "chair"},
                at=at, message_id=message_id, **task))
            out.append(self._envelope(
                {"type": "message.completed", "sender": agent_id, "receiver": "chair",
                 "text": raw.get("message", "")},
                at=at, message_id=message_id, cause_event_id=out[-1]["event_id"], **task))
        elif kind == "tool_call":
            out.append(self._envelope(
                {"type": "tool.started", "call_id": raw.get("call_id"), "tool": raw.get("tool"),
                 "args_summary": detail.get("输入")},
                at=at, **task))
        elif kind == "tool_result":
            summary = str(detail.get("返回摘要") or "")
            out.append(self._envelope(
                {"type": "tool.completed", "call_id": raw.get("call_id"), "tool": raw.get("tool"),
                 "status": "error" if "未授权" in summary else "ok", "summary": summary},
                at=at, **task))
        elif kind == "handoff" and raw.get("target_id") == "chair":
            out.append(self._envelope(
                {"type": "result.returned", "sender": agent_id, "receiver": "chair",
                 "artifact_id": f"findings:{agent_id}",
                 "digest": str(detail.get("主席收到的摘要") or raw.get("message") or ""),
                 "succeeded": str(raw.get("mission_status") or "") != "failed",
                 "error": detail.get("错误") or None,
                 "reply_to": dispatch.get("message_id")},
                at=at, message_id=uuid4().hex, cause_event_id=dispatch.get("event_id"), **task))
        elif kind == "error":
            out.append(self._envelope(
                {"type": "task.failed", "error": raw.get("message", "")}, at=at, **task))
        elif kind == "status" and status == "done":
            out.append(self._envelope({"type": "task.completed"}, at=at, **task))
        # 其余 worker 进度节点是过程噪音，不进入事件流
        return out

    def _feed_chair(
        self, raw: dict[str, Any], kind: str, status: str, at: str | None,
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        chair = dict(instance_id="chair", agent_type="chair")

        if kind == "request":
            self._chair_round += 1
            self._planning_open = True
            out.append(self._envelope(
                {"type": "planning.started", "round_no": self._chair_round,
                 "context": (raw.get("detail") or {}).get("已收到结论")},
                at=at, **chair))
        elif kind == "dispatch":
            mission_id = str(raw.get("target_id") or "")
            if not mission_id:
                return out
            created = self.ensure_instance(mission_id, str(raw.get("mission_type") or "generic"), at)
            if created is not None:
                out.append(created)
            self.instances[mission_id]["turns"] += 1
            detail = raw.get("detail") or {}
            message_id = uuid4().hex
            self._append_closed_planning(out, at, **chair)
            out.append(self._envelope(
                {"type": "task.dispatched", "sender": "chair", "receiver": mission_id,
                 "instruction": detail.get("目标") or raw.get("mission_goal") or "",
                 "files": detail.get("材料") or [], "questions": detail.get("问题") or [],
                 "note": detail.get("续派指令") or "", "reuse_context": bool(detail.get("复用上下文"))},
                at=at, message_id=message_id, turn_no=self.instances[mission_id]["turns"], **chair))
            self._dispatch_of[mission_id] = {"event_id": out[-1]["event_id"], "message_id": message_id}
        elif kind == "handoff" and raw.get("target_id") == "system":
            self._append_closed_planning(out, at, **chair)
            out.append(self._envelope(
                {"type": "result.returned", "sender": "chair", "receiver": "system",
                 "artifact_id": "synthesis",
                 "digest": json.dumps(raw.get("detail") or {}, ensure_ascii=False, default=str)[:300],
                 "succeeded": True},
                at=at, message_id=uuid4().hex, **chair))
        elif kind == "status" and status == "done":
            self._append_closed_planning(out, at, **chair)
        return out

    def _close_planning(self, at: str | None, **chair: Any) -> dict[str, Any] | None:
        if not self._planning_open:
            return None
        self._planning_open = False
        return self._envelope(
            {"type": "planning.completed", "round_no": self._chair_round}, at=at, **chair)

    def _append_closed_planning(self, out: list[dict[str, Any]], at: str | None, **chair: Any) -> None:
        closed = self._close_planning(at, **chair)
        if closed is not None:
            out.append(closed)


_ADMISSION_TASK_KINDS = (
    ("task_score:", "score"),
    ("evidence_repair:", "repair"),
    ("capability_mapping", "mapping"),
    ("overall_review", "review"),
)


class AdmissionCollabTranslator(_BaseTranslator):
    """准入链路：evaluator._Trace 事件 → v1 信封。系统编排节点不建 Agent 实例。

    evidence_repair 与 task_score 是同一个评分 Agent 的重评回合：归并为同一实例，
    避免群里出现成对的同名成员；回传 digest 带任务标题，保证消息人类可读。
    """

    def __init__(self, run_id: str) -> None:
        super().__init__(run_id, "admission")
        self._returned_tasks: set[str] = set()
        self._settled_tasks: set[str] = set()

    @staticmethod
    def _task_kind(node_id: str) -> str:
        for prefix, kind in _ADMISSION_TASK_KINDS:
            if node_id.startswith(prefix):
                return kind
        return "step"

    @staticmethod
    def _instance_of(agent_id: str) -> str:
        """evidence_repair:{task} 复用 task_score:{task} 的实例。"""
        if agent_id.startswith("evidence_repair:"):
            return "task_score:" + agent_id.split(":", 1)[1]
        return agent_id

    @staticmethod
    def _digest(raw: dict[str, Any]) -> str:
        text = str(raw.get("summary") or raw.get("message") or "")
        label = str(raw.get("label") or "")
        node_id = str(raw.get("node_id") or "")
        if text and label and node_id.startswith(("task_score:", "evidence_repair:")):
            return f"【{label}】{text}"
        return text

    def feed(self, raw: dict[str, Any]) -> list[dict[str, Any]]:
        agent_id = str(raw.get("agent_id") or "")
        agent_type = str(raw.get("agent_type") or "")
        node_id = str(raw.get("node_id") or "")
        kind = str(raw.get("event_kind") or "status")
        status = str(raw.get("status") or "")
        at = str(raw.get("at") or "") or None
        if not agent_id or agent_type == "system" or not node_id:
            return []
        instance_id = self._instance_of(agent_id)

        task = dict(
            instance_id=instance_id, agent_type=agent_type, task_id=node_id,
            task_kind=self._task_kind(node_id), turn_no=1,
        )
        out: list[dict[str, Any]] = []

        if kind == "handoff":
            out.append(self._envelope(
                {"type": "result.returned",
                 "sender": instance_id,
                 "receiver": str(raw.get("target_id") or "system"),
                 "digest": self._digest(raw),
                 "succeeded": status != "failed"},
                at=at, message_id=uuid4().hex, **task))
            self._returned_tasks.add(node_id)
            if status != "failed" and node_id not in self._settled_tasks:
                # 链路以 handoff 承载终态：回传后补 task.completed，任务统计才有终点
                self._settled_tasks.add(node_id)
                out.append(self._envelope({"type": "task.completed"},
                                          at=at, cause_event_id=out[-1]["event_id"], **task))
            return out

        created = self.ensure_instance(instance_id, agent_type, at)
        if created is not None:
            out.append(created)

        if status == "running":
            out.append(self._envelope({"type": "task.started"}, at=at, **task))
        elif status == "completed":
            if node_id not in self._settled_tasks:
                self._settled_tasks.add(node_id)
                out.append(self._envelope({"type": "task.completed"}, at=at, **task))
            if node_id not in self._returned_tasks:
                self._returned_tasks.add(node_id)
                out.append(self._envelope(
                    {"type": "result.returned", "sender": instance_id, "receiver": "system",
                     "digest": self._digest(raw), "succeeded": True},
                    at=at, message_id=uuid4().hex,
                    cause_event_id=out[-1]["event_id"], **task))
        elif status == "failed" or kind == "error":
            self._settled_tasks.add(node_id)
            out.append(self._envelope(
                {"type": "task.failed", "error": raw.get("error") or raw.get("summary") or ""},
                at=at, **task))
        return out


def append_collab_events(session: Session, envelopes: list[dict[str, Any]]) -> None:
    """把信封写入事件表；调用方负责 commit 与事务边界。"""
    for env in envelopes:
        session.add(AgentCollabEventORM(
            event_id=env["event_id"], run_id=env["run_id"], run_kind=env["run_kind"],
            seq=env["seq"], protocol=env["protocol"], instance_id=env["instance_id"],
            agent_type=env["agent_type"], task_id=env["task_id"], task_kind=env["task_kind"],
            turn_no=env["turn_no"], message_id=env["message_id"],
            cause_event_id=env["cause_event_id"], event=env["event"],
        ))


def list_collab_events(
    session: Session, run_kind: str, run_id: str, after_seq: int = -1, limit: int = 500,
) -> tuple[list[dict[str, Any]], int]:
    """按游标读取事件；返回 (信封列表, 最新 seq)。断线后带 after_seq 续传。"""
    rows = (
        session.query(AgentCollabEventORM)
        .filter(
            AgentCollabEventORM.run_kind == run_kind,
            AgentCollabEventORM.run_id == run_id,
            AgentCollabEventORM.seq > after_seq,
        )
        .order_by(AgentCollabEventORM.seq.asc())
        .limit(limit)
        .all()
    )
    events = [_row_to_envelope(row) for row in rows]
    latest = (
        session.query(func.max(AgentCollabEventORM.seq))
        .filter(AgentCollabEventORM.run_kind == run_kind, AgentCollabEventORM.run_id == run_id)
        .scalar()
    )
    return events, int(latest if latest is not None else -1)


def _row_to_envelope(row: AgentCollabEventORM) -> dict[str, Any]:
    return {
        "protocol": row.protocol, "run_id": row.run_id, "run_kind": row.run_kind,
        "event_id": row.event_id, "seq": row.seq,
        "at": row.created_at.replace(tzinfo=timezone.utc).isoformat(timespec="milliseconds")
        if row.created_at else None,
        "instance_id": row.instance_id, "agent_type": row.agent_type,
        "task_id": row.task_id, "task_kind": row.task_kind, "turn_no": row.turn_no,
        "message_id": row.message_id, "cause_event_id": row.cause_event_id,
        "event": row.event,
    }
