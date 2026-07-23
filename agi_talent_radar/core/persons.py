"""人员主档：用 fingerprint 把同一自然人的多次评估/邀请归并到一档。"""
from __future__ import annotations

import hashlib
import re
import uuid

from agi_talent_radar.core.db.orm import PersonORM

PERSON_TYPES = {"student", "social", "guest"}


def normalize_identity(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").lower())


def person_fingerprint(name: str, org: str = "", direction: str = "") -> str:
    base = "|".join([normalize_identity(name), normalize_identity(org), normalize_identity(direction)])
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:32]


def find_person(session, name: str, org: str = "", direction: str = "") -> PersonORM | None:
    """先精确指纹，再退化到纯姓名指纹（早期主档可能缺机构/方向）。"""
    person = session.query(PersonORM).filter_by(fingerprint=person_fingerprint(name, org, direction)).first()
    if person is not None:
        return person
    if org or direction:
        return session.query(PersonORM).filter_by(fingerprint=person_fingerprint(name)).first()
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
