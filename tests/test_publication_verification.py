"""Publication claim 与外部核验持久化测试。

覆盖（与计划 §阶段 3 对齐）：

1. save_publication_claims 清空旧记录后按顺序重写。
2. save_publication_verification 同 claim_id 至多一条；
   重试时覆盖核验字段，保留人工确认字段。
3. claim 与 verification 一对一关系正确建立。
4. retry_publication_verification 派发 Task，task_type=publication_verification。
5. retry_publication_verification 拒绝未知 evaluation_id。
"""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from agi_talent_radar.core.db import repository
from agi_talent_radar.core.db.orm import (
    Base,
    EvaluationORM,
    PersonORM,
    PublicationClaimORM,
    PublicationVerificationORM,
    TaskORM,
)
from agi_talent_radar.services import talent_service


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class _PublicationTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self._patch = patch(
            "agi_talent_radar.core.database.get_session", self._session_cm
        )
        self._patch.start()
        # 准备 person + evaluation
        with self.Session() as session:
            session.add(PersonORM(id="p-pub", name="张三", fingerprint="fp-pub"))
            session.add(
                EvaluationORM(
                    id=1,
                    candidate_id="c-pub",
                    person_id="p-pub",
                    status="completed",
                    evaluation_mode="multi_track_v1",
                )
            )
            session.commit()

    def tearDown(self) -> None:
        self._patch.stop()
        self.engine.dispose()

    def _session_cm(self):
        return self.Session()


class TestSavePublicationClaims(_PublicationTestBase):
    def test_claims_are_rewritten_in_order(self) -> None:
        with self.Session() as session:
            rows = repository.save_publication_claims(
                session,
                evaluation_id=1,
                claims=[
                    {"title": "Paper A", "claimed_status": "published", "venue": "NeurIPS"},
                    {"title": "Paper B", "claimed_status": "in_review"},
                ],
            )
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0].title, "Paper A")
            self.assertEqual(rows[0].order_index, 0)
            self.assertEqual(rows[1].title, "Paper B")
            self.assertEqual(rows[1].order_index, 1)

            # 第二次调用清空旧的，重写
            rows2 = repository.save_publication_claims(
                session,
                evaluation_id=1,
                claims=[{"title": "Paper C", "claimed_status": "draft"}],
            )
            self.assertEqual(len(rows2), 1)
            self.assertEqual(rows2[0].title, "Paper C")
            total = (
                session.query(PublicationClaimORM).filter_by(evaluation_id=1).count()
            )
            self.assertEqual(total, 1, msg="旧 claims 必须被清空")


class TestSavePublicationVerification(_PublicationTestBase):
    def setUp(self) -> None:
        super().setUp()
        with self.Session() as session:
            self.claims = repository.save_publication_claims(
                session,
                evaluation_id=1,
                claims=[{"title": "Paper A", "claimed_status": "published"}],
            )

    def test_single_verification_per_claim(self) -> None:
        with self.Session() as session:
            claim_id = self.claims[0].id
            first = repository.save_publication_verification(
                session,
                claim_id=claim_id,
                source="openalex",
                matched_title="Paper A (verified)",
                verified_status="verified",
                author_position_match="match",
                identity_confidence=0.9,
            )
            second = repository.save_publication_verification(
                session,
                claim_id=claim_id,
                source="openalex",
                matched_title="Paper A (retry)",
                verified_status="verified",
                failure_reason="",
            )
            count = (
                session.query(PublicationVerificationORM)
                .filter_by(claim_id=claim_id)
                .count()
            )
            self.assertEqual(count, 1, msg="同 claim 至多一条 verification")
            self.assertEqual(second.matched_title, "Paper A (retry)")
            self.assertEqual(first.id, second.id)

    def test_retry_preserves_human_status(self) -> None:
        with self.Session() as session:
            claim_id = self.claims[0].id
            repository.save_publication_verification(
                session,
                claim_id=claim_id,
                source="openalex",
                matched_title="Paper A",
                verified_status="conflict",
                conflicts=["作者顺序不一致"],
            )
            # 人工确认
            row = (
                session.query(PublicationVerificationORM)
                .filter_by(claim_id=claim_id)
                .first()
            )
            row.human_status = "confirmed"
            row.human_reviewer = "hr"
            session.commit()

            # 重试覆盖核验字段
            repository.save_publication_verification(
                session,
                claim_id=claim_id,
                source="openalex",
                matched_title="Paper A (retry)",
                verified_status="verified",
            )
            row = (
                session.query(PublicationVerificationORM)
                .filter_by(claim_id=claim_id)
                .first()
            )
            self.assertEqual(row.matched_title, "Paper A (retry)")
            self.assertEqual(row.verified_status, "verified")
            # 人工确认字段保留
            self.assertEqual(row.human_status, "confirmed")
            self.assertEqual(row.human_reviewer, "hr")

    def test_claim_verification_relationship(self) -> None:
        with self.Session() as session:
            claim_id = self.claims[0].id
            repository.save_publication_verification(
                session,
                claim_id=claim_id,
                source="openalex",
                verified_status="pending",
            )
            claim = session.get(PublicationClaimORM, claim_id)
            self.assertIsNotNone(claim.verification)
            self.assertEqual(claim.verification.source, "openalex")


class TestRetryPublicationVerification(_PublicationTestBase):
    def test_creates_task(self) -> None:
        result = talent_service.retry_publication_verification(1)
        self.assertEqual(result["task_type"], "publication_verification")
        self.assertEqual(result["status"], "queued")
        self.assertEqual(result["payload"]["evaluation_id"], 1)
        self.assertIsNone(result["payload"]["claim_ids"])

        with self.Session() as session:
            task = session.get(TaskORM, result["task_id"])
            self.assertIsNotNone(task)
            self.assertEqual(task.task_type, "publication_verification")

    def test_passes_claim_ids(self) -> None:
        result = talent_service.retry_publication_verification(
            1, paper_claim_ids=["42", "43"]
        )
        self.assertEqual(result["payload"]["claim_ids"], [42, 43])

    def test_unknown_evaluation_raises(self) -> None:
        with self.assertRaises(ValueError):
            talent_service.retry_publication_verification(99999)


if __name__ == "__main__":
    unittest.main()