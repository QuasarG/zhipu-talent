"""external_facts 缓存读写：未过期读缓存、过期才重拉，控制 API 成本。

修复 reputation_service 只写不读的技术债：连接器结果落表后，
TTL 内的重复请求直接命中缓存，不再重复调用外部 API。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from agi_talent_radar.core.db.orm import ExternalFactORM


def fetch_cached_facts(
    session,
    person_id: str,
    source: str,
    fact_type: str = "",
    now: datetime | None = None,
) -> list[ExternalFactORM]:
    """读未过期的缓存；fact_type 为空则匹配该 source 下全部。命中返回 ORM 列表，未命中返回空列表。"""
    now = now or datetime.now(timezone.utc)
    query = session.query(ExternalFactORM).filter(
        ExternalFactORM.person_id == person_id,
        ExternalFactORM.source == source,
        (ExternalFactORM.expires_at.is_(None)) | (ExternalFactORM.expires_at >= now),
    )
    if fact_type:
        query = query.filter(ExternalFactORM.fact_type == fact_type)
    return query.all()


def cache_fact(
    session,
    person_id: str,
    source: str,
    fact_type: str,
    payload: dict,
    source_url: str = "",
    ttl_days: int = 30,
    now: datetime | None = None,
) -> ExternalFactORM:
    """写一条带 TTL 的外部事实缓存，返回 ORM。"""
    now = now or datetime.now(timezone.utc)
    record = ExternalFactORM(
        person_id=person_id,
        source=source,
        fact_type=fact_type,
        payload=payload,
        source_url=source_url,
        fetched_at=now,
        expires_at=now + timedelta(days=ttl_days),
    )
    session.add(record)
    return record


def expired_cached_facts_exist(
    session,
    person_id: str,
    source: str,
    fact_type: str = "",
    now: datetime | None = None,
) -> bool:
    """是否存在已过期的缓存记录（用于判断是否需要重拉）。"""
    now = now or datetime.now(timezone.utc)
    query = session.query(ExternalFactORM).filter(
        ExternalFactORM.person_id == person_id,
        ExternalFactORM.source == source,
        ExternalFactORM.expires_at < now,
    )
    if fact_type:
        query = query.filter(ExternalFactORM.fact_type == fact_type)
    return session.query(query.exists()).scalar()
