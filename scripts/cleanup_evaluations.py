# -*- coding: utf-8 -*-
"""清空评估数据，保留人物/简历/JD 等基础数据。

在服务器项目根目录运行（需 DATABASE_URL 环境变量，或用 --url 传入）：

    # 第一步：先看会删什么（不删任何数据）
    python scripts/cleanup_evaluations.py

    # 第二步：备份 + 真正执行
    python scripts/cleanup_evaluations.py --execute

备份输出到 backup_eval_<时间戳>.sql（mysqldump，若不可用则写 JSON 兜底）。
"""
import argparse
import datetime
import os
import subprocess
import sys

from sqlalchemy import create_engine, text

# 评估相关表：按依赖顺序删除；人物/简历/JD/会话/用户全部不动
TABLES = [
    "agent_collab_events",
    "interview_assessment_pair_locks",
    "interview_assessment_runs",
    "interview_assessment_batches",
    "candidate_jd_assessments",
    "evaluation_node_runs",
    "evaluations",
]
KEEP = ["persons", "candidates", "resume_submissions", "candidate_sources", "jd_entries",
        "talent_bundles", "conversations", "messages", "users"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="真正执行删除（默认只统计）")
    parser.add_argument("--url", default=os.getenv("DATABASE_URL", ""), help="覆盖 DATABASE_URL")
    args = parser.parse_args()

    url = args.url or os.getenv("DATABASE_URL", "")
    if not url:
        print("缺少 DATABASE_URL（环境变量或 --url）")
        return 2
    engine = create_engine(url)

    with engine.connect() as conn:
        print("== 现状计数 ==")
        counts = {}
        for table in TABLES + KEEP:
            try:
                counts[table] = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
                print(f"  {table:38s} {counts[table]}")
            except Exception as exc:  # noqa: BLE001
                print(f"  {table:38s} 跳过（{str(exc)[:60]}）")
        if not args.execute:
            print("\n[dry-run] 未删除任何数据；确认后加 --execute 执行")
            return 0

        print("\n== 备份 ==")
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        dump_file = f"backup_eval_{stamp}.sql"
        if url.startswith("mysql"):
            parsed = url.split("://", 1)[1]
            auth, host_db = parsed.split("@", 1)
            user, _, password = auth.partition(":")
            host, _, db = host_db.partition("/")
            db = db.split("?")[0]
            result = subprocess.run(
                ["mysqldump", f"-h{host.rsplit(':', 1)[0]}", f"-u{user}", f"-p{password}",
                 db, *TABLES],
                capture_output=True, text=True,
            )
            if result.returncode == 0:
                with open(dump_file, "w", encoding="utf-8") as f:
                    f.write(result.stdout)
                print(f"  已备份 {len(result.stdout)} 字节 → {dump_file}")
            else:
                print(f"  mysqldump 不可用（{result.stderr[:80]}），改写 JSON 兜底备份")
                dump_file = f"backup_eval_{stamp}.json"
                with open(dump_file, "w", encoding="utf-8") as f:
                    import json
                    for table in TABLES:
                        rows = conn.execute(text(f"SELECT * FROM {table}")).mappings().all()
                        f.write(json.dumps({table: [dict(r) for r in rows]},
                                           ensure_ascii=False, default=str) + "\n")
                print(f"  JSON 备份 → {dump_file}")
        else:
            dump_file = f"backup_eval_{stamp}.json"
            import json
            with open(dump_file, "w", encoding="utf-8") as f:
                for table in TABLES:
                    rows = conn.execute(text(f"SELECT * FROM {table}")).mappings().all()
                    f.write(json.dumps({table: [dict(r) for r in rows]},
                                       ensure_ascii=False, default=str) + "\n")
            print(f"  JSON 备份 → {dump_file}")

    with engine.begin() as conn:
        print("\n== 删除 ==")
        for table in TABLES:
            result = conn.execute(text(f"DELETE FROM {table}"))
            print(f"  {table:38s} 删除 {result.rowcount} 行")
        conn.execute(text("ALTER TABLE agent_collab_events AUTO_INCREMENT = 1"))

    with engine.connect() as conn:
        print("\n== 复核（评估表应为 0，保留表数量不变） ==")
        for table in TABLES:
            print(f"  {table:38s} {conn.execute(text(f'SELECT COUNT(*) FROM {table}')).scalar()}")
        for table in KEEP:
            try:
                now = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
            except Exception:  # noqa: BLE001
                print(f"  {table:38s} 跳过（表不存在）")
                continue
            mark = "OK" if now == counts.get(table) else "CHANGED!"
            print(f"  {table:38s} {now} [{mark}]")
    print("\n完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
