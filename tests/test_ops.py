"""运维命令测试。

覆盖（与计划 §阶段 11 对齐）：

1. list_failed_tasks 按 task_type 过滤。
2. retry_failed_tasks 把 failed 重置为 queued，跳过非 failed。
3. rebuild_vector_index 委托给 vector_sync.rebuild_all_vectors。
4. run_database_migration 返回 schema_version。
"""
from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from agi_talent_radar.core.db import repository
from agi_talent_radar.core.db.migrations import ensure_schema
from agi_talent_radar.core.db.orm import Base, TaskORM
from agi_talent_radar.core.embedding import FakeEmbeddingClient
from agi_talent_radar.core.ops import (
    list_failed_tasks,
    retry_failed_tasks,
    run_database_migration,
)
from agi_talent_radar.core.vector_store import InMemoryVectorStore


class TestRetryFailedTasks(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)

    def tearDown(self) -> None:
        self.engine.dispose()

    def _seed_tasks(self) -> None:
        with self.Session() as session:
            repository.create_task(
                session, "publication_verification", payload={"evaluation_id": 1}
            )
            t2 = repository.create_task(
                session, "vector_sync", payload={"person_id": "p1"}
            )
            t2.status = "failed"
            t2.error_message = "timeout"
            session.commit()
            t3 = repository.create_task(
                session, "publication_verification", payload={}
            )
            t3.status = "failed"
            session.commit()

    def test_list_filters_by_type(self) -> None:
        self._seed_tasks()
        with self.Session() as session:
            pub_tasks = list_failed_tasks(session, task_type="publication_verification")
            all_tasks = list_failed_tasks(session)
        # 2 个 publication_verification（1 queued + 1 failed）
        self.assertEqual(len(pub_tasks), 2)
        self.assertEqual(len(all_tasks), 3)

    def test_retry_resets_failed_to_queued(self) -> None:
        self._seed_tasks()
        with self.Session() as session:
            result = retry_failed_tasks(session, task_type="vector_sync")
        self.assertEqual(result["reset_count"], 1)
        self.assertEqual(result["skipped_count"], 0)
        with self.Session() as session:
            failed = list_failed_tasks(session, task_type="vector_sync")
            self.assertEqual(len(failed), 1)
            self.assertEqual(failed[0].status, "queued")

    def test_retry_skips_non_failed(self) -> None:
        self._seed_tasks()
        with self.Session() as session:
            result = retry_failed_tasks(session)
        # 2 failed + 1 queued；reset=2，skipped=1
        self.assertEqual(result["reset_count"], 2)
        self.assertEqual(result["skipped_count"], 1)

    def test_retry_empty_returns_zero(self) -> None:
        with self.Session() as session:
            result = retry_failed_tasks(session)
        self.assertEqual(result["reset_count"], 0)


class TestRunDatabaseMigration(unittest.TestCase):
    def test_returns_current_version(self) -> None:
        engine = create_engine("sqlite+pysqlite:///:memory:")
        try:
            result = run_database_migration(engine)
            self.assertIn("current_version", result)
            self.assertIn("latest_version", result)
            self.assertTrue(result["up_to_date"])
        finally:
            engine.dispose()


class TestRebuildVectorIndex(unittest.TestCase):
    def test_delegates_to_rebuild(self) -> None:
        from agi_talent_radar.core.db.orm import PersonORM
        from agi_talent_radar.core.ops import rebuild_vector_index

        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine, expire_on_commit=False)
        try:
            with Session() as session:
                session.add(PersonORM(id="p-1", name="张三", fingerprint="fp-1"))
                session.commit()
                store = InMemoryVectorStore()
                result = rebuild_vector_index(
                    session, store, embedding_client=FakeEmbeddingClient()
                )
            self.assertEqual(result["persons_total"], 1)
            self.assertEqual(result["failed_count"], 0)
        finally:
            engine.dispose()


if __name__ == "__main__":
    unittest.main()