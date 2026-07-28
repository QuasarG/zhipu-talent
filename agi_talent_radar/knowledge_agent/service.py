"""人才知识 Agent 高层服务接口。

公共入口：

    ask_talent_knowledge(conversation_id, prompt) -> Iterator[AgentEvent]

流式产出 AgentEvent（type=node/intent/clarification/local_facts/tool_plan/
external_fact/tool_failure/answer/warning/done），适合 SSE。

权限边界（计划 §2.4）：
- Agent 可读人才库、调用外部工具、追加 pending 外部事实；
- 不得修改 HR 状态、合并人物、加入/删除 Candidate、确认事实、修改评分。
"""
from __future__ import annotations

from typing import Any, Callable, Iterator

from agi_talent_radar.knowledge_agent.models import (
    AgentEvent,
    KnowledgeState,
    ToolSelection,
    UserIntent,
)


def ask_talent_knowledge(
    conversation_id: str,
    prompt: str,
    *,
    inject_state: dict[str, Any] | None = None,
    connectors: dict[str, Callable[[dict[str, Any]], list]] | None = None,
) -> Iterator[AgentEvent]:
    """驱动一次知识 Agent 工作流，流式返回事件。

    ``connectors`` 用于注入测试用 fake 连接器（默认走真实 connector）。
    ``inject_state`` 用于注入额外状态字段（如 mock intent）。
    """
    from agi_talent_radar.knowledge_agent.graph import build_knowledge_graph_with_connectors

    initial_state: KnowledgeState = {
        "conversation_id": conversation_id,
        "prompt": prompt,
        "scope": ["all"],
        "local_facts": [],
        "external_facts": [],
        "failed_tools": [],
        "normalized_facts": [],
        "citations": [],
        "warnings": [],
    }
    if inject_state:
        initial_state.update(inject_state)  # type: ignore[typeddict-item]

    graph = build_knowledge_graph_with_connectors(connectors)

    yield AgentEvent(type="node", payload={"node": "intent_parser"})

    final_state: KnowledgeState = initial_state  # type: ignore[assignment]
    try:
        result = graph.invoke(initial_state)
        final_state = result  # type: ignore[assignment]

        intent = final_state.get("intent", "")
        yield AgentEvent(
            type="intent",
            payload={"intent": intent, "scope": final_state.get("scope", [])},
        )
        if intent == UserIntent.TALENT_DISCOVERY.value:
            yield AgentEvent(type="answer", payload={"answer": final_state.get("answer", "")})
            yield AgentEvent(type="done", payload={})
            return

        if final_state.get("needs_clarification"):
            yield AgentEvent(
                type="clarification",
                payload={"message": final_state.get("clarification_message", "")},
            )
            yield AgentEvent(type="answer", payload={"answer": final_state.get("answer", "")})
            yield AgentEvent(type="done", payload={})
            return

        yield AgentEvent(
            type="local_facts",
            payload={
                "count": len(final_state.get("local_facts", [])),
                "sufficient": bool(final_state.get("local_sufficient", False)),
            },
        )

        tools = final_state.get("tools", [])
        yield AgentEvent(type="tool_plan", payload={"tools": tools})

        if tools and tools != [ToolSelection.NONE.value]:
            yield AgentEvent(
                type="external_fact",
                payload={"count": len(final_state.get("external_facts", []))},
            )
            failed = final_state.get("failed_tools", [])
            if failed:
                yield AgentEvent(type="tool_failure", payload={"failed_tools": failed})

        for warning in final_state.get("warnings", []) or []:
            yield AgentEvent(type="warning", payload={"message": warning})

        yield AgentEvent(
            type="answer",
            payload={
                "answer": final_state.get("answer", ""),
                "citations": final_state.get("citations", []),
            },
        )
        yield AgentEvent(type="done", payload={})
    except Exception as exc:  # noqa: BLE001
        yield AgentEvent(type="warning", payload={"message": f"agent_error: {exc}"})
        yield AgentEvent(type="done", payload={})


__all__ = [
    "AgentEvent",
    "ask_talent_knowledge",
]