"""外部调查节点：AMiner / OpenAlex / Web Search 三链独立执行。

设计要点（与计划 §2.2 对齐）：

- 三条链路独立调用；任一失败不阻塞其他链路；
- 失败的链路记录到 ``failed_tools``，最终 status 为 "部分完成"；
- 所有连接器返回统一 ``KnowledgeFact``，不在节点内解析供应商原始响应；
- 通过可注入的 ``connectors`` 字典便于测试与未来切换。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from agi_talent_radar.core.connectors.base import ConnectorUnavailableError, Fact
from agi_talent_radar.knowledge_agent.models import (
    FactVerification,
    KnowledgeFact,
    KnowledgeState,
    ToolSelection,
)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# 默认连接器映射（按 ToolSelection 名）
def _default_connectors() -> dict[str, Callable[[dict[str, Any]], list[KnowledgeFact]]]:
    from agi_talent_radar.core.connectors.aminer import search_person as _aminer_search
    from agi_talent_radar.core.connectors.openalex import search_works as _openalex
    from agi_talent_radar.core.connectors.web_search import search_web as _web

    def wrap_aminer(identity: dict[str, Any]) -> list[KnowledgeFact]:
        name = str(identity.get("name", ""))
        facts: list[KnowledgeFact] = []
        for fact in _aminer_search(name) or []:
            facts.append(_to_knowledge_fact(fact, "aminer", "profile"))
        return facts

    def wrap_openalex(identity: dict[str, Any]) -> list[KnowledgeFact]:
        name = str(identity.get("name", ""))
        # 用姓名做粗粒度检索；OpenAlex 没有 author.name 直接查询，
        # 简化为以附加 keyword 检索标题。
        keywords = identity.get("additional_keywords") or [name]
        facts: list[KnowledgeFact] = []
        for keyword in keywords[:3]:
            for fact in _openalex(keyword) or []:
                facts.append(_to_knowledge_fact(fact, "openalex", "paper"))
        return facts

    def wrap_web(identity: dict[str, Any]) -> list[KnowledgeFact]:
        name = str(identity.get("name", ""))
        org = str(identity.get("org", ""))
        facts: list[KnowledgeFact] = []
        for fact in _web(name, count=8) or []:
            facts.append(_to_knowledge_fact(fact, "web_search", "search_hit"))
        _ = org
        return facts

    return {
        ToolSelection.AMINER.value: wrap_aminer,
        ToolSelection.OPENALEX.value: wrap_openalex,
        ToolSelection.WEB_SEARCH.value: wrap_web,
    }


def _to_knowledge_fact(
    fact: Fact,
    source: str,
    fact_type: str,
) -> KnowledgeFact:
    payload = dict(fact.payload or {})
    return KnowledgeFact(
        source=source,  # type: ignore[arg-type]
        fact_type=fact_type,
        title=str(payload.get("title", "")) or fact_type,
        payload=payload,
        source_url=fact.source_url or "",
        fetched_at=_now(),
        verification_status=FactVerification.PENDING,
    )


def external_investigator(
    state: KnowledgeState,
    connectors: dict[str, Callable[[dict[str, Any]], list[KnowledgeFact]]] | None = None,
) -> dict[str, Any]:
    """LangGraph 节点：执行外部链路。

    每条链路独立 try/except，单链失败仅记录到 ``failed_tools``。
    """
    tools = state.get("tools") or []
    if not tools or tools == [ToolSelection.NONE.value]:
        return {"external_facts": [], "failed_tools": []}

    if connectors is None:
        connectors = _default_connectors()

    identity = state.get("identity", {}) or {}
    facts: list[KnowledgeFact] = []
    failed: list[str] = []

    for tool in tools:
        connector = connectors.get(tool)
        if connector is None:
            failed.append(tool)
            continue
        try:
            facts.extend(connector(identity))
        except (ConnectorUnavailableError, Exception):
            failed.append(tool)

    return {
        "external_facts": [fact.model_dump() for fact in facts],
        "failed_tools": failed,
    }