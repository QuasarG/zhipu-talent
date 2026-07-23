"""嘉宾画像端到端演示：姓名+机构 → AMiner画像 + 学术核查 + 舆情分级。

临时演示脚本，用 SQLite 内存库，不持久化。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from agi_talent_radar.core.db.orm import Base
from agi_talent_radar.core.guest_profile_service import run_guest_profile


def main():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    name = "罗开平"
    org = "北京航空航天大学"
    direction = ""
    print(f"=== 嘉宾画像: {name} / {org} ===\n")

    with Session() as session:
        profile = run_guest_profile(session, name=name, org=org, direction=direction)

    # 画像区
    sp = profile.scholar_profile
    print(f"【学术画像】数据源: {sp.data_source}")
    print(f"  姓名: {sp.name}  机构: {sp.affiliation or sp.org}")
    print(f"  引用: {sp.citation_count}  论文数: {sp.publication_count}  h-index: {sp.hindex}")
    if sp.research_directions:
        print("  研究方向:")
        for d in sp.research_directions:
            print(f"    - {d.name}  (证据: {d.evidence})")
    if sp.representative_works:
        print("  代表成果:")
        for w in sp.representative_works:
            print(f"    - {w.title}  ({w.venue} {w.year}, {w.role})")

    # 学术核查区
    ac = profile.academic_summary
    print(f"\n【学术核查】verified={ac.get('verified_count',0)} mismatch={ac.get('mismatch_count',0)} unverifiable={ac.get('unverifiable_count',0)}")
    for d in ac.get("key_discrepancies", []):
        print(f"    ⚠ {d}")

    # 舆情区
    level_map = {"red": "🔴 红", "yellow": "🟡 黄", "green": "🟢 绿"}
    print(f"\n【舆情分级】{level_map.get(profile.reputation_level, profile.reputation_level)}")
    if profile.reputation_rationale:
        print(f"  理由: {profile.reputation_rationale}")
    for ev in profile.reputation_events:
        print(f"  - [{ev.get('category')}] {ev.get('summary')} ({ev.get('identity_match')})")
        for url in ev.get("source_urls", []):
            print(f"      来源: {url}")

    # 警告区
    if profile.warnings:
        print("\n【运行警告】")
        for w in profile.warnings:
            print(f"  - {w}")
    print("\n=== 完成 ===")


if __name__ == "__main__":
    main()
