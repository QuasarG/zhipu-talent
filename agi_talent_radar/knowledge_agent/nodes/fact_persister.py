"""事实落库节点：把外部新事实追加为 pending，不覆盖已确认事实。

权限边界（计划 §2.4）：
- Agent 可以追加 pending 外部事实；
- 不得覆盖 / 删除 / 确认已有事实；
- 不修改 HR 状态、合并人物、加入/删除 Candidate、修改评分。
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

from agi_talent_radar.core.db.orm import ExternalFactORM, PersonORM
from agi_talent_radar.knowledge_agent.models import KnowledgeState


FACT_TTL_DAYS = 30


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _dedupe_key(fact: dict[str, Any]) -> str:
    base = "|".join(
        [
            str(fact.get("source", "")),
            str(fact.get("fact_type", "")),
            str(fact.get("title", ""))[:200],
            str(fact.get("source_url", "")),
        ]
    )
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:32]


def persist_pending_facts(
    session,
    person_id: str | None,
    external_facts: list[dict[str, Any]],
) -> int:
    """把外部事实追加为 pending ExternalFactORM。返回新增条数。

    - 同 person + 同 dedupe_key 已存在 → 不重复插入；
    - 不修改任何 confirmed 记录。
    """
    if not person_id or not external_facts:
        return 0
    person = session.get(PersonORM, person_id)
    if person is None:
        return 0

    existing_keys = {
        row.source_url + "|" + row.fact_type
        for row in (
            session.query(ExternalFactORM)
            .filter_by(person_id=person_id)
            .all()
        )
    }
    inserted = 0
    expires = _now() + timedelta(days=FACT_TTL_DAYS)
    for fact in external_facts:
        dedupe = _dedupe_key(fact)
        signature = f"{fact.get('source_url', '')}|{fact.get('fact_type', '')}"
        if signature in existing_keys:
            continue
        session.add(
            ExternalFactORM(
                person_id=person_id,
                source=str(fact.get("source", "")),
                fact_type=str(fact.get("fact_type", "")),
                payload=fact.get("payload", {}) or {},
                source_url=str(fact.get("source_url", "")),
                expires_at=expires,
            )
        )
        existing_keys.add(signature)
        inserted += 1
    if inserted:
        session.commit()
    return inserted


def fact_persister(state: KnowledgeState) -> dict[str, Any]:
    """LangGraph 节点：追加 pending 外部事实。"""
    external = state.get("external_facts") or []
    if not external:
        return {"pending_fact_count": 0}

    identity = state.get("identity", {}) or {}
    name = str(identity.get("name", ""))
    if not name:
        return {"pending_fact_count": 0}

    from agi_talent_radar.core.database import get_session

    with get_session() as session:
        person = (
            session.query(PersonORM)
            .filter(PersonORM.name.like(f"%{name}%"))
            .first()
        )
        if person is None:
            return {"pending_fact_count": 0}
        inserted = persist_pending_facts(session, person.id, external)
    return {"pending_fact_count": inserted}