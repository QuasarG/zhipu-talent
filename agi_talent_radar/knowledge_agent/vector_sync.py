"""向量同步与全量重建（阶段 7）。

策略（与决策记录 §2.4 对齐）：

- **MySQL-first + outbox**：业务事务先提交 MySQL，再异步 embedding/upsert Qdrant；
  同步失败写可重试 task，不回滚已成功的业务写入。
- **全量重建**：Qdrant 索引丢失或模型版本变化时，从 MySQL 重新切片并调用
  embedding-3，不依赖旧 Qdrant 数据。
- Qdrant 只保存可重建的派生数据；MySQL 是唯一业务数据真源。
"""
from __future__ import annotations

from typing import Any

from agi_talent_radar.core.db import repository
from agi_talent_radar.core.db.orm import TaskORM
from agi_talent_radar.core.embedding import (
    EMBEDDING_DIM,
    embed_texts,
)
from agi_talent_radar.core.vector_store import (
    CURRENT_INDEX_VERSION,
    VectorPoint,
    VectorStore,
)
from agi_talent_radar.knowledge_agent.chunker import (
    chunk_to_payload,
    collect_chunks_for_person,
)


def enqueue_vector_sync_task(
    session,
    person_id: str,
    action: str = "upsert",
) -> TaskORM:
    """业务事务提交后派发向量同步任务。

    ``action``: ``upsert``（重新切片并写入）或 ``delete``（按 person 删除）。
    """
    if action not in {"upsert", "delete"}:
        raise ValueError("action 必须是 upsert 或 delete。")
    return repository.create_task(
        session,
        task_type="vector_sync",
        payload={"person_id": person_id, "action": action},
    )


def sync_person_vectors(
    session,
    person_id: str,
    vector_store: VectorStore,
    embedding_client=None,
) -> dict[str, Any]:
    """重新切片 + embedding + upsert 某 person 的全部 chunk。

    返回 ``{upserted, skipped}``。同步失败会重新抛出，由调用方写可重试 task。
    """
    chunks = collect_chunks_for_person(session, person_id)
    if not chunks:
        # 该 person 无可索引内容，仍按 delete 清理旧向量
        vector_store.delete_by_record("person", person_id)
        return {"upserted": 0, "skipped": 0}

    texts = [chunk.text for chunk in chunks]
    vectors = embed_texts(texts, client=embedding_client)
    if len(vectors) != len(chunks):
        raise RuntimeError(
            f"Embedding 数量与 chunk 数量不一致：{len(vectors)} vs {len(chunks)}"
        )

    points = [
        VectorPoint(
            vector=vector,
            payload=chunk_to_payload(chunk, CURRENT_INDEX_VERSION),
        )
        for chunk, vector in zip(chunks, vectors)
    ]
    upserted = vector_store.upsert(points)
    return {"upserted": upserted, "skipped": 0}


def delete_person_vectors(
    person_id: str,
    vector_store: VectorStore,
) -> int:
    """删除某 person 在向量库中的全部点（按 person_id payload 过滤）。"""
    return vector_store.delete_by_filter({"person_id": person_id})


def rebuild_all_vectors(
    session,
    vector_store: VectorStore,
    embedding_client=None,
    batch_size: int = 50,
) -> dict[str, int]:
    """全量重建：遍历所有 person，重新切片 + embedding + upsert。

    适用于 Qdrant 索引丢失或模型版本变化场景。
    """
    from agi_talent_radar.core.db.orm import PersonORM

    vector_store.ensure_collection(EMBEDDING_DIM)
    persons = session.query(PersonORM).all()
    upserted_total = 0
    failed: list[str] = []
    for person in persons:
        try:
            result = sync_person_vectors(
                session,
                person.id,
                vector_store,
                embedding_client=embedding_client,
            )
            upserted_total += int(result.get("upserted", 0))
        except Exception:  # noqa: BLE001
            failed.append(person.id)

    return {
        "persons_total": len(persons),
        "upserted_total": upserted_total,
        "failed_count": len(failed),
        "failed_person_ids": failed,
    }


__all__ = [
    "enqueue_vector_sync_task",
    "sync_person_vectors",
    "delete_person_vectors",
    "rebuild_all_vectors",
]
