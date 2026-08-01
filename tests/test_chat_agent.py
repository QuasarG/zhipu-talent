"""人才问答 ReAct Agent 测试：scripted LLM 验证循环、HITL 中断与 action 续跑。

用 sqlite 内存库 + monkeypatch call_llm_tools，不打外网、不打 MySQL。
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from agi_talent_radar.core.db.orm import (
    Base,
    ChatMessageORM,
    ConversationORM,
    PersonORM,
)
from agi_talent_radar.knowledge_agent.agent import resume_agent, run_agent


class ScriptedLLM:
    """按脚本依次返回 call_llm_tools 结果；on_delta 逐段回放 text。"""

    def __init__(self, scripts: list[dict]):
        self._scripts = list(scripts)
        self.calls: list[list[dict]] = []

    def __call__(self, messages, tools, temperature=0.2, on_delta=None, max_retries=3):
        self.calls.append(messages)
        script = self._scripts.pop(0)
        if on_delta and script.get("text"):
            on_delta(script["text"])
        return {
            "text": script.get("text", ""),
            "tool_calls": script.get("tool_calls", []),
            "finish_reason": script.get("finish_reason", "stop"),
        }


def _tool_call(call_id: str, name: str, arguments: str) -> dict:
    return {"id": call_id, "name": name, "arguments": arguments}


class ChatAgentTestBase(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.session = sessionmaker(bind=engine, expire_on_commit=False)()
        self.conv = ConversationORM()
        self.session.add(self.conv)
        self.session.commit()
        self.events: list[tuple[str, dict]] = []
        self._title_patch = patch(
            "agi_talent_radar.knowledge_agent.agent.call_llm_json",
            return_value={"title": "测试标题"},
        )
        self._title_patch.start()

    def tearDown(self) -> None:
        self._title_patch.stop()
        self.session.close()

    def emit(self, type_: str, payload: dict) -> None:
        self.events.append((type_, payload))

    def event_types(self) -> list[str]:
        return [type_ for type_, _ in self.events]

    def db_messages(self) -> list[ChatMessageORM]:
        return (
            self.session.query(ChatMessageORM)
            .filter_by(conversation_id=self.conv.id)
            .order_by(ChatMessageORM.created_at)
            .all()
        )

    def run_with(self, llm: ScriptedLLM, prompt: str = "人才库里有哪些人？") -> None:
        with patch("agi_talent_radar.knowledge_agent.agent.call_llm_tools", llm):
            run_agent(self.session, self.conv.id, prompt, self.emit)


class TestSimpleAnswer(ChatAgentTestBase):
    def test_answer_flow_persists_messages(self) -> None:
        llm = ScriptedLLM([{"text": "库里有 2 个人。"}])
        self.run_with(llm)

        types = self.event_types()
        self.assertEqual(types[0], "meta")
        self.assertIn("answer_delta", types)
        self.assertIn("sources", types)
        self.assertIn("message_done", types)
        self.assertEqual(types[-1], "done")
        self.assertEqual(dict(self.events)["done"]["status"], "completed")

        messages = self.db_messages()
        self.assertEqual([m.role for m in messages], ["user", "assistant"])
        assistant = messages[-1]
        self.assertEqual(assistant.status, "completed")
        segments = assistant.content["segments"]
        self.assertEqual(segments, [{"type": "text", "text": "库里有 2 个人。"}])
        # 首问标题已生成
        self.assertEqual(self.conv.title, "测试标题")
        # 历史不重复：system + user 两轮
        self.assertEqual(len(llm.calls[0]), 2)


class TestToolCallThenAnswer(ChatAgentTestBase):
    def test_tool_call_loop(self) -> None:
        self.session.add(PersonORM(id="p1", name="李四", direction="Agent", fingerprint="fp-test-1"))
        self.session.commit()
        llm = ScriptedLLM(
            [
                {
                    "text": "接下来我将调用 search_persons 筛选库内人物。",
                    "tool_calls": [_tool_call("call_1", "search_persons", '{"name": "李"}')],
                    "finish_reason": "tool_calls",
                },
                {"text": "库里有李四。"},
            ]
        )
        self.run_with(llm)

        types = self.event_types()
        self.assertIn("tool_start", types)
        self.assertIn("tool_end", types)
        tool_end = next(p for t, p in self.events if t == "tool_end")
        self.assertEqual(tool_end["status"], "ok")
        self.assertIn("命中 1 人", tool_end["summary"])
        self.assertEqual(dict(self.events)["done"]["status"], "completed")

        assistant = self.db_messages()[-1]
        segment_types = [seg["type"] for seg in assistant.content["segments"]]
        self.assertEqual(segment_types, ["text", "tool", "text"])
        # 第二轮 LLM 收到了 tool 响应
        second_call = llm.calls[1]
        tool_msgs = [m for m in second_call if m.get("role") == "tool"]
        self.assertEqual(len(tool_msgs), 1)
        self.assertIn("李四", tool_msgs[0]["content"])


class TestGatedInterruptAndResume(ChatAgentTestBase):
    def test_clarification_interrupt_then_resume(self) -> None:
        llm = ScriptedLLM(
            [
                {
                    "text": "这个问题需要澄清。",
                    "tool_calls": [
                        _tool_call("call_1", "ask_clarification", '{"question": "你指哪一位？", "options": []}')
                    ],
                    "finish_reason": "tool_calls",
                },
                {"text": "明白了，答案是张三。"},
            ]
        )
        with patch("agi_talent_radar.knowledge_agent.agent.call_llm_tools", llm):
            run_agent(self.session, self.conv.id, "他怎么样？", self.emit)

        types = self.event_types()
        self.assertIn("action_required", types)
        self.assertEqual(dict(self.events)["done"]["status"], "awaiting_action")
        action = dict(self.events)["action_required"]
        self.assertEqual(action["kind"], "clarify")

        assistant = self.db_messages()[-1]
        self.assertEqual(assistant.status, "awaiting_action")
        self.assertEqual(assistant.pending_action["action_id"], action["action_id"])

        # 用户回答后续跑（复用同一个 scripted LLM 的第二脚本）
        self.events.clear()
        with patch("agi_talent_radar.knowledge_agent.agent.call_llm_tools", llm):
            resume_agent(
                self.session, self.conv.id, action["action_id"], {"answer": "张三"}, self.emit
            )

        types = self.event_types()
        self.assertEqual(types[-1], "done")
        self.assertEqual(dict(self.events)["done"]["status"], "completed")
        assistant = self.db_messages()[-1]
        self.assertEqual(assistant.status, "completed")
        self.assertIsNone(assistant.pending_action)
        action_segments = [
            seg for seg in assistant.content["segments"] if seg.get("type") == "action"
        ]
        self.assertEqual(action_segments[0]["decision"], {"answer": "张三"})
        # 续跑时澄清结果作为 tool 响应回填
        resume_call = llm.calls[1]
        tool_msgs = [m for m in resume_call if m.get("role") == "tool"]
        self.assertEqual(tool_msgs[0]["content"], "用户回答：张三")
        self.assertEqual(tool_msgs[0]["tool_call_id"], "call_1")

    def test_resume_rejects_wrong_action_id(self) -> None:
        llm = ScriptedLLM(
            [
                {
                    "tool_calls": [
                        _tool_call("call_1", "ask_clarification", '{"question": "哪位？"}')
                    ],
                    "finish_reason": "tool_calls",
                }
            ]
        )
        self.run_with(llm, "他怎么样？")
        self.events.clear()
        resume_agent(self.session, self.conv.id, "wrong-id", {"answer": "x"}, self.emit)
        self.assertIn("error", self.event_types())
        error_payload = next(p for t, p in self.events if t == "error")
        self.assertIn("不匹配", error_payload["message"])


if __name__ == "__main__":
    unittest.main()
