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

    def test_valid_current_report_requires_an_audited_force_reason(self) -> None:
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
                with self.assertRaisesRegex(ValueError, "强制重评必须填写原因"):
                    service.start_batch(["candidate-1"], ["jd-1"], None)
                batch = service.start_batch(
                    ["candidate-1"],
                    ["jd-1"],
                    None,
                    force_reason="岗位要求发生实质变化",
                )

        self.assertEqual(batch["total_pairs"], 1)
        self.assertEqual(batch["force_reason"], "岗位要求发生实质变化")
        submit.assert_called_once()

    def test_same_request_id_returns_the_original_batch_without_resubmitting(self) -> None:
        with patch.object(service, "get_session", self.session_scope):
            with patch.object(service._PAIR_EXECUTOR, "submit") as submit:
                first = service.start_batch(
                    ["candidate-1"], ["jd-1"], None, request_id="request-1"
                )
                second = service.start_batch(
                    ["candidate-1"], ["jd-1"], None, request_id="request-1"
                )

        self.assertEqual(second["id"], first["id"])
        submit.assert_called_once()

    def test_request_id_cannot_be_reused_for_different_pairs(self) -> None:
        with self.Session() as session:
            session.add(
                JdEntryORM(
                    id="jd-2",
                    title="评测研发",
                    raw_text="建设评测系统",
                    card_status="ready",
                    assessment_card=_card(),
                )
            )
            session.commit()

        with patch.object(service, "get_session", self.session_scope), patch.object(
            service._PAIR_EXECUTOR, "submit"
        ):
            service.start_batch(
                ["candidate-1"], ["jd-1"], None, request_id="request-1"
            )
            with self.assertRaisesRegex(ValueError, "另一组"):
                service.start_batch(
                    ["candidate-1"], ["jd-2"], None, request_id="request-1"
                )

    def test_explicit_pairs_do_not_expand_to_a_cartesian_product(self) -> None:
        with self.Session() as session:
            session.add(CandidateORM(id="candidate-2", name="候选人二", raw_text="评测"))
            session.add(
                JdEntryORM(
                    id="jd-2",
                    title="评测研发",
                    raw_text="建设评测系统",
                    card_status="ready",
                    assessment_card=_card(),
                )
            )
            session.commit()

        with patch.object(service, "get_session", self.session_scope), patch.object(
            service._PAIR_EXECUTOR, "submit"
        ) as submit:
            batch = service.start_batch(
                ["candidate-1", "candidate-2"],
                ["jd-1", "jd-2"],
                None,
                pairs=[("candidate-1", "jd-1"), ("candidate-2", "jd-2")],
            )

        self.assertEqual(batch["total_pairs"], 2)
        self.assertEqual(submit.call_count, 2)

    def test_batch_pair_limit_is_enforced_before_database_writes(self) -> None:
        pairs = [(f"candidate-{index}", "jd-1") for index in range(service.MAX_BATCH_PAIRS + 1)]
        with patch.object(service, "get_session", self.session_scope):
            with self.assertRaisesRegex(ValueError, "单批最多"):
                service.start_batch([], [], None, pairs=pairs)

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
            batch = service.start_batch(
                ["candidate-1"], ["jd-1"], None, force_reason="验证失败时保留旧报告"
            )
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

    def test_reports_return_candidate_name_and_jd_title(self) -> None:
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

        with patch.object(service, "get_session", self.session_scope), patch.object(service._PAIR_EXECUTOR, "submit"):
            service.start_batch(
                ["candidate-1"], ["jd-1"], None, force_reason="验证报告与活动运行标签"
            )
            reports = service.list_current_assessments()
            active = service.list_active_runs()

        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0]["candidate_name"], "候选人")
        self.assertEqual(reports[0]["jd_title"], "Agent 研发")
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["candidate_name"], "候选人")
        self.assertEqual(active[0]["jd_title"], "Agent 研发")

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

    def test_running_run_becomes_terminal_immediately_when_cancelled(self) -> None:
        with patch.object(service, "get_session", self.session_scope), patch.object(service._PAIR_EXECUTOR, "submit"):
            batch = service.start_batch(["candidate-1"], ["jd-1"], None)
            with self.Session() as session:
                run = session.query(InterviewAssessmentRunORM).filter_by(batch_id=batch["id"]).one()
                run.status = "running"
                run.current_node = "task_score:agent_system"
                run.run_trace = [{"node_id": "task_score:agent_system"}]
                run.staged_result = {"partial": True}
                session.commit()
                run_id = run.id

            self.assertTrue(service.cancel_run(run_id))

        with self.Session() as session:
            run = session.get(InterviewAssessmentRunORM, run_id)
            self.assertEqual(run.status, "cancelled")
            self.assertTrue(run.cancellation_requested)
            self.assertEqual(run.current_node, "")
            self.assertEqual(run.run_trace, [])
            self.assertEqual(run.staged_result, {})
            self.assertEqual(session.query(InterviewAssessmentPairLockORM).count(), 0)

    def test_running_batch_becomes_terminal_immediately_when_cancelled(self) -> None:
        with self.Session() as session:
            session.add(
                JdEntryORM(
                    id="jd-2",
                    title="评测研发",
                    raw_text="建设评测系统",
                    card_status="ready",
                    assessment_card=_card(),
                )
            )
            session.commit()

        with patch.object(service, "get_session", self.session_scope), patch.object(service._PAIR_EXECUTOR, "submit"):
            batch = service.start_batch(["candidate-1"], ["jd-1", "jd-2"], None)
            with self.Session() as session:
                runs = session.query(InterviewAssessmentRunORM).filter_by(batch_id=batch["id"]).all()
                for run in runs:
                    run.status = "running"
                    run.current_node = "task_score:agent_system"
                session.commit()

            self.assertEqual(service.cancel_batch(batch["id"]), 2)

        with self.Session() as session:
            runs = session.query(InterviewAssessmentRunORM).filter_by(batch_id=batch["id"]).all()
            self.assertTrue(all(run.status == "cancelled" for run in runs))
            self.assertTrue(all(run.cancellation_requested for run in runs))
            self.assertEqual(session.query(InterviewAssessmentPairLockORM).count(), 0)

    def test_late_worker_failure_cannot_overwrite_cancelled_status(self) -> None:
        with patch.object(service, "get_session", self.session_scope), patch.object(service._PAIR_EXECUTOR, "submit"):
            batch = service.start_batch(["candidate-1"], ["jd-1"], None)
            with self.Session() as session:
                run_id = session.query(InterviewAssessmentRunORM.id).filter_by(batch_id=batch["id"]).scalar()

            def fail_after_cancellation(*_args, **_kwargs):
                self.assertTrue(service.cancel_run(run_id))
                raise RuntimeError("迟到的模型错误")

            with patch.object(service, "evaluate_candidate_for_job", side_effect=fail_after_cancellation):
                service._run_pair(run_id)

        with self.Session() as session:
            run = session.get(InterviewAssessmentRunORM, run_id)
            self.assertEqual(run.status, "cancelled")
            self.assertEqual(run.error_message, "")

    def test_active_run_listing_recovers_legacy_pending_cancellation(self) -> None:
        with patch.object(service, "get_session", self.session_scope), patch.object(service._PAIR_EXECUTOR, "submit"):
            batch = service.start_batch(["candidate-1"], ["jd-1"], None)
            with self.Session() as session:
                run = session.query(InterviewAssessmentRunORM).filter_by(batch_id=batch["id"]).one()
                run.status = "running"
                run.cancellation_requested = True
                session.commit()
                run_id = run.id

            self.assertEqual(service.list_active_runs(), [])

        with self.Session() as session:
            run = session.get(InterviewAssessmentRunORM, run_id)
            self.assertEqual(run.status, "cancelled")
            self.assertEqual(session.query(InterviewAssessmentPairLockORM).count(), 0)


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
