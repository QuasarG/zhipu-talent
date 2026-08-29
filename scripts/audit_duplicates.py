# -*- coding: utf-8 -*-
"""存量数据只读审计：疑似重复人物 + Person-Candidate 一对一违规。

不做任何写入；输出 JSON 报告供人工确认后再决定归并（归并必须走人工流程，
严禁按姓名自动合并或删除）。

用法：
    python scripts/audit_duplicates.py            # 控制台摘要
    python scripts/audit_duplicates.py --json     # 完整 JSON（重定向保存）
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agi_talent_radar.core.db.runtime import get_session  # noqa: E402
from agi_talent_radar.core.db.orm import (
    CandidateJdAssessmentORM,
    CandidateORM,
    EvaluationORM,
    PersonORM,
    ReputationReportORM,
    ResumeSubmissionORM,
)
from agi_talent_radar.core.persons import normalize_identity


def _person_payload(session, person: PersonORM) -> dict:
    candidates = session.query(CandidateORM).filter_by(person_id=person.id).all()
    return {
        "person_id": person.id,
        "name": person.name,
        "org": person.org,
        "direction": person.direction,
        "identity_conflict": bool(person.identity_conflict),
        "candidates": len(candidates),
        "evaluations": session.query(EvaluationORM).filter_by(person_id=person.id).count(),
        "reputation_reports": session.query(ReputationReportORM).filter_by(person_id=person.id).count(),
        "submissions": session.query(ResumeSubmissionORM).filter_by(person_id=person.id).count(),
    }


def find_duplicate_groups(session) -> list[dict]:
    """同名组：归一化姓名聚组，只标记'信息兼容可能重复'的组并给出依据。"""
    by_name: dict[str, list[PersonORM]] = defaultdict(list)
    for person in session.query(PersonORM).all():
        by_name[normalize_identity(person.name or "")].append(person)

    groups = []
    for normalized_name, persons in by_name.items():
        if len(persons) < 2 or not normalized_name:
            continue
        entries = [_person_payload(session, p) for p in persons]
        has_empty_org = any(not p.org for p in persons)
        same_org = len({normalize_identity(p.org) for p in persons if p.org}) == 1 and all(p.org for p in persons)
        groups.append({
            "normalized_name": normalized_name,
            "count": len(persons),
            # same_org=True 才是"疑似同一人多次建档"；含空 org 属于信息不足，留给人工判断
            "likely_same_person": bool(same_org),
            "insufficient_info": bool(has_empty_org and not same_org),
            "persons": entries,
        })
    groups.sort(key=lambda g: (-g["count"], g["normalized_name"]))
    return groups


def find_candidate_violations(session) -> list[dict]:
    """一个 Person 挂多个 Candidate 的违规（应有唯一约束但尚未加）。"""
    counts: dict[str, int] = defaultdict(int)
    for candidate in session.query(CandidateORM).filter(CandidateORM.person_id.isnot(None)).all():
        counts[candidate.person_id] += 1
    violations = []
    for person_id, count in counts.items():
        if count < 2:
            continue
        person = session.get(PersonORM, person_id)
        rows = session.query(CandidateORM).filter_by(person_id=person_id).all()
        # 每个 candidate 的 admissions 数（用于人工判断保留哪个）
        admissions = {
            c.id: session.query(CandidateJdAssessmentORM).filter_by(candidate_id=c.id).count()
            for c in rows
        }
        violations.append({
            "person_id": person_id,
            "person_name": person.name if person else "?",
            "candidate_count": count,
            "candidate_ids": [c.id for c in rows],
            "admissions_per_candidate": admissions,
        })
    return violations


def build_report() -> dict:
    with get_session() as session:
        duplicates = find_duplicate_groups(session)
        violations = find_candidate_violations(session)
        return {
            "summary": {
                "total_persons": session.query(PersonORM).count(),
                "duplicate_name_groups": len(duplicates),
                "likely_same_person_groups": sum(1 for g in duplicates if g["likely_same_person"]),
                "conflict_flagged_persons": session.query(PersonORM)
                    .filter(PersonORM.identity_conflict.is_(True)).count(),
                "person_multi_candidate_violations": len(violations),
            },
            "duplicate_groups": duplicates,
            "candidate_violations": violations,
            "note": "只读审计。归并需人工确认后走事务性流程，禁止按姓名自动合并。",
        }


def main() -> int:
    as_json = "--json" in sys.argv
    report = build_report()
    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    s = report["summary"]
    print(f"人物总数: {s['total_persons']}")
    print(f"同名组: {s['duplicate_name_groups']}（疑似同一人: {s['likely_same_person_groups']}）")
    print(f"identity_conflict 已标记: {s['conflict_flagged_persons']}")
    print(f"一人多 Candidate 违规: {s['person_multi_candidate_violations']}")
    for g in report["duplicate_groups"]:
        tag = "疑似同一人" if g["likely_same_person"] else ("信息不足" if g["insufficient_info"] else "机构不同/正常独立")
        print(f"  [{tag}] {g['normalized_name']} × {g['count']}")
    for v in report["candidate_violations"]:
        print(f"  [多Candidate] {v['person_name']}: {v['candidate_ids']}")
    if report["duplicate_groups"] or report["candidate_violations"]:
        print("详情: python scripts/audit_duplicates.py --json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
