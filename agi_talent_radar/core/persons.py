"""人员主档：用 fingerprint 把同一自然人的多次评估/邀请归并到一档。"""
from __future__ import annotations

import hashlib
import re
import uuid

from agi_talent_radar.core.db.orm import CandidateORM, PersonORM, ReputationReportORM, TalentGroupORM
from sqlalchemy import Text, func, or_ as _sql_or

PERSON_TYPES = {"student", "social", "guest"}


def normalize_identity(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").lower())


def person_fingerprint(name: str, org: str = "", direction: str = "") -> str:
    base = "|".join([normalize_identity(name), normalize_identity(org), normalize_identity(direction)])
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:32]


def find_person(session, name: str, org: str = "", direction: str = "") -> PersonORM | None:
    """按渐进补全的身份字段查找人物，避免后补方向时重复建档。"""
    person = session.query(PersonORM).filter_by(fingerprint=person_fingerprint(name, org, direction)).first()
    if person is not None:
        return person
    if org or direction:
        person = session.query(PersonORM).filter_by(fingerprint=person_fingerprint(name)).first()
        if person is not None:
            return person

        normalized_name = normalize_identity(name)
        candidates = (
            session.query(PersonORM)
            .filter(func.lower(func.replace(PersonORM.name, " ", "")) == normalized_name)
            .all()
        )
        compatible = [
            candidate
            for candidate in candidates
            if (
                not org
                or not candidate.org
                or normalize_identity(candidate.org) == normalize_identity(org)
            )
            and (
                not direction
                or not candidate.direction
                or normalize_identity(candidate.direction) == normalize_identity(direction)
            )
        ]
        if len(compatible) == 1:
            return compatible[0]
    return None


def get_or_create_person(
    session,
    name: str,
    org: str = "",
    direction: str = "",
    person_type: str = "student",
) -> PersonORM:
    person = find_person(session, name, org, direction)
    if person is not None:
        if org and not person.org:
            person.org = org
        if direction and not person.direction:
            person.direction = direction
        session.flush()
        return person
    person = PersonORM(
        id=uuid.uuid4().hex,
        name=name or "",
        org=org or "",
        direction=direction or "",
        fingerprint=person_fingerprint(name, org, direction),
        person_type=person_type if person_type in PERSON_TYPES else "student",
    )
    session.add(person)
    session.flush()
    return person


def list_persons(
    session,
    person_type: str = "",
    name: str = "",
    q: str = "",
    level: str = "",
    group_id: str = "",
    limit: int = 50,
    offset: int = 0,
) -> list[PersonORM]:
    """人才库列表：按类型/全文搜索/舆情等级/分组筛选，分页返回。只读不 commit。

    q 语义：对 name/org/direction/schools 做全文 OR 模糊匹配（学校/机构/track/方向都能搜到）。
    name 参数保留兼容（精确 name LIKE）；q 和 name 同时给时各自独立过滤。
    group_id 语义："ungrouped" → 过滤 NULL；具体 id → 该分组；空 → 全部。
    """
    from sqlalchemy import or_

    query = session.query(PersonORM)
    if person_type:
        query = query.filter(PersonORM.person_type == person_type)
    if name:
        query = query.filter(PersonORM.name.like(f"%{name}%"))
    if q:
        kw = f"%{q}%"
        query = query.filter(
            or_(
                PersonORM.name.like(kw),
                PersonORM.org.like(kw),
                PersonORM.direction.like(kw),
                PersonORM.schools.cast(Text).like(kw),
            )
        )
    if level:
        query = query.join(
            ReputationReportORM, PersonORM.id == ReputationReportORM.person_id, isouter=True,
        ).filter(ReputationReportORM.level == level)
    if group_id == "ungrouped":
        query = query.filter(PersonORM.group_id.is_(None))
    elif group_id:
        query = query.filter(PersonORM.group_id == group_id)
    # selectinload 预载 brief 用到的关系：消除列表页逐人 lazy load 的 N+1
    from sqlalchemy.orm import selectinload
    return (
        query.options(
            selectinload(PersonORM.evaluations),
            selectinload(PersonORM.reputation_reports),
            # 新准入评估（一岗一评）走 candidates.person_id 反查，列表页快照用
            selectinload(PersonORM.candidates).selectinload(CandidateORM.jd_assessments),
        )
        .order_by(PersonORM.updated_at.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )


def get_person_detail(session, person_id: str) -> PersonORM | None:
    """人才详情：主档 + 评估历史 + 舆情报告，通过 relationship 一次性带出。只读不 commit。"""
    return session.query(PersonORM).filter_by(id=person_id).first()


def list_talent_groups(session) -> list[TalentGroupORM]:
    """列出所有分组（按 sort_order），只读不 commit。"""
    return session.query(TalentGroupORM).order_by(TalentGroupORM.sort_order.asc()).all()


def count_persons_by_group(session, group_id: str) -> int:
    return session.query(PersonORM).filter_by(group_id=group_id).count()


def move_person_to_group(session, person_id: str, group_id: str | None) -> bool:
    """一人移入分组（一对多，旧分组自动移出）。返回是否找到人。"""
    person = session.get(PersonORM, person_id)
    if person is None:
        return False
    person.group_id = group_id  # None = 移到未分组
    session.commit()
    return True


def batch_move_persons(session, person_ids: list[str], group_id: str | None) -> int:
    """批量移动到同一分组，返回实际更新数。"""
    if not person_ids:
        return 0
    updated = (
        session.query(PersonORM)
        .filter(PersonORM.id.in_(person_ids))
        .update({PersonORM.group_id: group_id}, synchronize_session=False)
    )
    session.commit()
    return updated
