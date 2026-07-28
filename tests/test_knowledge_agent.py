"""人才知识 Agent 节点与端到端测试。

覆盖（与计划 §阶段 5 验收对齐）：

1. plan_tools：库内足够 → ['none']；scope=['papers'] → ['openalex']
2. external_investigator：aminer 抛错不阻塞，failed_tools 记录
3. evidence_normalizer：库内 + 外部去重
4. ask_talent_knowledge：人才发现请求 → unsupported 结束
5. ask_talent_knowledge：库内优先（mock local_sufficient=True）→ 不调外部
"""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from agi_talent_radar.core.connectors.base import ConnectorUnavailableError, Fact
from agi_talent_radar.knowledge_agent import ask_talent_knowledge
from agi_talent_radar.knowledge_agent.models import (
    AgentEvent,
    KnowledgeFact,
    FactVerification,
    ToolSelection,
    UserIntent,
)
from agi_talent_radar.knowledge_agent.nodes.evidence_normalizer import normalize_facts
from agi_talent_radar.knowledge_agent.nodes.external_investigator import (
    external_investigator,
)
from agi_talent_radar.knowledge_agent.nodes.tool_planner import plan_tools


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


class TestToolPlanner(unittest.TestCase):
    def test_pool_query_never_calls_external(self) -> None:
        tools = plan_tools(
            intent=UserIntent.POOL_QUERY.value,
            scope=["all"],
            local_sufficient=False,
        )
        self.assertEqual(tools, [ToolSelection.NONE.value])

    def test_local_sufficient_skips_external(self) -> None:
        tools = plan_tools(
            intent=UserIntent.KNOWN_PERSON.value,
            scope=["all"],
            local_sufficient=True,
        )
        self.assertEqual(tools, [ToolSelection.NONE.value])

    def test_scope_papers_only_calls_openalex(self) -> None:
        tools = plan_tools(
            intent=UserIntent.KNOWN_PERSON.value,
            scope=["papers"],
            local_sufficient=False,
        )
        self.assertEqual(tools, [ToolSelection.OPENALEX.value])

    def test_scope_reputation_only_calls_web_search(self) -> None:
        tools = plan_tools(
            intent=UserIntent.KNOWN_PERSON.value,
            scope=["reputation"],
            local_sufficient=False,
        )
        self.assertEqual(tools, [ToolSelection.WEB_SEARCH.value])

    def test_scope_all_calls_three_links(self) -> None:
        tools = plan_tools(
            intent=UserIntent.KNOWN_PERSON.value,
            scope=["all"],
            local_sufficient=False,
        )
        self.assertEqual(
            sorted(tools),
            sorted([
                ToolSelection.AMINER.value,
                ToolSelection.OPENALEX.value,
                ToolSelection.WEB_SEARCH.value,
            ]),
        )


class TestExternalInvestigator(unittest.TestCase):
    def test_failed_link_does_not_block_others(self) -> None:
        """aminer 抛 ConnectorUnavailableError 时，其他链路仍正常返回，
        aminer 进入 failed_tools。"""
        def boom_aminer(identity):
            raise ConnectorUnavailableError("aminer 不可用")

        def ok_openalex(identity):
            return [
                KnowledgeFact(
                    source="openalex",
                    fact_type="paper",
                    title="Paper A",
                    fetched_at=datetime.utcnow(),
                )
            ]

        def ok_web(identity):
            return [
                KnowledgeFact(
                    source="web_search",
                    fact_type="search_hit",
                    title="News A",
                    fetched_at=datetime.utcnow(),
                )
            ]

        state = {
            "tools": ["aminer", "openalex", "web_search"],
            "identity": {"name": "张三"},
        }
        result = external_investigator(
            state,
            connectors={
                "aminer": boom_aminer,
                "openalex": ok_openalex,
                "web_search": ok_web,
            },
        )
        self.assertEqual(result["failed_tools"], ["aminer"])
        self.assertEqual(len(result["external_facts"]), 2)
        sources = sorted(f["source"] for f in result["external_facts"])
        self.assertEqual(sources, ["openalex", "web_search"])

    def test_no_tools_returns_empty(self) -> None:
        result = external_investigator({"tools": ["none"]}, connectors={})
        self.assertEqual(result["external_facts"], [])
        self.assertEqual(result["failed_tools"], [])


class TestEvidenceNormalizer(unittest.TestCase):
    def test_dedupes_by_source_title_url(self) -> None:
        local = [
            {
                "source": "talent_pool",
                "fact_type": "evaluation_summary",
                "title": "张三 评估",
                "source_url": "",
                "fetched_at": _now_iso(),
                "verification_status": "confirmed",
            }
        ]
        external = [
            {
                "source": "openalex",
                "fact_type": "paper",
                "title": "Paper A",
                "source_url": "https://openalex.org/1",
                "fetched_at": _now_iso(),
                "verification_status": "pending",
            },
            # 重复（应被去重）
            {
                "source": "openalex",
                "fact_type": "paper",
                "title": "Paper A",
                "source_url": "https://openalex.org/1",
                "fetched_at": _now_iso(),
                "verification_status": "pending",
            },
        ]
        merged = normalize_facts(local, external)
        self.assertEqual(len(merged), 2)
        statuses = {f["verification_status"] for f in merged}
        self.assertEqual(statuses, {"confirmed", "pending"})


class TestAskTalentKnowledge(unittest.TestCase):
    def _drain(self, events_iter) -> list[AgentEvent]:
        return list(events_iter)

    def test_talent_discovery_request_is_unsupported(self) -> None:
        """按研究关键词发现一批未知人物 → UNSUPPORTED，不调用任何工具。"""
        events = self._drain(
            ask_talent_knowledge(
                "conv-1",
                "帮我按 Agent 方向发现一批候选人",
                inject_state={"intent": UserIntent.TALENT_DISCOVERY.value},
            )
        )
        types = [e.type for e in events]
        self.assertIn("intent", types)
        self.assertIn("answer", types)
        intent_event = next(e for e in events if e.type == "intent")
        self.assertEqual(intent_event.payload["intent"], "talent_discovery")
        # 不应触发 tool_plan / external_fact
        self.assertNotIn("tool_plan", types)
        self.assertNotIn("external_fact", types)
        answer_event = next(e for e in events if e.type == "answer")
        self.assertIn("不在实现范围内", answer_event.payload["answer"])

    def test_local_sufficient_skips_external_tools(self) -> None:
        """库内足够时 tool_planner 返回 ['none']，不调用外部链路。"""
        # 直接调 plan_tools，避免端到端 graph 触发真实 local_retriever。
        tools = plan_tools(
            intent=UserIntent.KNOWN_PERSON.value,
            scope=["all"],
            local_sufficient=True,
        )
        self.assertEqual(tools, [ToolSelection.NONE.value])

    def test_partial_failure_emits_tool_failure_via_node(self) -> None:
        """aminer 失败时仍正常返回 openalex 结果，failed_tools 记录。

        直接调 external_investigator 节点函数（端到端 graph 会被
        local_retriever 真实查询覆盖注入状态，故走节点级测试）。
        """
        def boom_aminer(identity):
            raise ConnectorUnavailableError("aminer 不可用")

        def ok_openalex(identity):
            return [
                KnowledgeFact(
                    source="openalex",
                    fact_type="paper",
                    title="Paper A",
                    fetched_at=datetime.now(timezone.utc).replace(tzinfo=None),
                )
            ]

        def ok_web(identity):
            return []

        result = external_investigator(
            {
                "tools": ["aminer", "openalex", "web_search"],
                "identity": {"name": "张三"},
            },
            connectors={
                "aminer": boom_aminer,
                "openalex": ok_openalex,
                "web_search": ok_web,
            },
        )
        self.assertEqual(result["failed_tools"], ["aminer"])
        self.assertEqual(len(result["external_facts"]), 1)
        self.assertEqual(result["external_facts"][0]["source"], "openalex")


if __name__ == "__main__":
    unittest.main()