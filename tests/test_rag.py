"""RAG chunker + vector_sync 测试。

覆盖（与计划 §阶段 7 验收对齐）：

1. chunker 从 evaluation / evidence / external_fact 生成可回链 chunk。
2. chunk_to_payload 包含全部 Qdrant 必需字段。
3. sync_person_vectors 切片 + embedding + upsert 行为正确。
4. 空 person（无 chunk）走 delete 清理。
5. rebuild_all_vectors 遍历全部 person，失败不阻塞其他。
"""
from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from agi_talent_radar.core.db.orm import (
    Base,
    EvaluationEvidenceORM,
    EvaluationORM,
    ExternalFactORM,
    PersonORM,
)
from agi_talent_radar.core.embedding import EMBEDDING_DIM, FakeEmbeddingClient
from agi_talent_radar.core.vector_store import (
    InMemoryVectorStore,
    PAYLOAD_REQUIRED_KEYS,
)
from agi_talent_radar.knowledge_agent.chunker import (
    chunk_to_payload,
    collect_chunks_for_person,
)
from agi_talent_radar.knowledge_agent.vector_sync import (
    rebuild_all_vectors,
    sync_person_vectors,
)


def _seed(session, person_id: str, name: str = "张三") -> None:
    session.add(PersonORM(id=person_id, name=name, fingerprint=f"fp-{person_id}"))
    ev = EvaluationORM(
        id=hash(person_id) & 0xFFFF,
        candidate_id=f"c-{person_id}",
        person_id=person_id,
        status="completed",
        overall_score=80,
        one_liner="高潜候选人",
        core_strengths=["工程闭环"],
        recommended_tracks=[{"track": "agent"}],
    )
    session.add(ev)
    session.flush()
    session.add(
        EvaluationEvidenceORM(
            evaluation_id=ev.id,
            evidence_key="e1",
            dimension="research_rigor",
            source="项目 A",
            quote="构建评测框架",
        )
    )
    session.add(
        ExternalFactORM(
            person_id=person_id,
            source="web_search",
            fact_type="search_hit",
            payload={"title": "新闻 A"},
        )
    )


class _VectorTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.store = InMemoryVectorStore()
        self.store.ensure_collection(EMBEDDING_DIM)
        self.embedder = FakeEmbeddingClient()

    def tearDown(self) -> None:
        self.engine.dispose()


class TestChunker(_VectorTestBase):
    def test_collect_chunks_covers_three_types(self) -> None:
        with self.Session() as session:
            _seed(session, "p-1")
            session.commit()
            chunks = collect_chunks_for_person(session, "p-1")
        types = {chunk.record_type for chunk in chunks}
        self.assertIn("evaluation", types)
        self.assertIn("evidence", types)
        self.assertIn("external_fact", types)

    def test_chunk_to_payload_has_required_keys(self) -> None:
        with self.Session() as session:
            _seed(session, "p-2")
            session.commit()
            chunks = collect_chunks_for_person(session, "p-2")
        for chunk in chunks:
            payload = chunk_to_payload(chunk, "v1")
            for key in PAYLOAD_REQUIRED_KEYS:
                self.assertIn(key, payload, msg=f"chunk {chunk.record_type} 缺 {key}")

    def test_unknown_person_returns_empty(self) -> None:
        with self.Session() as session:
            chunks = collect_chunks_for_person(session, "nonexistent")
        self.assertEqual(chunks, [])


class TestSyncPersonVectors(_VectorTestBase):
    def test_sync_upserts_all_chunks(self) -> None:
        with self.Session() as session:
            _seed(session, "p-sync")
            session.commit()
            result = sync_person_vectors(
                session,
                "p-sync",
                self.store,
                embedding_client=self.embedder,
            )
        self.assertGreater(result["upserted"], 0)
        self.assertEqual(self.store.count(), result["upserted"])
        # 每个 point 的 payload 都带 person_id
        hits = self.store.search(
            [0.5] * EMBEDDING_DIM, top_k=100
        )
        self.assertTrue(all(h.payload["person_id"] == "p-sync" for h in hits))

    def test_sync_empty_person_deletes_old_vectors(self) -> None:
        # 先写一条向量
        with self.Session() as session:
            _seed(session, "p-empty")
            session.commit()
            sync_person_vectors(session, "p-empty", self.store, embedding_client=self.embedder)
            self.assertGreater(self.store.count(), 0)
        # 删掉 person 的全部数据
        with self.Session() as session:
            from agi_talent_radar.core.db.orm import EvaluationORM, ExternalFactORM
            session.query(EvaluationORM).filter_by(person_id="p-empty").delete()
            session.query(ExternalFactORM).filter_by(person_id="p-empty").delete()
            session.commit()
            result = sync_person_vectors(session, "p-empty", self.store, embedding_client=self.embedder)
        self.assertEqual(result["upserted"], 0)


class TestRebuildAllVectors(_VectorTestBase):
    def test_rebuild_processes_all_persons(self) -> None:
        with self.Session() as session:
            _seed(session, "p-a", "张三")
            _seed(session, "p-b", "李四")
            session.commit()
            result = rebuild_all_vectors(
                session,
                self.store,
                embedding_client=self.embedder,
            )
        self.assertEqual(result["persons_total"], 2)
        self.assertGreater(result["upserted_total"], 0)
        self.assertEqual(result["failed_count"], 0)


if __name__ == "__main__":
    unittest.main()