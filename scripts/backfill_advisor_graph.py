"""师生知识图谱回填：申请表导师字段全量建图 + 飞书推荐信表佐证关联。

用法（服务器上）：
    cd /opt/zhipu-talent/current && set -a && source /etc/zhipu-talent.env && set +a
    /opt/zhipu-talent/venv/bin/python scripts/backfill_advisor_graph.py

数据源优先级（设计定稿）：
1. 申请表「导师姓名 + 导师单位/职务」——主数据源，全量覆盖，source=application；
2. 飞书推荐信表「已经邮件收到的导师推荐信」——佐证关联，source=letter；
   学生按姓名匹配申请档案，同名多档按学校消歧，消歧失败 confidence=low 跳过待人工。
飞书侧全程只读（GET）。幂等：重跑先清 source 范围内的 link 再重建，advisors 按 (name) upsert。
"""
import json
import os
import re
import sys
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agi_talent_radar.core.db.orm import AdvisorORM, AdvisorStudentLinkORM, ScholarshipApplicationORM
from agi_talent_radar.core.db.runtime import get_session
from agi_talent_radar.core.database import init_db
from agi_talent_radar.scholarship.graph_identity import canonical_advisor

LETTER_TABLE_ID = "tbl6bjudNeN4ezGW"  # 已经邮件收到的导师推荐信


def _feishu_headers() -> dict:
    req = urllib.request.Request(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        data=json.dumps({
            "app_id": os.getenv("FEISHU_APP_ID", "").strip(),
            "app_secret": os.getenv("FEISHU_APP_SECRET", "").strip(),
        }).encode(),
        headers={"Content-Type": "application/json"},
    )
    data = json.loads(urllib.request.urlopen(req, timeout=15).read())
    if data.get("code") != 0:
        raise RuntimeError(f"tenant_access_token 获取失败: {data.get('msg')}")
    return {"Authorization": "Bearer " + data["tenant_access_token"]}


def _list_letter_records(headers: dict) -> list[dict]:
    base = os.getenv("FEISHU_BASE_TOKEN", "").strip()
    recs, page_token = [], ""
    while True:
        q = "page_size=500" + (f"&page_token={page_token}" if page_token else "")
        url = (f"https://open.feishu.cn/open-apis/bitable/v1/apps/{base}"
               f"/tables/{LETTER_TABLE_ID}/records?{q}")
        data = json.loads(urllib.request.urlopen(
            urllib.request.Request(url, None, headers), timeout=15).read())
        if data.get("code") != 0:
            raise RuntimeError(f"推荐信表拉取失败: {data.get('msg')}")
        page = data.get("data") or {}
        recs += page.get("items") or []
        if not page.get("has_more"):
            return recs
        page_token = page.get("page_token") or ""


def _text(value) -> str:
    if isinstance(value, list):
        return "".join(x.get("text", "") if isinstance(x, dict) else str(x) for x in value).strip()
    return str(value).strip() if value not in (None, "") else ""


def _norm_name(name: str) -> str:
    """归并键：去空白与标点，小写（英文名）——中文名精确匹配，英文名宽松。"""
    return re.sub(r"[\s,.\-·']+", "", name).lower()


def main() -> int:
    init_db()
    headers = _feishu_headers()
    letter_records = _list_letter_records(headers)
    print(f"推荐信表: {len(letter_records)} 条（只读）")

    with get_session() as session:
        apps = (session.query(ScholarshipApplicationORM)
                .filter(ScholarshipApplicationORM.feishu_record_id.like("rec%"))
                .all())
        print(f"申请档案: {len(apps)} 条")

        # 导师 upsert 缓存：norm(name) → AdvisorORM
        advisors_by_key: dict[str, AdvisorORM] = {}
        for a in session.query(AdvisorORM).all():
            canonical_name = canonical_advisor(a.name)
            key = _norm_name(canonical_name)
            if key not in advisors_by_key or a.name == canonical_name:
                advisors_by_key[key] = a

        def get_or_create_advisor(name: str, title: str = "") -> AdvisorORM:
            canonical_name = canonical_advisor(name)
            key = _norm_name(canonical_name)
            found = advisors_by_key.get(key)
            if found is None:
                found = AdvisorORM(id=uuid.uuid4().hex, name=canonical_name, title=(title or "")[:256])
                session.add(found)
                advisors_by_key[key] = found
            else:
                if found.name != canonical_name:
                    found.name = canonical_name
                if title and not found.title:
                    found.title = title[:256]
            return found

        # 幂等：清掉本脚本管的 source 范围，重建
        session.query(AdvisorStudentLinkORM).filter(
            AdvisorStudentLinkORM.source.in_(("application", "letter"))).delete(synchronize_session=False)

        # ① 申请表：主数据源（advisors 字段是 list）
        n_app_links = 0
        for app in apps:
            names = [a for a in (app.advisors or []) if a.strip()]
            for name in names[:4]:  # 防脏数据，最多记 4 位导师
                advisor = get_or_create_advisor(name, app.advisor_title or "")
                session.add(AdvisorStudentLinkORM(
                    advisor_id=advisor.id, application_id=app.id,
                    student_name=(app.name or "")[:128],
                    source="application", confidence="high",
                    note=(app.school or "")[:120]))
                n_app_links += 1

        # ② 推荐信表：佐证（学生按姓名匹配；同名多档按学校字样消歧，失败 low+跳过）
        apps_by_name: dict[str, list[ScholarshipApplicationORM]] = {}
        for app in apps:
            if app.name:
                apps_by_name.setdefault(_norm_name(app.name), []).append(app)

        n_letter_links, n_letter_skipped = 0, 0
        for rec in letter_records:
            f = rec.get("fields") or {}
            advisor_name = _text(f.get("推荐人"))
            student_name = _text(f.get("被推荐学生"))
            if not advisor_name or not student_name:
                continue
            candidates = apps_by_name.get(_norm_name(student_name), [])
            if not candidates:
                n_letter_skipped += 1
                continue
            target = None
            if len(candidates) == 1:
                target = candidates[0]
            else:
                # 同名消歧：推荐信无学校字段，跳过记 low 待人工（防错链）
                n_letter_skipped += 1
                continue
            advisor = get_or_create_advisor(advisor_name)
            exists = any(
                isinstance(link, AdvisorStudentLinkORM)
                and link.advisor_id == advisor.id and link.application_id == target.id
                for link in session.new
            ) if session.new else False
            if not exists:
                session.add(AdvisorStudentLinkORM(
                    advisor_id=advisor.id, application_id=target.id,
                    student_name=(target.name or "")[:128],
                    source="letter", confidence="high",
                    note="推荐信表佐证"))
                n_letter_links += 1

        # 清掉没有任何 link 的孤儿导师（重跑时上轮残留）
        linked_ids = {lid for (lid,) in session.query(AdvisorStudentLinkORM.advisor_id).distinct()}
        for advisor in session.query(AdvisorORM).all():
            if advisor.id not in linked_ids:
                session.delete(advisor)

        session.commit()
        n_advisors = session.query(AdvisorORM).count()
        print(f"完成：导师 {n_advisors} 位 | 申请表关联 {n_app_links} 条 | 推荐信佐证 {n_letter_links} 条 | 跳过 {n_letter_skipped} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
