"""嘉宾/人员舆情核查服务：主档归并 → 舆情链 → 报告与证据落库。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from agi_talent_radar.agents.reputation import PersonIdentity, run_reputation_check
from agi_talent_radar.core.db.orm import ExternalFactORM, ReputationReportORM
from agi_talent_radar.core.persons import get_or_create_person

FACT_TTL_DAYS = 30


def run_guest_check(
    session,
    name: str,
    org: str = "",
    direction: str = "",
    person_type: str = "guest",
) -> dict:
    """guest_check 模式入口：只有姓名+机构+方向即可发起核查。"""
    if not (name or "").strip():
        raise ValueError("姓名不能为空。")
    person = get_or_create_person(session, name=name.strip(), org=org, direction=direction, person_type=person_type)
    identity = PersonIdentity(name=person.name, org=person.org, direction=person.direction)
    report = run_reputation_check(identity)

    record = ReputationReportORM(
        person_id=person.id,
        level=report.level,
        events=[event.model_dump() for event in report.events],
        # 绿色自动终态；红/黄必须人工复核
        review_status="confirmed" if report.level == "green" else "pending",
    )
    session.add(record)
    expires = datetime.now(timezone.utc) + timedelta(days=FACT_TTL_DAYS)
    for hit in report.hits:
        session.add(
            ExternalFactORM(
                person_id=person.id,
                source="web_search",
                fact_type="search_hit",
                payload=hit.model_dump(),
                source_url=hit.url,
                expires_at=expires,
            )
        )
    session.commit()
    session.refresh(record)
    return {
        "person_id": person.id,
        "name": person.name,
        "org": person.org,
        "direction": person.direction,
        "report_id": record.id,
        "level": record.level,
        "rationale": report.rationale,
        "events": record.events,
        "warnings": report.warnings,
        "review_status": record.review_status,
        "hit_count": len(report.hits),
    }


def review_reputation_report(session, report_id: int, action: str, reviewer: str = "", note: str = "") -> ReputationReportORM | None:
    """人工复核：confirm（确认风险成立）或 dismiss（驳回/误报）。"""
    if action not in {"confirmed", "dismissed"}:
        raise ValueError("action 必须是 confirmed 或 dismissed。")
    record = session.get(ReputationReportORM, report_id)
    if record is None:
        return None
    record.review_status = action
    record.reviewer = reviewer
    record.review_note = note
    record.reviewed_at = datetime.now(timezone.utc)
    session.commit()
    return record
