"""导师唯一学校归属回填：人工核验映射 > 申请表 title 解析。

用法（服务器上）：
    cd /opt/zhipu-talent/current && set -a && source /etc/zhipu-talent.env && set +a
    /opt/zhipu-talent/venv/bin/python scripts/backfill_advisor_schools.py

回填规则（advisors.school 三列）：
1. graph_identity.ADVISOR_SCHOOLS 命中（人工逐封看过推荐信原件/扫描件的结论）
   → school_source=verified, confidence=high；
2. 否则 guess_school_from_title(advisor.title)（申请表「导师单位/职务」快照，
   多导师拼接段按导师名定位）→ school_source=title, confidence=medium；
3. 都没有 → 置空，图谱端挂「归属待核验」占位，待人工补录。

幂等：覆盖表/解析结果直接覆写三列；人工在 DB 里的临时手改会被本脚本收敛，
长期修正请改 ADVISOR_SCHOOLS。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agi_talent_radar.core.db.orm import AdvisorORM
from agi_talent_radar.core.db.runtime import get_session
from agi_talent_radar.core.database import init_db
from agi_talent_radar.scholarship.graph_identity import (
    ADVISOR_SCHOOLS,
    canonical_advisor,
    guess_school_from_title,
)


def advisor_school(name: str, title: str) -> tuple[str, str, str]:
    """(school, source, confidence)；解析不出返回空三元组。"""
    verified = ADVISOR_SCHOOLS.get(canonical_advisor(name), "")
    if verified:
        return verified, "verified", "high"
    guessed = guess_school_from_title(title or "", name or "")
    if guessed:
        return guessed, "title", "medium"
    return "", "", ""


def main() -> int:
    init_db()
    n_verified, n_title, n_missing = 0, 0, 0
    with get_session() as session:
        for advisor in session.query(AdvisorORM).all():
            school, source, confidence = advisor_school(advisor.name, advisor.title)
            if source == "verified":
                n_verified += 1
            elif source == "title":
                n_title += 1
            else:
                n_missing += 1
            advisor.school = school
            advisor.school_source = source
            advisor.school_confidence = confidence
        session.commit()
    print(f"导师学校回填完成：人工核验 {n_verified} | title 解析 {n_title} | 待人工 {n_missing}")
    if n_missing:
        with get_session() as session:
            names = [a.name for a in session.query(AdvisorORM).all()
                     if not (a.school or "").strip()]
        print("待人工补录（图谱暂挂「归属待核验」）：" + "、".join(names))
    return 0


if __name__ == "__main__":
    sys.exit(main())
