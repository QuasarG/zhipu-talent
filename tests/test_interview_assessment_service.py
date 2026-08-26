from __future__ import annotations

import contextlib
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from agi_talent_radar.core.db.orm import (
    Base,
    CandidateJdAssessmentORM,
    CandidateORM,
    InterviewAssessmentPairLockORM,
    InterviewAssessmentRunORM,
    JdEntryORM,
)
from agi_talent_radar.services import interview_assessment_service as service


class InterviewAssessmentServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)

        @contextlib.contextmanager
        def session_scope():
            with self.Session() as session:
                yield session

        self.session_scope = session_scope
        with self.Session() as session:
            session.add(CandidateORM(id="candidate-1", name="候选人", raw_text="完成 Agent benchmark"))
            session.add(
                JdEntryORM(
                    id="jd-1",
                    title="Agent 研发",
                    raw_text="建设 Agent 系统",
                    card_status="ready",
                    assessment_card=_card(),
                )
            )
            session.commit()

    def test_valid_current_report_is_replaced_without_a_permission_flag(self) -> None:
        with self.Session() as session:
            session.add(
                CandidateJdAssessmentORM(
                    candidate_id="candidate-1",
                    jd_id="jd-1",
                    decision="interview",
                    total_score=80,
                )
            )
            session.commit()

        with patch.object(service, "get_session", self.session_scope):
            with patch.object(service._PAIR_EXECUTOR, "submit") as submit:
                batch = service.start_batch(["candidate-1"], ["jd-1"], None)

        self.assertEqual(batch["total_pairs"], 1)
        submit.assert_called_once()

    def test_failed_force_run_keeps_old_current_report(self) -> None:
        with self.Session() as session:
            current = CandidateJdAssessmentORM(
                candidate_id="candidate-1",
                jd_id="jd-1",
                decision="interview",
                total_score=80,
            )
            session.add(current)
            session.commit()

        with patch.object(service, "get_session", self.session_scope), patch.object(service._PAIR_EXECUTOR, "submit"):
            batch = service.start_batch(["candidate-1"], ["jd-1"], None)
            with self.Session() as session:
                run_id = session.query(InterviewAssessmentRunORM.id).filter_by(batch_id=batch["id"]).scalar()
            with patch.object(service, "evaluate_candidate_for_job", side_effect=RuntimeError("模型失败")):
                service._run_pair(run_id)

        with self.Session() as session:
            current = session.query(CandidateJdAssessmentORM).one()
            run = session.get(InterviewAssessmentRunORM, run_id)
            self.assertEqual(current.total_score, 80)
            self.assertTrue(current.is_valid)
            self.assertEqual(run.status, "failed")
            self.assertEqual(run.staged_result, {})
            self.assertEqual(session.query(InterviewAssessmentPairLockORM).count(), 0)

    def test_active_pair_is_locked_until_the_run_reaches_a_terminal_state(self) -> None:
        with patch.object(service, "get_session", self.session_scope), patch.object(service._PAIR_EXECUTOR, "submit"):
            batch = service.start_batch(["candidate-1"], ["jd-1"], None)
            with self.assertRaisesRegex(ValueError, "正在评估"):
                service.start_batch(["candidate-1"], ["jd-1"], None)
            with self.Session() as session:
                run = session.query(InterviewAssessmentRunORM).filter_by(batch_id=batch["id"]).one()
                self.assertEqual(session.query(InterviewAssessmentPairLockORM).count(), 1)
                run_id = run.id
            self.assertTrue(service.cancel_run(run_id))

        with self.Session() as session:
            self.assertEqual(session.query(InterviewAssessmentPairLockORM).count(), 0)

    def test_cancelled_run_discards_trace_and_staging(self) -> None:
        with patch.object(service, "get_session", self.session_scope), patch.object(service._PAIR_EXECUTOR, "submit"):
            batch = service.start_batch(["candidate-1"], ["jd-1"], None)
            with self.Session() as session:
                run = session.query(InterviewAssessmentRunORM).filter_by(batch_id=batch["id"]).one()
                run.run_trace = [{"node_id": "mapping"}]
                run.staged_result = {"partial": True}
                session.commit()
                run_id = run.id
            self.assertTrue(service.cancel_run(run_id))

        with self.Session() as session:
            run = session.get(InterviewAssessmentRunORM, run_id)
            self.assertEqual(run.status, "cancelled")
            self.assertEqual(run.run_trace, [])
            self.assertEqual(run.staged_result, {})


def _card() -> dict:
    def task(task_id: str, title: str, importance: str) -> dict:
        return {
            "id": task_id,
            "title": title,
            "description": f"围绕{title}完成设计、实现、验证和交付。",
            "importance": importance,
            "evaluation_focus": "根据项目难度、本人贡献、技术判断与成果评价。",
            "anchors": {
                "level_2": "实际参与并完成清晰的局部工作。",
                "level_3": "独立完成核心任务并解决关键问题。",
                "level_4": "复杂约束下成熟交付并沉淀方法。",
            },
        }

    return {
        "role_summary": "建设可靠可评测并能够稳定交付的智能体系统。",
        "core_tasks": [
            task("agent_system", "智能体系统研发", "primary"),
            task("evaluation", "智能体评测", "major"),
            task("delivery", "工程交付", "supporting"),
        ],
        "background_evidence_guidance": "学历和专业只辅助理解知识基础。",
        "excluded_requirements": [],
    }


if __name__ == "__main__":
    unittest.main()
