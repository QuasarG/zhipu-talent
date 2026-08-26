from __future__ import annotations

import unittest

from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.orm import sessionmaker

from agi_talent_radar.core.db.orm import (
    Base,
    CandidateORM,
    CandidateSourceORM,
    DimensionScoreORM,
    EngagementStatusHistoryORM,
    EvaluationEvidenceORM,
    EvaluationNodeRunORM,
    EvaluationORM,
    PersonORM,
    PublicationClaimORM,
    PublicationVerificationORM,
    ResumeSubmissionORM,
    ResumeVersionORM,
    SchemaVersionORM,
    TaskORM,
    TrackAssignmentORM,
    TrackEvaluationORM,
)
from agi_talent_radar.core.db.migrations import LATEST_SCHEMA_VERSION, ensure_schema
from agi_talent_radar.core.db.repository import (
    create_task,
    delete_person,
    evaluation_to_dict,
    get_candidate_with_latest_evaluation,
    record_node_event,
    save_candidate,
    save_evaluation,
    start_evaluation_run,
    update_task,
)
from agi_talent_radar.core.persons import get_or_create_person
from agi_talent_radar.core.models import (
    CandidateEvaluation,
    CandidateResume,
    DimensionScore,
    DirectionRecommendation,
    EvidenceItem,
    JobFitAssessment,
    JobFitDimension,
    TrackAssignment,
    TrackEvaluation,
)


class DatabaseTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)

    def tearDown(self) -> None:
        self.engine.dispose()

    def test_multi_track_evaluation_is_normalized_and_round_trips(self) -> None:
        with self.Session() as session:
            save_candidate(session, CandidateResume(id="candidate_db", name="DB 候选人"))
            run = start_evaluation_run(session, "candidate_db")
            record_node_event(
                session,
                run.id,
                {
                    "node": "track_router",
                    "phase": "routing",
                    "status": "done",
                    "message": "路由至 Agent 70% 和 Systems 30%",
                },
            )
            evaluation = _evaluation(82)
            evaluation.recommended_tracks = [
                DirectionRecommendation(
                    track="agent",
                    label="Agent Track",
                    score=50,
                    confidence=0.92,
                    rationale="Agent 推荐",
                    evidence_ids=["e1"],
                )
            ]
            evaluation.academic_report = {
                "alignments": [
                    {
                        "claim": {"title": "Verified Paper"},
                        "verdict": "mismatch",
                        "discrepancies": ["作者顺序不一致"],
                    }
                ],
                "warnings": [],
            }
            evaluation.interview_decision = "interview"
            evaluation.best_fit_jd_id = "jd-agent"
            evaluation.best_fit_jd_title = "Agent 评测"
            evaluation.decision_summary = "进入面试：核心任务证据充分。"
            evaluation.job_fit_assessments = [
                JobFitAssessment(
                    jd_id="jd-agent",
                    jd_title="Agent 评测",
                    decision="interview",
                    confidence=0.9,
                    fit_score=82,
                    dimensions=[
                        JobFitDimension(
                            key="direct_task_match",
                            label="直接任务匹配",
                            score=4.2,
                            weight=30,
                            evidence=["设计工具调用与自动验证闭环"],
                        )
                    ],
                    decision_reason="进入面试：核心任务证据充分。",
                )
            ]
            saved = save_evaluation(session, evaluation, evaluation_id=run.id)

            self.assertEqual(_count(session, EvaluationORM), 1)
            self.assertEqual(_count(session, EvaluationNodeRunORM), 1)
            self.assertEqual(_count(session, EvaluationEvidenceORM), 2)
            self.assertEqual(_count(session, TrackAssignmentORM), 2)
            self.assertEqual(_count(session, TrackEvaluationORM), 2)
            self.assertEqual(_count(session, DimensionScoreORM), 3)

            payload = evaluation_to_dict(saved)
            self.assertEqual(payload["status"], "completed")
            self.assertEqual(payload["track_assignments"][0]["evidence_ids"], ["e1"])
            self.assertEqual(payload["recommended_tracks"][0]["weight"], 0.7)
            self.assertEqual(payload["track_evaluations"][0]["dimension_scores"][0]["key"], "agent_architecture")
            self.assertEqual(payload["dimension_scores"][0]["evidence_ids"], ["e1", "e2"])
            self.assertEqual(payload["node_runs"][0]["node"], "track_router")
            self.assertEqual(payload["academic_report"]["alignments"][0]["verdict"], "mismatch")
            self.assertEqual(payload["interview_decision"], "interview")
            self.assertEqual(payload["best_fit_jd_id"], "jd-agent")
            self.assertEqual(payload["job_fit_assessments"][0]["fit_score"], 82)
            graph_nodes = [
                node["node"]
                for phase in payload["evaluation_graph"]["phases"]
                for group in phase["groups"]
                for node in group["nodes"]
            ]
            # 与图目录动态比对：加节点不用改这里（旧断言写死 15，catalog 演进到 17 后过时红灯）
            from agi_talent_radar.core.graph import evaluation_graph_catalog as _catalog

            catalog_nodes = [
                node["node"]
                for phase in _catalog()["phases"]
                for group in phase["groups"]
                for node in group["nodes"]
            ]
            self.assertEqual(sorted(graph_nodes), sorted(catalog_nodes))
            self.assertEqual(len(graph_nodes), len(set(graph_nodes)))
            # 论文核验前移到导入阶段后，academic_check 不再出现在展示图谱
            self.assertNotIn("academic_check", graph_nodes)
            # 硬编码 6 track 已废弃：图谱只暴露单个 JD 驱动动态节点
            self.assertEqual(
                graph_nodes,
                ["candidate_preparer", "jd_fit_assessor", "decision_guard", "result_formatter"],
            )
            self.assertEqual(
                [phase["key"] for phase in payload["evaluation_graph"]["phases"]],
                ["preparation", "assessment", "decision"],
            )

    def test_repeated_evaluations_preserve_history(self) -> None:
        with self.Session() as session:
            save_candidate(session, CandidateResume(id="candidate_db", name="DB 候选人"))
            first = save_evaluation(session, _evaluation(72))
            second = save_evaluation(session, _evaluation(88))

            self.assertNotEqual(first.id, second.id)
            self.assertEqual(_count(session, EvaluationORM), 2)
            _, latest = get_candidate_with_latest_evaluation(session, "candidate_db")
            self.assertEqual(latest.id, second.id)
            self.assertEqual(latest.overall_score, 88)

    def test_evaluation_links_person_master_record(self) -> None:
        with self.Session() as session:
            save_candidate(session, CandidateResume(id="candidate_db", name="DB 候选人", directions=["Agent 安全"]))
            first = save_evaluation(session, _evaluation(72))
            second = save_evaluation(session, _evaluation(88))

            self.assertTrue(first.person_id)
            self.assertEqual(first.person_id, second.person_id)
            self.assertTrue(first.config_version.startswith("scoring-"))
            person = session.get(PersonORM, first.person_id)
            self.assertEqual(person.name, "DB 候选人")
            self.assertEqual(person.direction, "Agent 安全")

    def test_person_fingerprint_merges_same_identity(self) -> None:
        with self.Session() as session:
            early = get_or_create_person(session, name="张三")
            later = get_or_create_person(session, name="张 三", org="某大学", person_type="guest")

            self.assertEqual(early.id, later.id)
            self.assertEqual(later.org, "某大学")
            self.assertEqual(_count(session, PersonORM), 1)

    def test_delete_person_removes_complete_resume_record_tree(self) -> None:
        with self.Session() as session:
            person = PersonORM(id="person-delete", name="待删除", fingerprint="fp-delete")
            candidate = CandidateORM(id="candidate-delete", name="待删除", person_id=person.id)
            evaluation = EvaluationORM(
                id=901,
                candidate_id=candidate.id,
                person_id=person.id,
                status="completed",
            )
            submission = ResumeSubmissionORM(
                id="submission-delete",
                candidate_id=candidate.id,
                person_id=person.id,
                source_format="pdf",
                raw_text="原始简历",
            )
            session.add_all([person, candidate, evaluation, submission])
            session.flush()
            session.add_all([
                ResumeVersionORM(
                    id="version-delete",
                    submission_id=submission.id,
                    version=1,
                    raw_text="原始简历",
                ),
                CandidateSourceORM(candidate_id=candidate.id, source_kind="resume_evaluation"),
                EngagementStatusHistoryORM(
                    candidate_id=candidate.id,
                    previous_status="newly_admitted",
                    current_status="contacted",
                    changed_by="hr",
                ),
            ])
            claim = PublicationClaimORM(
                evaluation_id=evaluation.id,
                claim_key="paper-1",
                title="Paper A",
            )
            session.add(claim)
            session.flush()
            session.add(PublicationVerificationORM(claim_id=claim.id, source="aminer"))
            session.commit()

            deleted = delete_person(session, person.id)

            self.assertIsNotNone(deleted)
            for model in (
                PersonORM,
                CandidateORM,
                EvaluationORM,
                ResumeSubmissionORM,
                ResumeVersionORM,
                CandidateSourceORM,
                EngagementStatusHistoryORM,
                PublicationClaimORM,
                PublicationVerificationORM,
            ):
                self.assertEqual(_count(session, model), 0, msg=f"{model.__name__} 未清理")

    def test_ensure_schema_creates_platform_tables(self) -> None:
        ensure_schema(self.engine)
        tables = set(inspect(self.engine).get_table_names())
        self.assertTrue({"persons", "external_facts", "reputation_reports", "tasks"} <= tables)
        evaluation_columns = {column["name"] for column in inspect(self.engine).get_columns("evaluations")}
        self.assertTrue({"person_id", "config_version"} <= evaluation_columns)
        with self.Session() as session:
            self.assertIsNotNone(session.get(SchemaVersionORM, LATEST_SCHEMA_VERSION))

    def test_task_lifecycle_helpers(self) -> None:
        with self.Session() as session:
            task = create_task(session, "reputation", {"person_id": "p1"})
            update_task(session, task.id, status="running", progress={"step": 1})
            update_task(session, task.id, status="done")
            final = session.get(TaskORM, task.id)
            self.assertEqual(final.status, "done")
            self.assertEqual(final.progress, {"step": 1})

    def test_legacy_json_columns_are_backfilled_then_removed(self) -> None:
        engine = create_engine("sqlite+pysqlite:///:memory:")
        try:
            with engine.begin() as connection:
                connection.execute(text("CREATE TABLE candidates (id VARCHAR(32) PRIMARY KEY, `group` VARCHAR(32), created_at DATETIME)"))
                connection.execute(
                    text(
                        """
                        CREATE TABLE evaluations (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            candidate_id VARCHAR(32) NOT NULL,
                            overall_score INTEGER,
                            level VARCHAR(8), tier VARCHAR(64), decision_method TEXT, one_liner TEXT,
                            core_strengths JSON, potential_risks JSON, interview_questions JSON,
                            cultivation_direction JSON, dimension_scores JSON, evidence JSON,
                            critic_flags JSON, normalized_education JSON, screening_tags JSON,
                            common_score FLOAT, document_score FLOAT, track_assignments JSON,
                            track_evaluations JSON, routing_confidence FLOAT,
                            evaluation_mode VARCHAR(64), created_at DATETIME
                        )
                        """
                    )
                )
                connection.execute(text("INSERT INTO candidates (id, `group`) VALUES ('legacy', 'pending')"))
                connection.execute(
                    text(
                        """
                        INSERT INTO evaluations (
                            candidate_id, overall_score, level, tier, dimension_scores, evidence,
                            track_assignments, track_evaluations, created_at
                        ) VALUES (
                            'legacy', 80, 'S', '强烈建议沟通', :dimensions, :evidence,
                            :assignments, :track_evaluations, CURRENT_TIMESTAMP
                        )
                        """
                    ),
                    {
                        "dimensions": '[{"key":"research_rigor","label":"研究严谨性","score":4,"evidence_ids":["e1"]}]',
                        "evidence": '[{"id":"e1","dimension":"research_rigor","source":"项目","quote":"对照实验","strength":4}]',
                        "assignments": '[{"track":"agent","weight":1,"confidence":0.9,"evidence_ids":["e1"]}]',
                        "track_evaluations": '[{"track":"agent","label":"Agent Track","weight":1,"confidence":0.9,"raw_score":50,"calibrated_score":48,"dimension_scores":[],"evidence_ids":["e1"]}]',
                    },
                )

            ensure_schema(engine)
            columns = {column["name"] for column in inspect(engine).get_columns("evaluations")}
            candidate_columns = {column["name"] for column in inspect(engine).get_columns("candidates")}
            self.assertFalse({"dimension_scores", "evidence", "track_assignments", "track_evaluations"} & columns)
            self.assertIn("experiences", candidate_columns)
            Session = sessionmaker(bind=engine)
            with Session() as session:
                self.assertEqual(_count(session, EvaluationEvidenceORM), 1)
                self.assertEqual(_count(session, TrackAssignmentORM), 1)
                self.assertEqual(_count(session, TrackEvaluationORM), 1)
                self.assertEqual(_count(session, DimensionScoreORM), 1)
        finally:
            engine.dispose()


def _evaluation(score: int) -> CandidateEvaluation:
    evidence = [
        EvidenceItem(
            id="e1",
            dimension="track_specific",
            source="项目 A",
            quote="设计工具调用与自动验证闭环",
            signals=["工具调用", "自动验证"],
            strength=5,
            has_specific_tool=True,
            has_ownership=True,
            track_hints=["agent"],
        ),
        EvidenceItem(
            id="e2",
            dimension="research_rigor",
            source="项目 B",
            quote="通过对照实验验证系统吞吐",
            signals=["对照实验"],
            strength=4,
            has_metric=True,
            track_hints=["ai_infra"],
        ),
    ]
    common_dimension = DimensionScore(
        key="research_rigor",
        label="研究严谨性",
        score=4.2,
        weighted_score=6.7,
        max_points=8,
        rationale="e1 和 e2 显示验证闭环。",
        evidence_ids=["e1", "e2"],
    )
    agent_dimension = DimensionScore(
        key="agent_architecture",
        label="Agent 架构能力",
        score=4.5,
        weighted_score=15,
        max_points=18,
        rationale="e1 支撑。",
        evidence_ids=["e1"],
    )
    systems_dimension = DimensionScore(
        key="systems_optimization",
        label="系统优化",
        score=4.0,
        weighted_score=12,
        max_points=16,
        rationale="e2 支撑。",
        evidence_ids=["e2"],
    )
    return CandidateEvaluation(
        id="candidate_db",
        name="DB 候选人",
        target_role="Agent 研究员",
        stage="博士在读",
        overall_score=score,
        level="S" if score >= 80 else "B",
        tier="强烈建议沟通" if score >= 80 else "建议沟通",
        one_liner="Agent 与系统能力兼具。",
        core_strengths=["Agent 闭环"],
        potential_risks=["待验证贡献边界"],
        interview_questions=["如何设计失败恢复？"],
        cultivation_direction=["Coding Agent"],
        dimension_scores=[common_dimension],
        evidence=evidence,
        common_score=32,
        document_score=2,
        routing_confidence=0.9,
        track_assignments=[
            TrackAssignment(track="agent", weight=0.7, confidence=0.92, rationale="e1", evidence_ids=["e1"]),
            TrackAssignment(track="ai_infra", weight=0.3, confidence=0.84, rationale="e2", evidence_ids=["e2"]),
        ],
        track_evaluations=[
            TrackEvaluation(
                track="agent",
                label="Agent Track",
                weight=0.7,
                confidence=0.92,
                raw_score=52,
                calibrated_score=50,
                dimension_scores=[agent_dimension],
                evidence_ids=["e1"],
            ),
            TrackEvaluation(
                track="ai_infra",
                label="Systems Track",
                weight=0.3,
                confidence=0.84,
                raw_score=48,
                calibrated_score=46,
                dimension_scores=[systems_dimension],
                evidence_ids=["e2"],
            ),
        ],
    )


def _count(session, model) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


class TestSqliteConcurrentWrites(unittest.TestCase):
    """WAL + busy_timeout 回归：多线程并发写 sqlite 不得出现 database is locked。"""

    def test_concurrent_writes_no_lock_error(self) -> None:
        import tempfile
        import threading

        from agi_talent_radar.core.db.runtime import _make_engine

        with tempfile.TemporaryDirectory() as tmp:
            engine = _make_engine(f"sqlite:///{tmp}/t.db")
            Base.metadata.create_all(engine)
            with engine.connect() as conn:
                mode = conn.exec_driver_sql("PRAGMA journal_mode").scalar()
            self.assertEqual(mode, "wal")

            errors: list[Exception] = []

            def writer(index: int) -> None:
                try:
                    Session = sessionmaker(bind=engine, expire_on_commit=False)
                    with Session() as session:
                        for j in range(20):
                            session.add(CandidateORM(id=f"c-{index}-{j}", name="x"))
                            session.commit()
                except Exception as exc:  # noqa: BLE001
                    errors.append(exc)

            threads = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            engine.dispose()

        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
