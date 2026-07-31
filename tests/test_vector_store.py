"""Qdrant 向量存储适配器测试（用 InMemoryVectorStore）。

覆盖（与计划 §阶段 7 验收对齐）：

1. payload 缺少必需字段时抛 ValueError。
2. upsert / search / delete / count 行为正确。
3. search 支持 filters 过滤（如 fact_status / person_id）。
4. collection 名称带 index_version 后缀。
5. QdrantVectorStore 未配置 URL 时抛 RuntimeError。
"""
from __future__ import annotations

import unittest

from agi_talent_radar.core.vector_store import (
    CURRENT_INDEX_VERSION,
    PAYLOAD_REQUIRED_KEYS,
    InMemoryVectorStore,
    QdrantVectorStore,
    VectorPoint,
)


def _full_payload(**overrides) -> dict:
    payload = {key: "" for key in PAYLOAD_REQUIRED_KEYS}
    payload.update(overrides)
    return payload


class TestVectorPoint(unittest.TestCase):
    def test_validate_rejects_missing_keys(self) -> None:
        point = VectorPoint(vector=[0.1, 0.2], payload={"record_id": "1"})
        with self.assertRaises(ValueError) as ctx:
            point.validate_payload()
        self.assertIn("record_type", str(ctx.exception))

    def test_validate_accepts_full_payload(self) -> None:
        point = VectorPoint(
            vector=[0.1, 0.2],
            payload=_full_payload(record_id="1"),
        )
        point.validate_payload()  # 不抛


class TestInMemoryVectorStore(unittest.TestCase):
    def setUp(self) -> None:
        self.store = InMemoryVectorStore()
        self.store.ensure_collection(dim=3)

    def test_upsert_and_count(self) -> None:
        points = [
            VectorPoint(vector=[1.0, 0.0, 0.0], payload=_full_payload(record_id="1")),
            VectorPoint(vector=[0.0, 1.0, 0.0], payload=_full_payload(record_id="2")),
        ]
        inserted = self.store.upsert(points)
        self.assertEqual(inserted, 2)
        self.assertEqual(self.store.count(), 2)

    def test_search_returns_top_k_by_cosine(self) -> None:
        self.store.upsert([
            VectorPoint(vector=[1.0, 0.0, 0.0], payload=_full_payload(record_id="1")),
            VectorPoint(vector=[0.0, 1.0, 0.0], payload=_full_payload(record_id="2")),
            VectorPoint(vector=[0.9, 0.1, 0.0], payload=_full_payload(record_id="3")),
        ])
        hits = self.store.search([1.0, 0.0, 0.0], top_k=2)
        self.assertEqual(len(hits), 2)
        # 最相似的是 record_id=1（完全一致）
        self.assertEqual(hits[0].payload["record_id"], "1")
        self.assertGreater(hits[0].score, hits[1].score)

    def test_search_with_filters(self) -> None:
        self.store.upsert([
            VectorPoint(
                vector=[1.0, 0.0, 0.0],
                payload=_full_payload(record_id="1", person_id="p-a", fact_status="confirmed"),
            ),
            VectorPoint(
                vector=[0.9, 0.1, 0.0],
                payload=_full_payload(record_id="2", person_id="p-b", fact_status="pending"),
            ),
        ])
        # 只看 confirmed
        hits = self.store.search([1.0, 0.0, 0.0], filters={"fact_status": "confirmed"})
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].payload["record_id"], "1")
        # 只看 person p-b
        hits = self.store.search([1.0, 0.0, 0.0], filters={"person_id": "p-b"})
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].payload["record_id"], "2")

    def test_delete_by_record(self) -> None:
        self.store.upsert([
            VectorPoint(vector=[1.0, 0.0, 0.0], payload=_full_payload(record_id="1", record_type="evaluation")),
            VectorPoint(vector=[0.0, 1.0, 0.0], payload=_full_payload(record_id="2", record_type="paper")),
        ])
        deleted = self.store.delete_by_record("evaluation", "1")
        self.assertEqual(deleted, 1)
        self.assertEqual(self.store.count(), 1)

    def test_delete_by_person_filter_removes_all_record_types(self) -> None:
        from agi_talent_radar.knowledge_agent.vector_sync import delete_person_vectors

        self.store.upsert([
            VectorPoint(vector=[1.0, 0.0, 0.0], payload=_full_payload(record_type="evaluation", record_id="1", person_id="p-delete")),
            VectorPoint(vector=[0.0, 1.0, 0.0], payload=_full_payload(record_type="external_fact", record_id="2", person_id="p-delete")),
            VectorPoint(vector=[0.5, 0.5, 0.0], payload=_full_payload(record_type="evaluation", record_id="3", person_id="p-keep")),
        ])

        deleted = delete_person_vectors("p-delete", self.store)

        self.assertEqual(deleted, 2)
        self.assertEqual(self.store.count(), 1)

    def test_upsert_replaces_same_point_id(self) -> None:
        p1 = VectorPoint(
            vector=[1.0, 0.0, 0.0],
            payload=_full_payload(record_id="1", fact_status="pending"),
            point_id="fixed-id",
        )
        p2 = VectorPoint(
            vector=[0.0, 1.0, 0.0],
            payload=_full_payload(record_id="1", fact_status="confirmed"),
            point_id="fixed-id",
        )
        self.store.upsert([p1])
        self.store.upsert([p2])
        self.assertEqual(self.store.count(), 1)
        hits = self.store.search([0.0, 1.0, 0.0])
        self.assertEqual(hits[0].payload["fact_status"], "confirmed")


class TestQdrantCollectionVersion(unittest.TestCase):
    def test_collection_name_has_version_suffix(self) -> None:
        store = QdrantVectorStore(collection="talent_knowledge")
        self.assertIn(CURRENT_INDEX_VERSION, store.collection)


class TestQdrantMissingConfig(unittest.TestCase):
    def test_missing_url_raises(self) -> None:
        import os
        from unittest.mock import patch

        with patch.dict(os.environ, {"QDRANT_URL": ""}, clear=False):
            store = QdrantVectorStore()
            with self.assertRaises(RuntimeError) as ctx:
                store.count()
            self.assertIn("QDRANT_URL", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
