"""运维命令（阶段 11）：失败 task 重试 / Qdrant 重建 / 配置连通性检查。

约束（与计划 §阶段 11 对齐）：

- 数据库迁移、Qdrant 全量重建、失败任务重试、配置连通性检查；
- 不记录敏感 Key；
- 为 Agent、外部调用、事实落库、向量同步记录 task_id 等元数据。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from agi_talent_radar.core.db.orm import TaskORM


TASK_TYPE_HANDLERS = {
    "publication_verification": "publication_verification",
    "vector_sync": "vector_sync",
}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def list_failed_tasks(session, task_type: str = "") -> list[TaskORM]:
    """列出失败 / 排队中的 task。"""
    query = session.query(TaskORM).filter(
        TaskORM.status.in_(["failed", "queued", "running"])
    )
    if task_type:
        query = query.filter_by(task_type=task_type)
    return query.order_by(TaskORM.created_at.desc()).all()


def retry_failed_tasks(
    session,
    task_type: str = "",
    limit: int = 50,
) -> dict[str, Any]:
    """重置失败 task 为 queued，等待 worker 处理。

    返回 ``{reset_count, skipped_count, task_ids}``。
    本函数只重置状态；实际执行由后台 worker（阶段 11 部署）完成。
    """
    failed = list_failed_tasks(session, task_type=task_type)
    if limit > 0:
        failed = failed[:limit]

    reset_ids: list[str] = []
    skipped = 0
    for task in failed:
        if task.status == "failed":
            task.status = "queued"
            task.error_message = ""
            reset_ids.append(task.id)
        else:
            skipped += 1
    if reset_ids:
        session.commit()

    return {
        "reset_count": len(reset_ids),
        "skipped_count": skipped,
        "task_ids": reset_ids,
    }


def rebuild_vector_index(
    session,
    vector_store,
    embedding_client=None,
) -> dict[str, Any]:
    """Qdrant 全量重建：从 MySQL 重新切片 + embedding + upsert。"""
    from agi_talent_radar.knowledge_agent.vector_sync import rebuild_all_vectors

    return rebuild_all_vectors(
        session,
        vector_store,
        embedding_client=embedding_client,
    )


def check_config_connectivity() -> dict[str, Any]:
    """配置连通性检查：调用 health 模块。"""
    from agi_talent_radar.core.health import run_health_check

    report = run_health_check()
    return report.to_dict()


def run_database_migration(engine) -> dict[str, Any]:
    """触发数据库 schema 迁移（ensure_schema）。

    返回当前 schema_version。
    """
    from agi_talent_radar.core.db.migrations import LATEST_SCHEMA_VERSION, ensure_schema

    ensure_schema(engine)
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT version FROM schema_versions ORDER BY version DESC LIMIT 1"
            )
        ).fetchone()
    current = int(row[0]) if row else 0
    return {
        "current_version": current,
        "latest_version": LATEST_SCHEMA_VERSION,
        "up_to_date": current >= LATEST_SCHEMA_VERSION,
    }


__all__ = [
    "list_failed_tasks",
    "retry_failed_tasks",
    "rebuild_vector_index",
    "check_config_connectivity",
    "run_database_migration",
]