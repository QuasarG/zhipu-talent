"""库内检索节点：优先查询 MySQL（未来 + Qdrant）。

库内查询返回 ``local_facts``；如果命中足够信息则置 ``local_sufficient=True``，
后续 tool_planner 不会触发外部调用（计划 §2.4 库内优先）。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from agi_talent_radar.core.db.orm import (
    CandidateORM,
    EvaluationORM,
    ExternalFactORM,
    PersonORM,
)
from agi_talent_radar.knowledge_agent.models import FactVerification, KnowledgeState


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def query_local_pool(
    session,
    identity: dict[str, Any],
    scope: list[str],
    list_evaluations: Callable | None = None,
    list_external_facts: Callable | None = None,
) -> list[dict[str, Any]]:
    """纯数据访问函数，便于单测注入。"""
    name = str(identity.get("name", "")).strip()
    if not name:
        return []
    facts: list[dict[str, Any]] = []

    persons = (
        session.query(PersonORM)
        .filter(PersonORM.name.like(f"%{name}%"))
        .all()
    )
    if not persons:
        return facts

    person_ids = {p.id for p in persons}
    for person in persons:
        # 候选人 / 评估摘要
        if "profile" in scope or "all" in scope:
            evaluations = (
                session.query(EvaluationORM)
                .filter_by(person_id=person.id, status="completed")
                .order_by(EvaluationORM.created_at.desc())
                .limit(3)
                .all()
            )
            for ev in evaluations:
                facts.append(
                    {
                        "source": "talent_pool",
                        "fact_type": "evaluation_summary",
                        "title": f"{person.name} 评估摘要",
                        "payload": {
                            "person_id": person.id,
                            "evaluation_id": ev.id,
                            "overall_score": ev.overall_score,
                            "stage_profile": ev.stage_profile,
                            "recommended_tracks": ev.recommended_tracks or [],
                        },
                        "source_url": "",
                        "fetched_at": (ev.completed_at or ev.created_at or _now()).isoformat(),
                        "verification_status": FactVerification.CONFIRMED.value,
                    }
                )
        # 外部事实（已有）
        external = (
            session.query(ExternalFactORM)
            .filter_by(person_id=person.id)
            .order_by(ExternalFactORM.fetched_at.desc())
            .limit(10)
            .all()
        )
        for fact in external:
            facts.append(
                {
                    "source": fact.source,
                    "fact_type": fact.fact_type,
                    "title": (fact.payload or {}).get("title", "") or fact.fact_type,
                    "payload": fact.payload or {},
                    "source_url": fact.source_url,
                    "fetched_at": fact.fetched_at.isoformat() if fact.fetched_at else _now().isoformat(),
                    "verification_status": FactVerification.PENDING.value,
                }
            )
    _ = person_ids  # 保留以备未来 Qdrant 过滤
    return facts


def decide_sufficient(local_facts: list[dict[str, Any]], scope: list[str]) -> bool:
    """简单决策：库内是否有足以回答的事实。"""
    if not local_facts:
        return False
    # 若只问论文，但库内没有 paper 类型事实 → 不够
    if scope == ["papers"]:
        return any(f.get("fact_type") == "paper" for f in local_facts)
    if scope == ["reputation"]:
        return any("search_hit" in str(f.get("fact_type", "")) for f in local_facts)
    # profile / all：只要有评估摘要即视为库内够
    return any(f.get("fact_type") == "evaluation_summary" for f in local_facts)


def local_retriever(state: KnowledgeState) -> dict[str, Any]:
    """LangGraph 节点：库内检索。"""
    identity = state.get("identity", {}) or {}
    scope = state.get("scope") or ["all"]
    from agi_talent_radar.core.database import get_session

    with get_session() as session:
        facts = query_local_pool(session, identity, scope)
    return {
        "local_facts": facts,
        "local_sufficient": decide_sufficient(facts, scope),
    }