from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from agi_talent_radar.core.db.migrations import LATEST_SCHEMA_VERSION, ensure_schema
from agi_talent_radar.core.db.orm import (
    CandidateJdAssessmentORM,
    CandidateORM,
    InterviewAssessmentRunORM,
    JdEntryORM,
)
from agi_talent_radar.core.db.repository import (
    create_interview_assessment_batch,
    invalidate_assessments_for_candidate,
    invalidate_assessments_for_jd,
    list_active_jds,
    list_evaluation_directory_rows,
    replace_jd_assessment_card,
)


class InterviewAssessmentStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        ensure_schema(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def test_schema_contains_independent_current_report_tables(self) -> None:
        self.assertEqual(LATEST_SCHEMA_VERSION, 29)
        with self.Session() as session:
            session.add_all(
                [
                    CandidateORM(id="candidate-1", name="甲"),
                    CandidateORM(id="candidate-2", name="乙"),
                    JdEntryORM(
                        id="jd-1",
                        title="Agent 评测",
                        raw_text="构建 Agent benchmark",
                        assessment_card={"tasks": [{"id": "benchmark"}]},
                        card_status="ready",
                    ),
                    JdEntryORM(
                        id="jd-2",
                        title="强化学习",
                        raw_text="负责 RL 训练",
                        assessment_card={"tasks": [{"id": "rl_training"}]},
                        card_status="ready",
                    ),
                ]
            )
            session.commit()

            batch = create_interview_assessment_batch(
                session,
                ["candidate-1", "candidate-2"],
                ["jd-1", "jd-2"],
            )

            self.assertEqual(batch.total_pairs, 4)
            self.assertEqual(
                session.query(InterviewAssessmentRunORM).filter_by(batch_id=batch.id).count(),
                4,
            )

    def test_jd_selection_no_longer_depends_on_legacy_active_status(self) -> None:
        with self.Session() as session:
            session.add_all(
                [
                    JdEntryORM(
                        id="jd-ready",
                        title="可选",
                        raw_text="JD",
                        status="draft",
                        card_status="ready",
                    ),
                    JdEntryORM(
                        id="jd-not-ready",
                        title="未就绪",
                        raw_text="JD",
                        status="active",
                        card_status="generating",
                    ),
                ]
            )
            session.commit()

            self.assertEqual([row.id for row in list_active_jds(session)], ["jd-ready"])

    def test_invalidation_is_scoped_to_candidate_or_jd(self) -> None:
        with self.Session() as session:
            session.add_all(
                [
                    CandidateORM(id="candidate-1", name="甲"),
                    CandidateORM(id="candidate-2", name="乙"),
                    JdEntryORM(id="jd-1", title="岗位一", raw_text="JD", card_status="ready"),
                    JdEntryORM(id="jd-2", title="岗位二", raw_text="JD", card_status="ready"),
                ]
            )
            session.flush()
            session.add_all(
                [
                    _assessment("candidate-1", "jd-1"),
                    _assessment("candidate-1", "jd-2"),
                    _assessment("candidate-2", "jd-1"),
                ]
            )
            session.commit()

            self.assertEqual(invalidate_assessments_for_jd(session, "jd-1", "岗位卡变化"), 2)
            untouched = session.query(CandidateJdAssessmentORM).filter_by(
                candidate_id="candidate-1", jd_id="jd-2"
            ).one()
            self.assertTrue(untouched.is_valid)

            self.assertEqual(
                invalidate_assessments_for_candidate(session, "candidate-1", "简历变化"),
                1,
            )
            self.assertFalse(untouched.is_valid)

    def test_replacing_card_and_invalidation_are_one_repository_operation(self) -> None:
        with self.Session() as session:
            session.add_all(
                [
                    CandidateORM(id="candidate-1", name="甲"),
                    JdEntryORM(id="jd-1", title="岗位一", raw_text="JD", card_status="ready"),
                ]
            )
            session.flush()
            session.add(_assessment("candidate-1", "jd-1"))
            session.commit()

            jd = replace_jd_assessment_card(
                session,
                "jd-1",
                ["关注复杂工具调用"],
                {"role_summary": "新岗位卡", "core_tasks": []},
            )

            self.assertEqual(jd.supplements, ["关注复杂工具调用"])
            self.assertEqual(jd.card_status, "ready")
            assessment = session.query(CandidateJdAssessmentORM).one()
            self.assertFalse(assessment.is_valid)
            self.assertEqual(assessment.invalid_reason, "岗位评估卡已更新")

    def test_evaluation_directory_lists_pool_members_and_report_owners(self) -> None:
        """目录 = 已入库（关联 person）∪ 有准入报告者；两者皆无的不返回。"""
        with self.Session() as session:
            session.add_all(
                [
                    CandidateORM(id="in-pool", name="已入库", person_id="person-1"),
                    CandidateORM(id="report-only", name="仅报告"),
                    CandidateORM(id="nowhere", name="不在库"),
                    JdEntryORM(id="jd-1", title="Agent 评测", raw_text="构建 Agent benchmark"),
                ]
            )
            session.flush()
            session.add(_assessment("report-only", "jd-1"))
            session.commit()

            ids = [row.id for row in list_evaluation_directory_rows(session)]

        self.assertIn("in-pool", ids)
        self.assertIn("report-only", ids)
        self.assertNotIn("nowhere", ids)


def _assessment(candidate_id: str, jd_id: str) -> CandidateJdAssessmentORM:
    return CandidateJdAssessmentORM(
        candidate_id=candidate_id,
        jd_id=jd_id,
        decision="interview",
        total_score=75,
    )


if __name__ == "__main__":
    unittest.main()
