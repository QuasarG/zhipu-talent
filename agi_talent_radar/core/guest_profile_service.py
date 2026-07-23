"""嘉宾画像服务：主档归并 → 学术画像 → 学术核查 → 舆情分级 → 落库。

三链组装：build_scholar_profile（方向+成果）+ run_academic_check（成果核查）
+ run_reputation_check（舆情红黄绿）。失败链路记 warning，不拖死整体。
"""
from __future__ import annotations

from agi_talent_radar.agents.academic import run_academic_check
from agi_talent_radar.agents.academic.models import AcademicReport
from agi_talent_radar.agents.guest import GuestProfile, ScholarProfile, build_scholar_profile
from agi_talent_radar.agents.reputation import PersonIdentity, run_reputation_check
from agi_talent_radar.core.db.orm import ReputationReportORM
from agi_talent_radar.core.fact_cache import cache_fact, fetch_cached_facts
from agi_talent_radar.core.persons import get_or_create_person


def run_guest_profile(
    session,
    name: str,
    org: str = "",
    direction: str = "",
    person_type: str = "guest",
) -> GuestProfile:
    """嘉宾画像完整入口：姓名+机构+方向 → 三链画像报告 + 落库。"""
    if not (name or "").strip():
        raise ValueError("姓名不能为空。")

    person = get_or_create_person(session, name=name.strip(), org=org, direction=direction, person_type=person_type)
    warnings: list[str] = []

    # 链1: 学术画像（方向 + 代表成果）—— 优先读缓存，未命中才调外部
    scholar, scholar_cached = _get_scholar_profile_cached(session, person)
    warnings.extend(scholar.warnings)

    # 链2: 学术核查（用代表成果做 OpenAlex 对齐）
    academic_report, academic_summary = _run_academic_for_guest(person.name, scholar)
    if academic_report and academic_report.warnings:
        warnings.extend(academic_report.warnings)

    # 链3: 舆情分级
    rep_level, rep_rationale, rep_events, rep_warnings = _run_reputation_for_guest(person.name, person.org, person.direction)
    warnings.extend(rep_warnings)

    profile = GuestProfile(
        name=person.name,
        org=person.org,
        direction=person.direction,
        scholar_profile=scholar,
        academic_summary=academic_summary,
        reputation_level=rep_level,
        reputation_rationale=rep_rationale,
        reputation_events=rep_events,
        warnings=warnings,
    )

    _persist_guest_profile(session, person.id, profile, scholar, academic_report, scholar_cached)
    session.commit()
    return profile


def _get_scholar_profile_cached(session, person) -> tuple[ScholarProfile, bool]:
    """画像优先读缓存，未命中才拉外部；返回 (profile, from_cache)。"""
    cached = fetch_cached_facts(session, person.id, source="aminer", fact_type="scholar_profile")
    if not cached:
        cached = fetch_cached_facts(session, person.id, source="web_search", fact_type="scholar_profile")
    if cached:
        scholar = ScholarProfile.model_validate(cached[0].payload)
        scholar.warnings.append("命中缓存，跳过外部画像拉取。")
        return scholar, True
    scholar = build_scholar_profile(name=person.name, org=person.org, direction=person.direction)
    return scholar, False


def _run_academic_for_guest(name: str, scholar: ScholarProfile) -> tuple[AcademicReport | None, dict]:
    """把代表成果转成 publications 列表，喂给学术核查链。"""
    works = [w for w in scholar.representative_works if w.title.strip()]
    if not works:
        return None, {"verified_count": 0, "mismatch_count": 0, "unverifiable_count": 0, "note": "无代表成果可核查"}
    publications = [w.title for w in works]
    try:
        report = run_academic_check(name=name, publications=publications)
    except Exception as exc:
        return None, {"verified_count": 0, "mismatch_count": 0, "unverifiable_count": 0, "note": f"学术核查失败: {exc}"}
    summary = {
        "verified_count": report.verified_count,
        "mismatch_count": report.mismatch_count,
        "unverifiable_count": report.unverifiable_count,
        "key_discrepancies": _collect_key_discrepancies(report),
    }
    return report, summary


def _collect_key_discrepancies(report: AcademicReport) -> list[str]:
    """只留 mismatch 的差异点，verified/unverifiable 不展开。"""
    discrepancies: list[str] = []
    for alignment in report.alignments:
        if alignment.verdict == "mismatch":
            for d in alignment.discrepancies:
                discrepancies.append(f"{alignment.claim.title[:40]}: {d}")
    return discrepancies


def _run_reputation_for_guest(name: str, org: str, direction: str) -> tuple[str, str, list[dict], list[str]]:
    """跑舆情链，返回 (level, rationale, events, warnings)。"""
    warnings: list[str] = []
    try:
        identity = PersonIdentity(name=name, org=org, direction=direction)
        report = run_reputation_check(identity)
    except Exception as exc:
        warnings.append(f"舆情核查失败: {exc}")
        return "green", "", [], warnings
    events = [event.model_dump() for event in report.events]
    if report.warnings:
        warnings.extend(report.warnings)
    return report.level, report.rationale, events, warnings


def _persist_guest_profile(
    session,
    person_id: str,
    profile: GuestProfile,
    scholar: ScholarProfile,
    academic_report: AcademicReport | None,
    scholar_cached: bool,
) -> None:
    """画像结果落库：ExternalFactORM 缓存 + ReputationReportORM 舆情。命中缓存则跳过画像写入。"""
    # 学术画像缓存（命中缓存则不重复写）
    if not scholar_cached:
        cache_fact(session, person_id, source=scholar.data_source, fact_type="scholar_profile", payload=scholar.model_dump())
    # 学术核查结果缓存
    if academic_report:
        cache_fact(session, person_id, source="openalex", fact_type="academic_check", payload=academic_report.model_dump())
    # 舆情报告落库（绿自动终态，红/黄挂人工复核）
    session.add(
        ReputationReportORM(
            person_id=person_id,
            level=profile.reputation_level,
            events=profile.reputation_events,
            review_status="confirmed" if profile.reputation_level == "green" else "pending",
        )
    )
