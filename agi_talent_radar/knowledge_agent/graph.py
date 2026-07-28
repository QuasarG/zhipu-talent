"""人才知识 Agent 的 LangGraph 装配。

图结构（含分支）：

    START
      ↓
    intent_parser
      ↓ (条件分支)
    ┌─ talent_discovery → END (unsupported)
    ├─ pool_query → local_retriever → tool_planner → evidence_normalizer
    │              → answer_composer → END
    └─ known_person
           ↓
        identity_resolver
           ↓ (needs_clarification → END)
        local_retriever
           ↓
        tool_planner
           ↓ (tools=['none'] → 跳过 investigator)
        external_investigator  (可选)
           ↓
        evidence_normalizer
           ↓
        fact_persister
           ↓
        answer_composer → END
"""
from __future__ import annotations

from typing import Any, Callable

from langgraph.graph import END, START, StateGraph

from agi_talent_radar.knowledge_agent.models import (
    KnowledgeState,
    ToolSelection,
    UserIntent,
)
from agi_talent_radar.knowledge_agent.nodes.answer_composer import answer_composer
from agi_talent_radar.knowledge_agent.nodes.evidence_normalizer import evidence_normalizer
from agi_talent_radar.knowledge_agent.nodes.external_investigator import (
    _default_connectors,
    external_investigator,
)
from agi_talent_radar.knowledge_agent.nodes.fact_persister import fact_persister
from agi_talent_radar.knowledge_agent.nodes.identity_resolver import identity_resolver
from agi_talent_radar.knowledge_agent.nodes.intent_parser import intent_parser
from agi_talent_radar.knowledge_agent.nodes.local_retriever import local_retriever
from agi_talent_radar.knowledge_agent.nodes.tool_planner import tool_planner


def _route_after_intent(state: KnowledgeState) -> str:
    intent = state.get("intent", "")
    if intent == UserIntent.TALENT_DISCOVERY.value:
        return "end_unsupported"
    if intent == UserIntent.POOL_QUERY.value:
        return "local_retriever"
    # known_person
    return "identity_resolver"


def _route_after_identity(state: KnowledgeState) -> str:
    if state.get("needs_clarification"):
        return "end_clarification"
    return "local_retriever"


def _route_after_tools(state: KnowledgeState) -> str:
    tools = state.get("tools") or []
    if not tools or tools == [ToolSelection.NONE.value]:
        return "evidence_normalizer"
    return "external_investigator"


def build_knowledge_graph():
    """装配并编译知识 Agent 的 LangGraph（使用默认连接器）。"""
    return build_knowledge_graph_with_connectors(connectors=None)


def build_knowledge_graph_with_connectors(
    connectors: dict[str, Callable[[dict[str, Any]], list]] | None,
):
    """装配并编译知识 Agent 的 LangGraph。

    ``connectors=None`` 时使用默认真实连接器；
    测试时可注入 fake connector 字典。
    """
    resolved_connectors = connectors if connectors is not None else _default_connectors()

    def _wrapped_external_investigator(state: KnowledgeState) -> dict[str, Any]:
        return external_investigator(state, connectors=resolved_connectors)

    workflow = StateGraph(KnowledgeState)

    workflow.add_node("intent_parser", intent_parser)
    workflow.add_node("identity_resolver", identity_resolver)
    workflow.add_node("local_retriever", local_retriever)
    workflow.add_node("tool_planner", tool_planner)
    workflow.add_node("external_investigator", _wrapped_external_investigator)
    workflow.add_node("evidence_normalizer", evidence_normalizer)
    workflow.add_node("fact_persister", fact_persister)
    workflow.add_node("answer_composer", answer_composer)
    workflow.add_node("end_unsupported", _end_unsupported)
    workflow.add_node("end_clarification", _end_clarification)

    workflow.add_edge(START, "intent_parser")
    workflow.add_conditional_edges(
        "intent_parser",
        _route_after_intent,
        {
            "end_unsupported": "end_unsupported",
            "local_retriever": "local_retriever",
            "identity_resolver": "identity_resolver",
        },
    )
    workflow.add_edge("end_unsupported", END)

    workflow.add_conditional_edges(
        "identity_resolver",
        _route_after_identity,
        {
            "end_clarification": "end_clarification",
            "local_retriever": "local_retriever",
        },
    )
    workflow.add_edge("end_clarification", END)

    workflow.add_edge("local_retriever", "tool_planner")
    workflow.add_conditional_edges(
        "tool_planner",
        _route_after_tools,
        {
            "external_investigator": "external_investigator",
            "evidence_normalizer": "evidence_normalizer",
        },
    )
    workflow.add_edge("external_investigator", "evidence_normalizer")
    workflow.add_edge("evidence_normalizer", "fact_persister")
    workflow.add_edge("fact_persister", "answer_composer")
    workflow.add_edge("answer_composer", END)

    return workflow.compile()


def _end_unsupported(state: KnowledgeState) -> dict[str, Any]:
    return {
        "answer": (
            "按研究关键词发现一批未知人才的功能当前明确不在实现范围内。"
            "如果只想了解人才库中已有的人物，请提供更具体的查询条件。"
        ),
        "citations": [],
        "warnings": ["talent_discovery_unsupported"],
    }


def _end_clarification(state: KnowledgeState) -> dict[str, Any]:
    return {
        "answer": state.get("clarification_message")
        or "请补充可识别的具体人物信息。",
        "citations": [],
        "warnings": [],
    }


__all__ = ["build_knowledge_graph"]