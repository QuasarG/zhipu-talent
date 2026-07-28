"""外部事实版本与审核服务（阶段 6）。

策略（与计划 §阶段 6 对齐）：

- **去重**：按稳定 dedupe_key 归并；完全相同的事实不重复写入。
- **版本替代**：内容变化（raw_payload_hash 不同）时创建新版本，
  旧版本 superseded_at 写入时间、新版本 supersedes_id 指向旧版本。
- **冲突检测**：与已确认事实冲突时生成 conflict 审核项，不覆盖旧值。
- **审核**：confirmed 事实不会被自动降级；人工确认 / 驳回 / 解除都写审计。
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from agi_talent_radar.core.db.orm import ExternalFactORM


FACT_VERIFICATION_STATUSES = {
    "confirmed",
    "pending",
    "conflict",
    "disproved",
    "superseded",
}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def compute_dedupe_key(
    source: str,
    fact_type: str,
    title: str,
    source_url: str,
) -> str:
    base = "|".join(
        [
            str(source or ""),
            str(fact_type or ""),
            str(title or "")[:200],
            str(source_url or ""),
        ]
    )
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:32]


def compute_identity_key(person_id: str, fact_type: str, subject: str = "") -> str:
    base = "|".join([str(person_id or ""), str(fact_type or ""), str(subject or "")])
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:32]


def compute_payload_hash(payload: dict[str, Any]) -> str:
    """对 payload 内容做哈希，用于检测是否变化。"""
    if not payload:
        return ""
    # 排序键保证稳定哈希
    serialized = repr(sorted(payload.items(), key=lambda kv: kv[0]))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:32]


def append_versioned_fact(
    session,
    person_id: str,
    source: str,
    fact_type: str,
    payload: dict[str, Any] | None = None,
    source_url: str = "",
    query_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """追加一条外部事实，按版本策略处理。

    返回 ``{fact_id, action}``，action 取值：
    - ``inserted``      首次写入（pending）
    - ``deduped``       完全相同，未写入
    - ``versioned``     内容变化，旧版本 superseded，新版本 pending 指向旧
    - ``conflict``      与已确认事实冲突，作为 conflict 版本写入（旧不动）
    """
    payload = payload or {}
    title = str(payload.get("title", "")) or fact_type
    dedupe_key = compute_dedupe_key(source, fact_type, title, source_url)
    identity_key = compute_identity_key(person_id, fact_type)
    payload_hash = compute_payload_hash(payload)

    # 找同 dedupe_key 的现有事实（按 id 倒序取最新）
    existing = (
        session.query(ExternalFactORM)
        .filter_by(person_id=person_id, dedupe_key=dedupe_key)
        .order_by(ExternalFactORM.id.desc())
        .first()
    )

    if existing is None:
        row = ExternalFactORM(
            person_id=person_id,
            source=source,
            fact_type=fact_type,
            payload=payload,
            source_url=source_url,
            identity_key=identity_key,
            dedupe_key=dedupe_key,
            verification_status="pending",
            valid_from=_now(),
            query_context=query_context or {},
            raw_payload_hash=payload_hash,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return {"fact_id": row.id, "action": "inserted"}

    # 内容完全相同 → 去重
    if existing.raw_payload_hash == payload_hash and existing.verification_status != "superseded":
        return {"fact_id": existing.id, "action": "deduped"}

    # 与已确认事实内容不同 → conflict
    if existing.verification_status == "confirmed":
        conflict_row = ExternalFactORM(
            person_id=person_id,
            source=source,
            fact_type=fact_type,
            payload=payload,
            source_url=source_url,
            identity_key=identity_key,
            dedupe_key=dedupe_key,
            verification_status="conflict",
            valid_from=_now(),
            supersedes_id=existing.id,
            query_context=query_context or {},
            raw_payload_hash=payload_hash,
        )
        session.add(conflict_row)
        session.commit()
        session.refresh(conflict_row)
        return {"fact_id": conflict_row.id, "action": "conflict"}

    # 内容变化但旧版本非 confirmed → 创建新版本，旧版本 superseded
    now = _now()
    existing.superseded_at = now
    new_row = ExternalFactORM(
        person_id=person_id,
        source=source,
        fact_type=fact_type,
        payload=payload,
        source_url=source_url,
        identity_key=identity_key,
        dedupe_key=dedupe_key,
        verification_status="pending",
        valid_from=now,
        supersedes_id=existing.id,
        query_context=query_context or {},
        raw_payload_hash=payload_hash,
    )
    session.add(new_row)
    session.commit()
    session.refresh(new_row)
    return {"fact_id": new_row.id, "action": "versioned"}


def confirm_fact(
    session,
    fact_id: int,
    reviewer: str,
    note: str = "",
) -> ExternalFactORM:
    """人工确认一条 pending / conflict 事实为 confirmed。

    确认后只升级这一条；不删除冲突版本（两者并存）。
    """
    if not reviewer or not reviewer.strip():
        raise ValueError("reviewer 必填，禁止自动确认。")
    row = session.get(ExternalFactORM, fact_id)
    if row is None:
        raise ValueError(f"事实不存在: {fact_id}")
    if row.verification_status == "confirmed":
        return row
    row.verification_status = "confirmed"
    row.query_context = dict(row.query_context or {})
    row.query_context["confirmed_by"] = reviewer
    row.query_context["confirm_note"] = note
    session.commit()
    session.refresh(row)
    return row


def dismiss_fact(
    session,
    fact_id: int,
    reviewer: str,
    note: str = "",
) -> ExternalFactORM:
    """人工驳回一条事实（disproved）。不物理删除。"""
    if not reviewer or not reviewer.strip():
        raise ValueError("reviewer 必填，禁止自动驳回。")
    row = session.get(ExternalFactORM, fact_id)
    if row is None:
        raise ValueError(f"事实不存在: {fact_id}")
    row.verification_status = "disproved"
    row.query_context = dict(row.query_context or {})
    row.query_context["dismissed_by"] = reviewer
    row.query_context["dismiss_note"] = note
    session.commit()
    session.refresh(row)
    return row


def list_current_facts(
    session,
    person_id: str,
    fact_type: str = "",
    include_history: bool = False,
) -> list[ExternalFactORM]:
    """列出当前版本（superseded_at IS NULL）。

    ``include_history=True`` 时也返回历史版本。
    """
    query = session.query(ExternalFactORM).filter_by(person_id=person_id)
    if fact_type:
        query = query.filter_by(fact_type=fact_type)
    if not include_history:
        query = query.filter(ExternalFactORM.superseded_at.is_(None))
    return query.order_by(ExternalFactORM.fetched_at.desc(), ExternalFactORM.id.desc()).all()


__all__ = [
    "FACT_VERIFICATION_STATUSES",
    "compute_dedupe_key",
    "compute_identity_key",
    "compute_payload_hash",
    "append_versioned_fact",
    "confirm_fact",
    "dismiss_fact",
    "list_current_facts",
]