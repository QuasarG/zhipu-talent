"""talent_service 实装后的行为契约测试。

覆盖（与计划 §阶段 1 验收 + 阶段 4 边界）：

1. admit_candidate_after_evaluation 双源去重：
   - 同一 person 二次 admit 仅创建一份 Candidate；
   - 但 ``person_investigation`` 与 ``resume_evaluation`` 可并存。

2. admit_candidate_after_evaluation 拒绝非 completed 评估 / 缺 person_id：
   - ``status != 'completed'`` raise ``ValueError``。
   - ``person_id`` 为空 raise ``ValueError``。

3. manual_admit_person_to_pool 强制 changed_by：
   - 空字符串 / 纯空白 raise ``ValueError``。

4. update_engagement_status 强制 changed_by + 不可变审计：
   - 空字符串 raise ``ValueError``；
   - 历史表新增一行；Candidate.engagement_status 变更；
   - 多次变更按时间顺序追加。
"""
from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from agi_talent_radar.core.db.orm import (
    Base,
    CandidateORM,
    CandidateSourceORM,
    EngagementStatusHistoryORM,
    EvaluationORM,
    PersonORM,
)
from agi_talent_radar.core.db import repository
from agi_talent_radar.core.db.repository import evaluation_to_dict
from agi_talent_radar.core.domain_models import EngagementStatus
from agi_talent_radar.services import talent_service


class _TalentServiceTestBase(unittest.TestCase):
    """每个测试独占一个 sqlite 内存库；用 monkey-patch 把 talent_service
    的 ``get_session`` 指到当前测试 DB，避免污染 runtime engine 缓存。
    """

    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        # 替换 talent_service 内部 ``from agi_talent_radar.core.database``
        # 引入的 get_session（它在函数体内 import）。
        self._patch = patch(
            "agi_talent_radar.core.database.get_session", self._session_cm
        )
        self._patch.start()

    def tearDown(self) -> None:
        self._patch.stop()
        self.engine.dispose()

    def _session_cm(self):
        return self.Session()

    def _seed_person(self, person_id: str = "person-1", name: str = "张三") -> PersonORM:
        with self.Session() as session:
            person = PersonORM(
                id=person_id,
                name=name,
                org="某大学",
                direction="Agent",
                fingerprint=f"fp-{person_id}",
            )
            session.add(person)
            session.commit()
        return person

    def _seed_evaluation(
        self,
        evaluation_id: int,
        candidate_id: str,
        person_id: str,
        status: str = "completed",
    ) -> EvaluationORM:
        with self.Session() as session:
            eval_row = EvaluationORM(
                id=evaluation_id,
                candidate_id=candidate_id,
                person_id=person_id,
                status=status,
                evaluation_mode="multi_track_v1",
            )
            session.add(eval_row)
            session.commit()
        return eval_row


def patch(*args, **kwargs):
    from unittest.mock import patch as _patch

    return _patch(*args, **kwargs)


class TestAdmitCandidateAfterEvaluation(_TalentServiceTestBase):
    def test_admit_promotes_existing_submission_candidate_without_duplicate(self) -> None:
        """兼容期 Candidate 承载简历提交时，入库应原地晋升并保留核验状态。"""
        self._seed_person(person_id="p-promote", name="张向宇")
        with self.Session() as session:
            session.add(
                CandidateORM(
                    id="resume-submission",
                    name="张向宇",
                    stage="博四",
                    raw_text="完整简历原文",
                    publications='["Paper A"]',
                    academic_report={"alignments": [{"verdict": "verified"}]},
                    academic_check_status="done",
                )
            )
            session.commit()
        self._seed_evaluation(10, "resume-submission", "p-promote")

        result = talent_service.admit_candidate_after_evaluation(10)

        self.assertEqual(result["candidate_id"], "resume-submission")
        with self.Session() as session:
            rows = session.query(CandidateORM).all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].person_id, "p-promote")
            self.assertEqual(rows[0].academic_check_status, "done")
            self.assertTrue(rows[0].academic_report)
            evaluation = session.get(EvaluationORM, 10)
            self.assertEqual(evaluation.candidate_id, "resume-submission")

    def test_double_admit_same_person_creates_one_candidate(self) -> None:
        """同一 person 二次评估 → 一个 Candidate，resume_evaluation 来源幂等。"""
        candidate_id = "candidate-double"
        self._seed_person(person_id="p-double", name="重复评估")
        self._seed_evaluation(11, candidate_id, "p-double")
        self._seed_evaluation(12, candidate_id, "p-double")

        first = talent_service.admit_candidate_after_evaluation(11)
        second = talent_service.admit_candidate_after_evaluation(12)

        self.assertEqual(first["candidate_id"], second["candidate_id"])
        self.assertEqual(first["person_id"], "p-double")
        with self.Session() as session:
            candidates = (
                session.query(CandidateORM).filter_by(person_id="p-double").all()
            )
            self.assertEqual(len(candidates), 1, msg="同一 person 必须只有一个 Candidate")
            sources = (
                session.query(CandidateSourceORM)
                .filter_by(candidate_id=candidates[0].id)
                .all()
            )
            source_kinds = sorted(row.source_kind for row in sources)
            self.assertEqual(source_kinds, ["resume_evaluation"])

    def test_admit_appends_person_investigation_source(self) -> None:
        """admit + manual_admit 后该 Candidate 同时拥有两个来源。"""
        candidate_id = "candidate-mixed"
        self._seed_person(person_id="p-mixed")
        self._seed_evaluation(20, candidate_id, "p-mixed")

        admit_result = talent_service.admit_candidate_after_evaluation(20)
        manual_result = talent_service.manual_admit_person_to_pool(
            person_id="p-mixed",
            changed_by="hr-recruiter",
            note="人物画像后由 HR 手动加入人才库。",
        )

        self.assertEqual(admit_result["candidate_id"], manual_result["candidate_id"])
        with self.Session() as session:
            sources = (
                session.query(CandidateSourceORM)
                .filter_by(candidate_id=admit_result["candidate_id"])
                .all()
            )
            kinds = sorted(row.source_kind for row in sources)
            self.assertEqual(kinds, ["person_investigation", "resume_evaluation"])

    def test_admit_rejects_non_completed_evaluation(self) -> None:
        candidate_id = "candidate-running"
        self._seed_person(person_id="p-running")
        self._seed_evaluation(31, candidate_id, "p-running", status="running")
        with self.assertRaises(ValueError) as ctx:
            talent_service.admit_candidate_after_evaluation(31)
        self.assertIn("评估未完成", str(ctx.exception))

    def test_admit_rejects_missing_person_id(self) -> None:
        candidate_id = "candidate-no-person"
        with self.Session() as session:
            eval_row = EvaluationORM(
                id=40,
                candidate_id=candidate_id,
                person_id=None,
                status="completed",
                evaluation_mode="multi_track_v1",
            )
            session.add(eval_row)
            session.commit()
        with self.assertRaises(ValueError) as ctx:
            talent_service.admit_candidate_after_evaluation(40)
        self.assertIn("person_id", str(ctx.exception))

    def test_admit_does_not_touch_group_column(self) -> None:
        """admit 不应自动改写 Candidate.group；前端默认展示由手动接口管理。"""
        candidate_id = "candidate-group"
        self._seed_person(person_id="p-group")
        self._seed_evaluation(50, candidate_id, "p-group")
        talent_service.admit_candidate_after_evaluation(50)
        with self.Session() as session:
            candidate = (
                session.query(CandidateORM).filter_by(person_id="p-group").first()
            )
            self.assertEqual(candidate.group, "pending", msg="admit 不应改 group。")


class TestManualAdmitPerson(_TalentServiceTestBase):
    def test_changed_by_is_required(self) -> None:
        self._seed_person(person_id="p-required")
        with self.assertRaises(ValueError) as ctx:
            talent_service.manual_admit_person_to_pool(
                person_id="p-required", changed_by="", note="n"
            )
        self.assertIn("changed_by", str(ctx.exception))

    def test_whitespace_changed_by_rejected(self) -> None:
        self._seed_person(person_id="p-ws")
        with self.assertRaises(ValueError):
            talent_service.manual_admit_person_to_pool(
                person_id="p-ws", changed_by="   ", note="n"
            )

    def test_manual_admit_is_idempotent(self) -> None:
        self._seed_person(person_id="p-idem")
        first = talent_service.manual_admit_person_to_pool(
            person_id="p-idem", changed_by="hr", note="first"
        )
        second = talent_service.manual_admit_person_to_pool(
            person_id="p-idem", changed_by="hr", note="second"
        )
        self.assertEqual(first["candidate_id"], second["candidate_id"])
        with self.Session() as session:
            sources = (
                session.query(CandidateSourceORM)
                .filter_by(candidate_id=first["candidate_id"])
                .all()
            )
            self.assertEqual(len(sources), 1, msg="person_investigation 同 kind 必须幂等。")


class TestUpdateEngagementStatus(_TalentServiceTestBase):
    def setUp(self) -> None:
        super().setUp()
        self._seed_person(person_id="p-status")
        self._seed_evaluation(60, "candidate-status", "p-status")
        self._admit_result = talent_service.admit_candidate_after_evaluation(60)
        self.candidate_id = self._admit_result["candidate_id"]

    def test_changed_by_required(self) -> None:
        with self.assertRaises(ValueError):
            talent_service.update_engagement_status(
                candidate_id=self.candidate_id,
                status=EngagementStatus.CONTACTED,
                changed_by="",
                note="电话联系确认意向",
            )

    def test_invalid_status_rejected(self) -> None:
        with self.assertRaises(ValueError):
            talent_service.update_engagement_status(
                candidate_id=self.candidate_id,
                status="auto_recommend",  # type: ignore[arg-type]
                changed_by="hr",
                note="n",
            )

    def test_status_change_writes_audit_and_updates_candidate(self) -> None:
        first = talent_service.update_engagement_status(
            candidate_id=self.candidate_id,
            status=EngagementStatus.TO_CONTACT,
            changed_by="hr-recruiter",
            note="已发送邮件",
        )
        second = talent_service.update_engagement_status(
            candidate_id=self.candidate_id,
            status=EngagementStatus.CONTACTED,
            changed_by="hr-recruiter",
            note="电话沟通完成",
        )

        self.assertEqual(first.current, EngagementStatus.TO_CONTACT)
        self.assertEqual(first.previous, EngagementStatus.NEWLY_ADMITTED)
        self.assertEqual(second.current, EngagementStatus.CONTACTED)
        self.assertEqual(second.previous, EngagementStatus.TO_CONTACT)

        with self.Session() as session:
            history = repository.list_engagement_history(session, self.candidate_id)
            self.assertEqual(len(history), 2)
            self.assertEqual(history[0].current_status, "to_contact")
            self.assertEqual(history[1].current_status, "contacted")
            self.assertTrue(all(row.changed_by == "hr-recruiter" for row in history))

            candidate = session.get(CandidateORM, self.candidate_id)
            self.assertEqual(candidate.engagement_status, "contacted")


class TestEvaluateResume(_TalentServiceTestBase):
    """evaluate_resume 编排测试：走 admit 路径，不写 group。"""

    def test_evaluate_resume_unknown_submission_raises(self) -> None:
        with self.assertRaises(ValueError):
            talent_service.evaluate_resume("nonexistent")

    @patch("agi_talent_radar.core.runner.run_candidate")
    @patch("agi_talent_radar.services.talent_service.retry_publication_verification")
    def test_evaluate_resume_admits_and_does_not_write_group(
        self, mock_retry, mock_run
    ) -> None:
        from agi_talent_radar.core.models import CandidateEvaluation

        mock_run.return_value = CandidateEvaluation(
            id="c-eval",
            name="张三",
            target_role="研究员",
            stage="博士在读",
            overall_score=78,
            one_liner="高潜",
            core_strengths=[],
            potential_risks=[],
            interview_questions=[],
            cultivation_direction=[],
            dimension_scores=[],
            evidence=[],
        )
        # 准备 candidate + person + evaluation_run
        self._seed_person(person_id="p-eval")
        with self.Session() as session:
            from agi_talent_radar.core.db.orm import CandidateORM
            from agi_talent_radar.core.persons import get_or_create_person

            person = get_or_create_person(session, name="张三", direction="Agent")
            session.add(
                CandidateORM(
                    id="c-eval",
                    name="张三",
                    target_role="研究员",
                    stage="博士在读",
                    group="pending",
                    person_id=person.id,
                    raw_text="raw",
                    education="[]",
                    directions="[]",
                    experiences="[]",
                    projects="[]",
                    publications="[]",
                    skills="[]",
                    screening_tags="[]",
                )
            )
            session.commit()

        result = talent_service.evaluate_resume("c-eval")
        self.assertIn("evaluation_id", result)
        self.assertIn("admit", result)
        self.assertIn("resume_evaluation", result["admit"]["sources"])

        # Candidate.group 不被自动改写
        with self.Session() as session:
            from agi_talent_radar.core.db.orm import CandidateORM

            candidate = session.get(CandidateORM, "c-eval")
            self.assertEqual(candidate.group, "pending")

        # 论文核验 task 被派发
        mock_retry.assert_called()


class TestTrackRecommendation(_TalentServiceTestBase):
    def test_record_track_recommendation_reads_from_evaluation(self) -> None:
        candidate_id = "candidate-track"
        self._seed_person(person_id="p-track")
        self._seed_evaluation(70, candidate_id, "p-track")
        with self.Session() as session:
            evaluation = session.get(EvaluationORM, 70)
            evaluation.recommended_tracks = [
                {"track": "agent", "weight": 0.6, "confidence": 0.9},
                {"track": "base", "weight": 0.4, "confidence": 0.8},
            ]
            session.commit()

        result = talent_service.record_track_recommendation(70)
        self.assertEqual(result.evaluation_id, 70)
        self.assertEqual(len(result.tracks), 2)
        self.assertEqual(result.tracks[0]["track"], "agent")

    def test_record_track_recommendation_unknown_evaluation_raises(self) -> None:
        with self.assertRaises(ValueError):
            talent_service.record_track_recommendation(99999)


if __name__ == "__main__":
    unittest.main()
