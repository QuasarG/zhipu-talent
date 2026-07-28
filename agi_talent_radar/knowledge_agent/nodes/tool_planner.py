"""工具规划节点：判断库内是否足够，以及需要哪些外部链路。

策略（与计划 §2.2 对齐）：

- 库内 ``local_sufficient=True`` → ``tools=['none']``，不调用外部。
- 已知人物调查 + scope=['papers'] → 调 OpenAlex；
- + ['reputation'] → 调 Web Search；
- 默认（profile / all）→ AMiner + OpenAlex + Web Search 三链。
- 用户显式限定范围时缩小实际调用范围。
"""
from __future__ import annotations

from typing import Any

from agi_talent_radar.knowledge_agent.models import KnowledgeState, ToolSelection, UserIntent


def plan_tools(
    intent: str,
    scope: list[str],
    local_sufficient: bool,
) -> list[str]:
    """纯函数版工具规划，便于单测。"""
    if intent != UserIntent.KNOWN_PERSON.value:
        return [ToolSelection.NONE.value]
    if local_sufficient:
        return [ToolSelection.NONE.value]

    tools: list[str] = []
    scope_set = set(scope or ["all"])
    if "all" in scope_set:
        return [
            ToolSelection.AMINER.value,
            ToolSelection.OPENALEX.value,
            ToolSelection.WEB_SEARCH.value,
        ]
    if "papers" in scope_set:
        tools.append(ToolSelection.OPENALEX.value)
    if "reputation" in scope_set:
        tools.append(ToolSelection.WEB_SEARCH.value)
    if "profile" in scope_set:
        tools.append(ToolSelection.AMINER.value)
    return tools or [ToolSelection.NONE.value]


def tool_planner(state: KnowledgeState) -> dict[str, Any]:
    """LangGraph 节点：工具规划。"""
    tools = plan_tools(
        intent=state.get("intent", ""),
        scope=state.get("scope") or ["all"],
        local_sufficient=bool(state.get("local_sufficient", False)),
    )
    return {"tools": tools}