"""运维命令入口（阶段 11）。

按 AGENTS.md 要求：简单脚本不用 argparse，直接用变量。

用法：
    python scripts/ops_commands.py <command>
    python scripts/ops_commands.py retry_tasks [task_type]
    python scripts/ops_commands.py rebuild_vectors
    python scripts/ops_commands.py check_config
    python scripts/ops_commands.py migrate_db

支持命令：
- retry_tasks      重置失败 task 为 queued
- rebuild_vectors  Qdrant 全量重建（从 MySQL 重新切片 + embedding）
- check_config     配置连通性检查（health report）
- migrate_db       触发数据库 schema 迁移
"""
from __future__ import annotations

import json
import sys


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1

    command = sys.argv[1]
    task_type = sys.argv[2] if len(sys.argv) > 2 else ""

    if command == "retry_tasks":
        return _retry_tasks(task_type)
    if command == "rebuild_vectors":
        return _rebuild_vectors()
    if command == "check_config":
        return _check_config()
    if command == "migrate_db":
        return _migrate_db()

    print(f"未知命令：{command}")
    print(__doc__)
    return 1


def _retry_tasks(task_type: str) -> int:
    from agi_talent_radar.core.database import get_session
    from agi_talent_radar.core.ops import retry_failed_tasks

    with get_session() as session:
        result = retry_failed_tasks(session, task_type=task_type)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _rebuild_vectors() -> int:
    from agi_talent_radar.core.database import get_session
    from agi_talent_radar.core.embedding import ZhipuEmbeddingClient
    from agi_talent_radar.core.ops import rebuild_vector_index
    from agi_talent_radar.core.vector_store import QdrantVectorStore

    with get_session() as session:
        result = rebuild_vector_index(
            session,
            QdrantVectorStore(),
            embedding_client=ZhipuEmbeddingClient(),
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _check_config() -> int:
    from agi_talent_radar.core.ops import check_config_connectivity

    result = check_config_connectivity()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _migrate_db() -> int:
    from agi_talent_radar.core.database import get_engine
    from agi_talent_radar.core.ops import run_database_migration

    result = run_database_migration(get_engine())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())