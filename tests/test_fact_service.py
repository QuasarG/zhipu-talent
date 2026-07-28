"""外部事实版本与审核服务测试。

覆盖（与计划 §阶段 6 验收对齐）：

1. 重复拉取完全相同事实不产生无限重复记录（deduped）。
2. 内容变化会保留旧版本并创建新版本（versioned）。
3. confirmed 事实不会被自动降级或覆盖（conflict）。
4. confirm / dismiss 强制 reviewer。
5. list_current_facts 默认排除 superseded。
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from agi_talent_radar.core.db.orm import Base, ExternalFactORM, PersonORM
from agi_talent_radar.services import fact_service


class _FactTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.Session() as session:
            session.add(PersonORM(id="p-fact", name="张三", fingerprint="fp-fact"))
            session.commit()

    def tearDown(self) -> None:
        self.engine.dispose()


class TestAppendVersionedFact(_FactTestBase):
    def test_identical_fact_is_deduped(self) -> None:
        with self.Session() as session:
            r1 = fact_service.append_versioned_fact(
                session, "p-fact", "openalex", "paper",
                payload={"title": "Paper A", "cited": 10},
                source_url="https://openalex.org/1",
            )
            r2 = fact_service.append_versioned_fact(
                session, "p-fact", "openalex", "paper",
                payload={"title": "Paper A", "cited": 10},
                source_url="https://openalex.org/1",
            )
            self.assertEqual(r1["action"], "inserted")
            self.assertEqual(r2["action"], "deduped")
            count = session.query(ExternalFactORM).filter_by(person_id="p-fact").count()
            self.assertEqual(count, 1)

    def test_changed_payload_creates_new_version(self) -> None:
        with self.Session() as session:
            r1 = fact_service.append_versioned_fact(
                session, "p-fact", "openalex", "paper",
                payload={"title": "Paper A", "cited": 10},
                source_url="https://openalex.org/1",
            )
            r2 = fact_service.append_versioned_fact(
                session, "p-fact", "openalex", "paper",
                payload={"title": "Paper A", "cited": 15},
                source_url="https://openalex.org/1",
            )
            self.assertEqual(r1["action"], "inserted")
            self.assertEqual(r2["action"], "versioned")

            all_facts = (
                session.query(ExternalFactORM)
                .filter_by(person_id="p-fact")
                .order_by(ExternalFactORM.id)
                .all()
            )
            self.assertEqual(len(all_facts), 2)
            # 旧版本被 superseded
            self.assertIsNotNone(all_facts[0].superseded_at)
            self.assertIsNone(all_facts[1].superseded_at)
            # 新版本 supersedes_id 指向旧版本
            self.assertEqual(all_facts[1].supersedes_id, all_facts[0].id)

    def test_conflict_with_confirmed_fact_preserves_both(self) -> None:
        with self.Session() as session:
            r1 = fact_service.append_versioned_fact(
                session, "p-fact", "openalex", "paper",
                payload={"title": "Paper A", "cited": 10},
                source_url="https://openalex.org/1",
            )
            # 人工确认旧版本
            fact_service.confirm_fact(
                session, r1["fact_id"], reviewer="hr", note="确认引用数 10",
            )
            # 新版本与 confirmed 内容不同
            r2 = fact_service.append_versioned_fact(
                session, "p-fact", "openalex", "paper",
                payload={"title": "Paper A", "cited": 999},
                source_url="https://openalex.org/1",
            )
            self.assertEqual(r2["action"], "conflict")

            all_facts = (
                session.query(ExternalFactORM)
                .filter_by(person_id="p-fact")
                .order_by(ExternalFactORM.id)
                .all()
            )
            self.assertEqual(len(all_facts), 2)
            # 旧版本仍 confirmed，未被自动降级
            self.assertEqual(all_facts[0].verification_status, "confirmed")
            self.assertIsNone(all_facts[0].superseded_at)
            # 新版本为 conflict
            self.assertEqual(all_facts[1].verification_status, "conflict")


class TestConfirmDismiss(_FactTestBase):
    def test_confirm_requires_reviewer(self) -> None:
        with self.Session() as session:
            r = fact_service.append_versioned_fact(
                session, "p-fact", "web_search", "search_hit",
                payload={"title": "News A"},
            )
            with self.assertRaises(ValueError):
                fact_service.confirm_fact(session, r["fact_id"], reviewer="")

    def test_confirm_upgrades_pending_to_confirmed(self) -> None:
        with self.Session() as session:
            r = fact_service.append_versioned_fact(
                session, "p-fact", "web_search", "search_hit",
                payload={"title": "News A"},
            )
            fact_service.confirm_fact(session, r["fact_id"], reviewer="hr", note="ok")
            row = session.get(ExternalFactORM, r["fact_id"])
            self.assertEqual(row.verification_status, "confirmed")
            self.assertEqual(row.query_context["confirmed_by"], "hr")

    def test_dismiss_marks_disproved(self) -> None:
        with self.Session() as session:
            r = fact_service.append_versioned_fact(
                session, "p-fact", "web_search", "search_hit",
                payload={"title": "News A"},
            )
            fact_service.dismiss_fact(session, r["fact_id"], reviewer="hr", note="误报")
            row = session.get(ExternalFactORM, r["fact_id"])
            self.assertEqual(row.verification_status, "disproved")

    def test_confirm_idempotent(self) -> None:
        with self.Session() as session:
            r = fact_service.append_versioned_fact(
                session, "p-fact", "web_search", "search_hit",
                payload={"title": "News A"},
            )
            fact_service.confirm_fact(session, r["fact_id"], reviewer="hr")
            # 二次确认不报错
            fact_service.confirm_fact(session, r["fact_id"], reviewer="hr")


class TestListCurrentFacts(_FactTestBase):
    def test_excludes_superseded_by_default(self) -> None:
        with self.Session() as session:
            fact_service.append_versioned_fact(
                session, "p-fact", "openalex", "paper",
                payload={"title": "A", "v": 1},
                source_url="u1",
            )
            fact_service.append_versioned_fact(
                session, "p-fact", "openalex", "paper",
                payload={"title": "A", "v": 2},
                source_url="u1",
            )
            current = fact_service.list_current_facts(session, "p-fact")
            self.assertEqual(len(current), 1)
            self.assertEqual(current[0].payload["v"], 2)
            # include_history=True 包含旧版本
            history = fact_service.list_current_facts(session, "p-fact", include_history=True)
            self.assertEqual(len(history), 2)


if __name__ == "__main__":
    unittest.main()