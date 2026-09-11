# -*- coding: utf-8 -*-
"""agent-collab/v1 翻译器与事件表测试：续派、并行回传去重、失败恢复、游标读取。"""
from __future__ import annotations

import unittest
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from agi_talent_radar.core.collab_events import (
    AdmissionCollabTranslator,
    PanelCollabTranslator,
    append_collab_events,
    list_collab_events,
)
from agi_talent_radar.core.db.migrations import LATEST_SCHEMA_VERSION, ensure_schema


def panel_node(**fields) -> dict:
    return {"type": "node", "phase": "assessment", "status": "running",
            "message": "", **fields}


def admission_event(**fields) -> dict:
    return {"node_id": "", "status": "running", **fields}


class PanelTranslatorTests(unittest.TestCase):
    def feed_all(self, translator, events):
        out = []
        for raw in events:
            out.extend(translator.feed(raw))
        return out

    def types_of(self, envelopes):
        return [env["event"]["type"] for env in envelopes]

    def test_full_lifecycle_with_re_dispatch(self) -> None:
        tr = PanelCollabTranslator("9001")
        events = self.feed_all(tr, [
            panel_node(ts="2026-09-08T10:00:00+00:00", agent_id="chair", agent_type="chair",
                       event_kind="request", message="主席正在审阅"),
            panel_node(ts="2026-09-08T10:00:01+00:00", agent_id="chair", agent_type="chair",
                       event_kind="dispatch", target_id="m1", mission_type="verify",
                       mission_goal="核实贡献",
                       detail={"目标": "核实贡献", "材料": ["项目说明.pdf"], "问题": [],
                               "续派指令": "", "复用上下文": False}),
            panel_node(ts="2026-09-08T10:00:02+00:00", agent_id="m1", agent_type="verify",
                       event_kind="request", mission_id="m1"),
            panel_node(ts="2026-09-08T10:00:03+00:00", agent_id="m1", agent_type="verify",
                       event_kind="tool_call", tool="read_pages", call_id="c1",
                       detail={"输入": {"file": "项目说明.pdf"}}),
            panel_node(ts="2026-09-08T10:00:05+00:00", agent_id="m1", agent_type="verify",
                       event_kind="tool_result", tool="read_pages", call_id="c1",
                       detail={"输入": {}, "返回摘要": "找到说明"}),
            panel_node(ts="2026-09-08T10:00:06+00:00", agent_id="m1", agent_type="verify",
                       event_kind="message", message="正文输出"),
            panel_node(ts="2026-09-08T10:00:07+00:00", agent_id="m1", agent_type="verify",
                       status="done", message="完成（3 条结论）"),
            panel_node(ts="2026-09-08T10:00:08+00:00", agent_id="m1", agent_type="verify",
                       event_kind="handoff", target_id="chair", mission_status="done",
                       detail={"主席收到的摘要": "已确认评测模块贡献", "错误": ""}),
            # 续派：同实例第二轮
            panel_node(ts="2026-09-08T10:01:00+00:00", agent_id="chair", agent_type="chair",
                       event_kind="request", message="主席正在审阅"),
            panel_node(ts="2026-09-08T10:01:01+00:00", agent_id="chair", agent_type="chair",
                       event_kind="dispatch", target_id="m1", mission_type="verify",
                       detail={"目标": "边界复核", "复用上下文": True}),
            panel_node(ts="2026-09-08T10:01:02+00:00", agent_id="m1", agent_type="verify",
                       event_kind="request"),
            panel_node(ts="2026-09-08T10:01:03+00:00", agent_id="m1", agent_type="verify",
                       status="done", message="完成"),
            panel_node(ts="2026-09-08T10:01:04+00:00", agent_id="m1", agent_type="verify",
                       event_kind="handoff", target_id="chair", mission_status="done",
                       detail={"主席收到的摘要": "复核完成"}),
            # 收队
            panel_node(ts="2026-09-08T10:02:00+00:00", agent_id="chair", agent_type="chair",
                       event_kind="handoff", target_id="system", detail={"综合意见": []}),
            panel_node(ts="2026-09-08T10:02:01+00:00", agent_id="chair", agent_type="chair",
                       status="done", message="评审团收工"),
        ])

        types = self.types_of(events)
        # 实例只创建一次，续派不新建（首事件是主席规划开始）
        self.assertEqual(types.count("instance.created"), 1)
        self.assertEqual(events[0]["event"]["type"], "planning.started")
        self.assertEqual(events[1]["event"]["type"], "instance.created")
        self.assertEqual(events[1]["instance_id"], "m1")
        # 派工两次，轮次递增
        dispatches = [e for e in events if e["event"]["type"] == "task.dispatched"]
        self.assertEqual(len(dispatches), 2)
        self.assertEqual(dispatches[0]["turn_no"], 1)
        self.assertEqual(dispatches[1]["turn_no"], 2)
        self.assertTrue(dispatches[1]["event"]["reuse_context"])
        # 第二次 task.started 因果指向第二次 dispatch
        starts = [e for e in events if e["event"]["type"] == "task.started"]
        self.assertEqual(len(starts), 2)
        self.assertEqual(starts[1]["cause_event_id"], dispatches[1]["event_id"])
        # 回传回复派工消息
        returns = [e for e in events if e["event"]["type"] == "result.returned"
                   and e["event"]["receiver"] == "chair"]
        self.assertEqual(len(returns), 2)
        self.assertEqual(returns[1]["event"]["reply_to"], dispatches[1]["message_id"])
        self.assertTrue(returns[1]["event"]["succeeded"])
        # 规划成对 + 收队
        self.assertEqual(types.count("planning.started"), 2)
        self.assertEqual(types.count("planning.completed"), 2)
        self.assertEqual(events[-1]["event"]["type"], "result.returned")
        self.assertEqual(events[-1]["event"]["receiver"], "system")
        # 信封不变量：seq 连续、event_id 唯一、run 标识一致
        self.assertEqual([e["seq"] for e in events], list(range(len(events))))
        self.assertEqual(len({e["event_id"] for e in events}), len(events))
        self.assertTrue(all(e["run_id"] == "9001" and e["run_kind"] == "panel" for e in events))

    def test_failure_and_noise(self) -> None:
        tr = PanelCollabTranslator("9002")
        events = self.feed_all(tr, [
            panel_node(agent_id="chair", event_kind="dispatch", target_id="m1",
                       mission_type="deep_read", detail={"目标": "深读"}),
            # 孤立 worker 事件（未注册实例）不产生输出
            panel_node(agent_id="ghost", agent_type="verify", event_kind="request"),
            # 进度噪音不进入事件流
            panel_node(agent_id="m1", event_kind="status", message="正在读取任务简报"),
            panel_node(agent_id="m1", event_kind="error", message="材料读取失败"),
            panel_node(agent_id="m1", event_kind="handoff", target_id="chair",
                       mission_status="failed", detail={"主席收到的摘要": "失败", "错误": "读取超时"}),
            # 准备阶段事件忽略
            {"type": "node", "phase": "preparation", "message": "材料整备"},
        ])
        types = self.types_of(events)
        self.assertNotIn("task.started", types)
        self.assertIn("task.failed", types)
        failed_return = [e for e in events if e["event"]["type"] == "result.returned"][0]
        self.assertFalse(failed_return["event"]["succeeded"])
        self.assertEqual(failed_return["event"]["error"], "读取超时")


class AdmissionTranslatorTests(unittest.TestCase):
    def test_parallel_tasks_and_return_dedup(self) -> None:
        tr = AdmissionCollabTranslator("run-uuid-1")
        events = []
        for raw in [
            admission_event(node_id="capability_mapping", agent_id="capability_mapping",
                            agent_type="mapper", status="running", at="t1"),
            admission_event(node_id="capability_mapping", agent_id="capability_mapping",
                            agent_type="mapper", status="completed", at="t2", summary="映射完成"),
            # 两个并行 scorer：running → handoff → completed
            admission_event(node_id="task_score:t1", agent_id="task_score:t1",
                            agent_type="task_scorer", status="running", at="t3"),
            admission_event(node_id="task_score:t2", agent_id="task_score:t2",
                            agent_type="task_scorer", status="running", at="t4"),
            admission_event(node_id="task_score:t1", agent_id="task_score:t1",
                            agent_type="task_scorer", event_kind="handoff",
                            target_id="system", status="completed", summary="任务一完成", at="t5"),
            admission_event(node_id="task_score:t1", agent_id="task_score:t1",
                            agent_type="task_scorer", status="completed", at="t6"),
            admission_event(node_id="task_score:t2", agent_id="task_score:t2",
                            agent_type="task_scorer", status="completed", at="t7", summary="任务二完成"),
            # 系统编排节点不建实例
            admission_event(node_id="admission_decision", agent_id="system",
                            agent_type="system", status="completed"),
            # 总审失败
            admission_event(node_id="overall_review", agent_id="overall_review",
                            agent_type="reviewer", status="running", at="t8"),
            admission_event(node_id="overall_review", agent_id="overall_review",
                            agent_type="reviewer", status="failed", at="t9", error="审阅超时"),
        ]:
            events.extend(tr.feed(raw))

        types = [e["event"]["type"] for e in events]
        # 系统不建实例；四个 LLM 实例各创建一次（mapper、两个 scorer、总审）
        self.assertEqual(types.count("instance.created"), 4)
        self.assertFalse(any(e["instance_id"] == "system" for e in events))
        # t1 的 result.returned 只发一次（handoff 与 completed 去重）
        t1_returns = [e for e in events if e["event"]["type"] == "result.returned"
                      and e["task_id"] == "task_score:t1"]
        self.assertEqual(len(t1_returns), 1)
        # t2 无 handoff：completed 补发一条
        t2_returns = [e for e in events if e["event"]["type"] == "result.returned"
                      and e["task_id"] == "task_score:t2"]
        self.assertEqual(len(t2_returns), 1)
        self.assertEqual(types.count("task.failed"), 1)
        self.assertEqual([e["seq"] for e in events], list(range(len(events))))

    def test_mapper_return_follows_completed(self) -> None:
        tr = AdmissionCollabTranslator("run-uuid-2")
        events = tr.feed(admission_event(
            node_id="capability_mapping", agent_id="capability_mapping",
            agent_type="mapper", status="completed", summary="两项任务"))
        types = [e["event"]["type"] for e in events]
        self.assertEqual(types, ["instance.created", "task.completed", "result.returned"])
        self.assertEqual(events[-1]["cause_event_id"], events[-2]["event_id"])

    def test_repair_merges_into_score_instance_and_digest_carries_task_title(self) -> None:
        tr = AdmissionCollabTranslator("run-uuid-3")
        events: list[dict] = []
        for raw in [
            admission_event(node_id="task_score:t9", agent_id="task_score:t9",
                            agent_type="task_scorer", status="running", at="t1"),
            admission_event(node_id="task_score:t9", agent_id="task_score:t9",
                            agent_type="task_scorer", event_kind="handoff", target_id="system",
                            status="completed", summary="评定 2 级（low）：生成经验偏研究",
                            label="生成算法研究", at="t2"),
            admission_event(node_id="evidence_repair:t9", agent_id="evidence_repair:t9",
                            agent_type="task_scorer", status="running", at="t3"),
            admission_event(node_id="evidence_repair:t9", agent_id="evidence_repair:t9",
                            agent_type="task_scorer", event_kind="handoff", target_id="system",
                            status="completed", summary="证据修正后评定 3 级：证据链完整",
                            label="生成算法研究", at="t4"),
        ]:
            events.extend(tr.feed(raw))

        types = [e["event"]["type"] for e in events]
        # repair 与 score 是同一个评分 Agent：实例只建一次，信封全部挂在 task_score 实例下
        self.assertEqual(types.count("instance.created"), 1)
        self.assertTrue(all(e["instance_id"] == "task_score:t9" for e in events))
        # 回传 digest 带任务标题，消息可读；每轮回传各补一次 task.completed 终点
        returns = [e for e in events if e["event"]["type"] == "result.returned"]
        self.assertEqual(len(returns), 2)
        self.assertEqual(returns[0]["event"]["digest"], "【生成算法研究】评定 2 级（low）：生成经验偏研究")
        self.assertEqual(returns[1]["event"]["digest"], "【生成算法研究】证据修正后评定 3 级：证据链完整")
        self.assertEqual(types.count("task.completed"), 2)
        self.assertEqual([e["seq"] for e in events], list(range(len(events))))


class CollabEventStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        ensure_schema(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def test_append_and_cursor_read(self) -> None:
        self.assertGreaterEqual(LATEST_SCHEMA_VERSION, 32)
        tr = PanelCollabTranslator("777")
        envelopes = [tr.run_event("run.started")]
        envelopes += tr.feed(panel_node(
            agent_id="chair", event_kind="dispatch", target_id="m1",
            mission_type="verify", detail={"目标": "核实"}))
        with self.Session() as session:
            append_collab_events(session, envelopes)
            session.commit()
            first, latest = list_collab_events(session, "panel", "777")
            self.assertEqual(latest, len(envelopes) - 1)
            self.assertEqual(first[0]["event"]["type"], "run.started")
            # 游标续读：只回放新增
            more = [tr.run_event("run.completed", summary="done")]
            append_collab_events(session, more)
            session.commit()
            tail, latest2 = list_collab_events(session, "panel", "777", after_seq=latest)
            self.assertEqual(len(tail), 1)
            self.assertEqual(tail[0]["event"]["type"], "run.completed")
            self.assertEqual(latest2, len(envelopes))

    def test_run_seq_unique_constraint(self) -> None:
        tr = PanelCollabTranslator("778")
        env = tr.run_event("run.started")
        with self.Session() as session:
            append_collab_events(session, [env])
            session.commit()
            duplicate = dict(env, event_id=uuid4().hex)  # 同 run 同 seq，不同 event_id
            append_collab_events(session, [duplicate])
            with self.assertRaises(IntegrityError):
                session.commit()


if __name__ == "__main__":
    unittest.main()
