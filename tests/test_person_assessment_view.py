from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from agi_talent_radar.core.db.orm import (
    Base,
    CandidateJdAssessmentORM,
    CandidateORM,
    EvaluationORM,
    JdEntryORM,
    PersonORM,
    ResumeSubmissionORM,
)
from agi_talent_radar.services.person_assessment_view import get_person_assessment_view


class PersonAssessmentViewTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)

    def tearDown(self) -> None:
        self.engine.dispose()

    def test_missing_person_returns_none(self) -> None:
        with self.Session() as session:
            self.assertIsNone(get_person_assessment_view(session, "missing"))

    def test_unifies_resume_general_evaluation_and_jd_admissions(self) -> None:
        with self.Session() as session:
            person = PersonORM(
                id="p1",
                name="洪宇曦",
                fingerprint="fp-p1",
                person_type="student",
            )
            candidate = CandidateORM(id="c1", person_id="p1", name="洪宇曦")
            session.add_all(
                [
                    person,
                    candidate,
                    ResumeSubmissionORM(
                        id="s1",
                        candidate_id="c1",
                        person_id="p1",
                        source_format="pdf",
                        filename="resume.pdf",
                        parse_status="completed",
                        structured={"skills": ["PyTorch"]},
                    ),
                    EvaluationORM(
                        candidate_id="c1",
                        person_id="p1",
                        status="completed",
                        overall_score=72,
                        level="A",
                        tier="recommended",
                    ),
                    JdEntryORM(
                        id="jd1",
                        title="多模态生成算法研究",
                        raw_text="研究多模态生成模型",
                        card_status="ready",
                    ),
                    CandidateJdAssessmentORM(
                        id="a1",
                        candidate_id="c1",
                        jd_id="jd1",
                        status="completed",
                        is_valid=True,
                        decision="interview",
                        total_score=65.6,
                        task_assessments=[{"task_id": "t1", "level": 3}],
                    ),
                ]
            )
            session.commit()

            view = get_person_assessment_view(session, "p1")

        self.assertIsNotNone(view)
        assert view is not None
        self.assertEqual(view["schema_version"], "person-assessment-view.v1")
        self.assertEqual(view["person_id"], "p1")
        self.assertEqual(view["candidate_id"], "c1")
        self.assertTrue(view["resume"]["has_resume"])
        self.assertEqual(view["resume"]["submission_id"], "s1")
        self.assertEqual(view["general_evaluation"]["overall_score"], 72)
        self.assertEqual(view["general_evaluation"]["level"], "A")
        self.assertEqual(len(view["admissions"]), 1)
        admission = view["admissions"][0]
        self.assertEqual(admission["jd_title"], "多模态生成算法研究")
        self.assertEqual(admission["decision"], "interview")
        self.assertEqual(admission["total_score"], 65.6)
        self.assertEqual(view["latest"]["source_type"], "interview_admission")
        self.assertEqual(view["latest"]["source_id"], "a1")

    def test_ignores_invalid_or_incomplete_admissions(self) -> None:
        with self.Session() as session:
            session.add_all(
                [
                    PersonORM(id="p2", name="候选人", fingerprint="fp-p2"),
                    CandidateORM(id="c2", person_id="p2", name="候选人"),
                    JdEntryORM(id="jd2", title="岗位一", raw_text="岗位描述", card_status="ready"),
                    JdEntryORM(id="jd3", title="岗位二", raw_text="岗位描述", card_status="ready"),
                    CandidateJdAssessmentORM(
                        id="invalid",
                        candidate_id="c2",
                        jd_id="jd3",
                        status="completed",
                        is_valid=False,
                        decision="interview",
                        total_score=99,
                    ),
                    CandidateJdAssessmentORM(
                        id="running",
                        candidate_id="c2",
                        jd_id="jd2",
                        status="running",
                        is_valid=True,
                        decision="no_interview",
                        total_score=10,
                    ),
                ]
            )
            session.commit()

            view = get_person_assessment_view(session, "p2")

        self.assertIsNotNone(view)
        assert view is not None
        self.assertEqual(view["admissions"], [])
        self.assertIsNone(view["latest"])


if __name__ == "__main__":
    unittest.main()
