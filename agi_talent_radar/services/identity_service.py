"""入库身份归并（Intake Identity Resolution）服务。

策略（与计划 §阶段 2 + CONTEXT.md 对齐）：

- **第一层确定性匹配**：邮箱 / ORCID / AMiner ID 等稳定唯一标识精确一致。
  命中单一 person 即可自动归并；命中多个不同 person 则判 CONFLICT。
- **第二层 AI 模糊匹配**：姓名变体、机构、方向、时间线、论文。
  首版**只生成 NEEDS_REVIEW 建议**，不自动合并；
  等积累离线样本并验证误合并率后再单独放开"姓名+机构"规则。

该服务输出 ``IdentityResolution``，不修改 HR 跟进状态、不读取历史评分或
旧结论；后续评分节点只接收 ``matched_person_id`` 与本次身份判断。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from agi_talent_radar.core.db.orm import PersonORM
from agi_talent_radar.core.domain_models import (
    IdentityDecision,
    IdentityEvidence,
    IdentityResolution,
)


# 支持的稳定标识类型（按优先级降序）。
STABLE_ID_KEYS = ("orcid", "aminer_id", "email")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def resolve_intake_identity(
    evidence: IdentityEvidence,
    find_person_by_identifier: Callable[[str, str], PersonORM | None] | None = None,
    find_person_by_fingerprint: Callable[[str, str, str], PersonORM | None] | None = None,
    ai_matcher: Callable[[IdentityEvidence, list[PersonORM]], IdentityResolution | None] | None = None,
) -> IdentityResolution:
    """对一份入库简历执行身份归并。

    可注入回调（便于测试与未来切换数据源）：

    - ``find_person_by_identifier(kind, value)``：按稳定标识查 person；
      默认走 ``_default_find_by_identifier``（SQLAlchemy）。
    - ``find_person_by_fingerprint(name, org, direction)``：按姓名模糊查 person；
      默认走 ``_default_find_by_fingerprint``（SQLAlchemy）。
    - ``ai_matcher(evidence, candidates)``：AI 模糊匹配器；
      默认走 ``_default_ai_matcher``（保守的 NEEDS_REVIEW）。

    首版策略：

    1. 任一稳定标识命中 → 收集命中的 unique persons。
       - 0 命中：进入第二层。
       - 1 命中：返回 ``MATCHED`` + 自动归并建议。
       - ≥ 2 不同 person：返回 ``CONFLICT``，阻止合并。
    2. 第二层按姓名变体 + 机构 / 方向查询候选。
       - 多个候选且有冲突点 → ``CONFLICT``。
       - 单个候选且机构 / 方向相符 → ``NEEDS_REVIEW``（不自动合并）。
       - 无候选 → ``NEW``。
    """
    if find_person_by_identifier is None:
        find_person_by_identifier = _default_find_by_identifier
    if find_person_by_fingerprint is None:
        find_person_by_fingerprint = _default_find_by_fingerprint
    if ai_matcher is None:
        ai_matcher = _default_ai_matcher

    stable_ids = _collect_stable_ids(evidence)

    # ----- 第一层：稳定标识确定性匹配 -----
    matched: dict[str, tuple[PersonORM, list[str]]] = {}
    for kind, value in stable_ids:
        person = find_person_by_identifier(kind, value)
        if person is None:
            continue
        if person.id not in matched:
            matched[person.id] = (person, [f"{kind}={value}"])
        else:
            matched[person.id][1].append(f"{kind}={value}")

    if len(matched) >= 2:
        persons = list(matched.values())
        conflicts = [
            f"稳定标识同时指向多个 Person：{persons[0][0].id} 与 {persons[1][0].id}"
        ]
        return IdentityResolution(
            matched_person_id=None,
            decision=IdentityDecision.CONFLICT,
            confidence=0.95,
            supporting_evidence=sum((hits for _, hits in persons), []),
            conflicts=conflicts,
        )
    if len(matched) == 1:
        person, hits = next(iter(matched.values()))
        return IdentityResolution(
            matched_person_id=person.id,
            decision=IdentityDecision.MATCHED,
            confidence=0.95,
            supporting_evidence=[f"稳定标识命中：{hit}" for hit in hits],
            conflicts=[],
        )

    # ----- 第二层：AI 模糊匹配 -----
    candidates = _collect_fuzzy_candidates(evidence, find_person_by_fingerprint)
    ai_resolution = ai_matcher(evidence, candidates)
    if ai_resolution is not None:
        return ai_resolution

    return IdentityResolution(
        matched_person_id=None,
        decision=IdentityDecision.NEW,
        confidence=0.5,
        supporting_evidence=["无稳定标识命中，AI 模糊匹配也无可靠候选。"],
        conflicts=[],
    )


def _collect_stable_ids(evidence: IdentityEvidence) -> list[tuple[str, str]]:
    """从证据中提取稳定标识，按 STABLE_ID_KEYS 顺序去重。

    来源优先级：
    1. ``evidence.stable_ids``（dict，key 为 email/orcid/aminer_id）；
    2. ``evidence.emails``（兜底，作为 email 来源）。
    """
    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    stable_map: dict[str, str] = dict(evidence.stable_ids or {})
    # emails 列表兜底，避免调用方只填了 emails。
    for email in evidence.emails or []:
        stable_map.setdefault("email", email)

    for key in STABLE_ID_KEYS:
        value = stable_map.get(key)
        if not value:
            continue
        normalized = _normalize_id(value)
        if not normalized:
            continue
        item = (key, normalized)
        if item not in seen:
            seen.add(item)
            pairs.append(item)
    return pairs


def _normalize_id(value: str) -> str:
    return (value or "").strip().lower()


def _collect_fuzzy_candidates(
    evidence: IdentityEvidence,
    find_person_by_fingerprint: Callable[[str, str, str], PersonORM | None],
) -> list[PersonORM]:
    """按姓名变体逐个查 person 候选；同 person 仅保留一次。"""
    candidates: dict[str, PersonORM] = {}
    name_variants = evidence.name_variants or []
    if not name_variants:
        return []
    for name_variant in name_variants:
        if not name_variant:
            continue
        person = find_person_by_fingerprint(name_variant, "", "")
        if person is not None and person.id not in candidates:
            candidates[person.id] = person
    return list(candidates.values())


def _default_ai_matcher(
    evidence: IdentityEvidence,
    candidates: list[PersonORM],
) -> IdentityResolution | None:
    """保守的 AI 模糊匹配：单候选 + 机构/方向相符 → NEEDS_REVIEW；不自动合并。

    多候选时直接判 CONFLICT；无候选时返回 None，由上层降级为 NEW。
    """
    if not candidates:
        return None
    if len(candidates) >= 2:
        ids = [c.id for c in candidates]
        return IdentityResolution(
            matched_person_id=None,
            decision=IdentityDecision.CONFLICT,
            confidence=0.6,
            supporting_evidence=[],
            conflicts=[f"姓名变体同时匹配多个 Person：{ids}"],
        )

    candidate = candidates[0]
    supporting = [f"姓名变体匹配候选：{candidate.id}（{candidate.name}）"]
    if candidate.org:
        supporting.append(f"候选机构：{candidate.org}")
    if candidate.direction:
        supporting.append(f"候选方向：{candidate.direction}")
    return IdentityResolution(
        matched_person_id=candidate.id,
        decision=IdentityDecision.NEEDS_REVIEW,
        confidence=0.5,
        supporting_evidence=supporting,
        conflicts=[],
    )


def _default_find_by_identifier(kind: str, value: str) -> PersonORM | None:
    """SQLAlchemy 默认：按 person.identifiers JSON 字段查。"""
    from sqlalchemy import text

    from agi_talent_radar.core.database import get_session

    with get_session() as session:
        # SQLite 不支持 JSON path；用 like 兜底，生产 MySQL 用 JSON_EXTRACT。
        row = (
            session.query(PersonORM)
            .filter(PersonORM.identifiers.isnot(None))
            .filter(text(f"identifiers LIKE :pat"))
            .params(pat=f'%"{kind}": "{value}"%')
            .first()
        )
        return row


def _default_find_by_fingerprint(name: str, org: str, direction: str) -> PersonORM | None:
    from agi_talent_radar.core.persons import find_person

    from agi_talent_radar.core.database import get_session

    with get_session() as session:
        return find_person(session, name, org, direction)


__all__ = [
    "resolve_intake_identity",
    "STABLE_ID_KEYS",
]