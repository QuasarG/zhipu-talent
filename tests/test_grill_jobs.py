"""grill 岗位库与 vector_store payload_keys 参数化测试（不调真实 embedding/外网）。

覆盖：
1. talent_knowledge 的默认强校验不回归（PAYLOAD_REQUIRED_KEYS）。
2. grill build_point 用 GRILL_JOB_PAYLOAD_KEYS 豁免 talent 校验。
3. InMemoryVectorStore 能 upsert/search grill 岗位点。
"""
from __future__ import annotations

import unittest

from agi_talent_radar.core.vector_store import (
    PAYLOAD_REQUIRED_KEYS,
    InMemoryVectorStore,
    VectorPoint,
)
from agi_talent_radar.grill import jobs_store


def _talent_payload(**overrides) -> dict:
    payload = {key: "" for key in PAYLOAD_REQUIRED_KEYS}
    payload.update(overrides)
    return payload


def _job_rec(**overrides) -> dict:
    rec = {"id": 100, "title": "后端开发", "requirement": "精通 Go",
           "job_category": {"name": "研发"}, "city_info": [{"name": "北京"}],
           "recruit_type": {"name": "社招"}}
    rec.update(overrides)
    return rec


class TestPayloadKeysDefault(unittest.TestCase):
    """talent_knowledge 强校验保持不变（不回归）。"""

    def test_missing_talent_key_raises(self) -> None:
        point = VectorPoint(vector=[0.1], payload={"record_id": "1"})
        with self.assertRaises(ValueError):
            point.validate_payload()

    def test_full_talent_payload_passes(self) -> None:
        point = VectorPoint(vector=[0.1], payload=_talent_payload())
        point.validate_payload()  # 不抛即通过


class TestGrillBuildPoint(unittest.TestCase):
    """grill 岗位点用 GRILL_JOB_PAYLOAD_KEYS，豁免 talent 必需字段。"""

    def test_grill_point_validates_with_grill_keys(self) -> None:
        point = jobs_store.build_point(_job_rec(), [0.1, 0.2, 0.3])
        # 不应抛错：grill payload 不含 talent 的 person_id 等字段，但用 grill 契约校验通过
        point.validate_payload()

    def test_grill_point_payload_fields(self) -> None:
        point = jobs_store.build_point(_job_rec(id=42), [0.1])
        self.assertEqual(point.payload["job_id"], "42")
        self.assertEqual(point.payload["title"], "后端开发")
        self.assertEqual(point.payload["job_category"], "研发")
        self.assertEqual(point.payload["city_info"], "北京")
        self.assertEqual(point.point_id, 42)

    def test_grill_point_does_not_satisfy_talent_keys(self) -> None:
        # grill 点若误用 talent 契约校验应失败（证明两套契约独立）
        point = jobs_store.build_point(_job_rec(), [0.1])
        talent_point = VectorPoint(
            vector=point.vector, payload=point.payload,
            required_keys=PAYLOAD_REQUIRED_KEYS,
        )
        with self.assertRaises(ValueError):
            talent_point.validate_payload()

    def test_non_numeric_job_id_falls_back_to_uuid(self) -> None:
        point = jobs_store.build_point(_job_rec(id="abc-x"), [0.1])
        # 非数字 id → 确定性 UUID 字符串（Qdrant 接受 UUID）
        self.assertIsInstance(point.point_id, str)
        self.assertEqual(point.payload["job_id"], "abc-x")


class TestInMemoryGrillSearch(unittest.TestCase):
    """InMemoryVectorStore upsert/search grill 岗位点。"""

    def test_upsert_and_search(self) -> None:
        store = InMemoryVectorStore()
        store.ensure_collection(3)
        p1 = jobs_store.build_point(_job_rec(id=1, title="后端"), [1.0, 0.0, 0.0])
        p2 = jobs_store.build_point(_job_rec(id=2, title="算法"), [0.0, 1.0, 0.0])
        store.upsert([p1, p2])
        self.assertEqual(store.count(), 2)
        hits = store.search([0.95, 0.05, 0.0], top_k=1)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].payload["title"], "后端")


if __name__ == "__main__":
    unittest.main()
