"""证据归一节点：统一来源 / 时间 / 核验状态 / 去重键。"""
from __future__ import annotations

from typing import Any

from agi_talent_radar.knowledge_agent.models import KnowledgeState


def normalize_facts(
    local_facts: list[dict[str, Any]],
    external_facts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """合并库内与外部事实，统一字段。

    - 库内事实的 verification_status 保持原值（多数 confirmed）；
    - 外部事实统一为 pending（已由 KnowledgeFact 默认）；
    - 按 (source, title, source_url) 去重。
    """
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    def _key(fact: dict[str, Any]) -> tuple[str, str, str]:
        return (
            str(fact.get("source", "")),
            str(fact.get("title", ""))[:200],
            str(fact.get("source_url", "")),
        )

    for fact in local_facts + external_facts:
        key = _key(fact)
        if key in seen:
            continue
        seen.add(key)
        normalized = {
            "source": fact.get("source", ""),
            "fact_type": fact.get("fact_type", ""),
            "title": fact.get("title", ""),
            "payload": fact.get("payload", {}) or {},
            "source_url": fact.get("source_url", ""),
            "fetched_at": fact.get("fetched_at", ""),
            "verification_status": fact.get("verification_status", "pending"),
        }
        merged.append(normalized)
    return merged


def evidence_normalizer(state: KnowledgeState) -> dict[str, Any]:
    """LangGraph 节点：归一证据。"""
    merged = normalize_facts(
        state.get("local_facts") or [],
        state.get("external_facts") or [],
    )
    pending_count = sum(
        1 for f in merged if f.get("verification_status") == "pending"
    )
    return {
        "normalized_facts": merged,
        "pending_fact_count": pending_count,
    }