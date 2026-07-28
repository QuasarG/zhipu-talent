"""端到端集成测试：导入 → 评估 → 入库 → RAG 检索。

验证后端三条主线真的串起来了：

1. 简历评估主线：
   CandidateORM 存在 → evaluate_resume（mock LLM）→ EvaluationORM 写入 →
   CandidateSource(resume_evaluation) 追加 → vector_sync task 派发 →
   不写 group

2. 人才知识 Agent 主线：
   ask_talent_knowledge（mock intent=pool_query）→ 不调外部工具 → 返回 answer

3. 健康检查主线：
   /health 路由 → run_health_check → 返回 per-service 报告

这些测试用 sqlite 内存库 + mock LLM + InMemoryVectorStore，不依赖外网。
"""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from agi_talent_radar.core.db.orm import (
    Base,
    CandidateORM,
    CandidateSourceORM,
    EvaluationORM,
    PersonORM,
    TaskORM,
)
from agi_talent_radar.core.db import repository
from agi_talent_radar.knowledge_agent import ask_talent_knowledge
from agi_talent_radar.knowledge_agent.models import AgentEvent, UserIntent
from agi_talent_radar.services import talent_service


def _make_resume_candidate(session, candidate_id: str = "c-e2e") -> str:
    """准备一个 CandidateORM + 关联 Person。"""
    from agi_talent_radar.core.persons import get_or_create_person

    person = get_or_create_person(session, name="李四", direction="Agent")
    session.add(
        CandidateORM(
            id=candidate_id,
            name="李四",
            target_role="研究员",
            stage="博士在读",
            group="pending",
            person_id=person.id,
            raw_text="raw text",
            education="[]",
            directions='["Agent"]',
            experiences="[]",
            projects='[{"name":"项目A","details":["做X"]}]',
            publications='["Paper A"]',
            skills='["Python"]',
            screening_tags="[]",
        )
    )
    session.commit()
    return person.id


class TestResumeEvaluationE2E(unittest.TestCase):
    """简历评估端到端：evaluate_resume → 入库 → vector_sync task。"""

    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self._patch = patch(
            "agi_talent_radar.core.database.get_session", self._session_cm
        )
        self._patch.start()

    def tearDown(self) -> None:
        self._patch.stop()
        self.engine.dispose()

    def _session_cm(self):
        return self.Session()

    @patch("agi_talent_radar.core.runner.run_candidate")
    @patch("agi_talent_radar.services.talent_service.retry_publication_verification")
    def test_full_resume_evaluation_pipeline(self, mock_retry, mock_run) -> None:
        from agi_talent_radar.core.models import CandidateEvaluation

        mock_run.return_value = CandidateEvaluation(
            id="c-e2e",
            name="李四",
            target_role="研究员",
            stage="博士在读",
            overall_score=82,
            one_liner="高潜",
            core_strengths=["工程闭环"],
            potential_risks=[],
            interview_questions=[],
            cultivation_direction=[],
            dimension_scores=[],
            evidence=[],
        )

        with self.Session() as session:
            person_id = _make_resume_candidate(session, "c-e2e")

        # 执行评估编排
        result = talent_service.evaluate_resume("c-e2e")

        # 1. EvaluationORM 已写入
        with self.Session() as session:
            evaluations = session.query(EvaluationORM).filter_by(candidate_id="c-e2e").all()
            self.assertEqual(len(evaluations), 1)
            self.assertEqual(evaluations[0].status, "completed")
            self.assertEqual(evaluations[0].overall_score, 82)
            self.assertEqual(evaluations[0].person_id, person_id)

            # 2. CandidateSource(resume_evaluation) 已追加
            sources = (
                session.query(CandidateSourceORM)
                .filter_by(candidate_id="c-e2e")
                .all()
            )
            self.assertEqual(len(sources), 1)
            self.assertEqual(sources[0].source_kind, "resume_evaluation")

            # 3. vector_sync task 已派发
            sync_tasks = (
                session.query(TaskORM)
                .filter_by(task_type="vector_sync")
                .all()
            )
            self.assertEqual(len(sync_tasks), 1)
            self.assertEqual(sync_tasks[0].payload["person_id"], person_id)
            self.assertEqual(sync_tasks[0].payload["action"], "upsert")

            # 4. Candidate.group 未被自动改写
            candidate = session.get(CandidateORM, "c-e2e")
            self.assertEqual(candidate.group, "pending")

            # 5. 论文核验 task 已派发
            mock_retry.assert_called_once()


class TestKnowledgeAgentE2E(unittest.TestCase):
    """人才知识 Agent 端到端：pool_query 不调外部。"""

    def test_pool_query_returns_answer_without_external_tools(self) -> None:
        events = list(
            ask_talent_knowledge(
                "conv-e2e",
                "人才库里有哪些候选人？",
                inject_state={"intent": UserIntent.POOL_QUERY.value},
            )
        )
        types = [e.type for e in events]
        self.assertIn("intent", types)
        self.assertIn("answer", types)
        self.assertIn("done", types)
        # pool_query 不调外部
        self.assertNotIn("external_fact", types)
        self.assertNotIn("tool_failure", types)

    def test_talent_discovery_is_unsupported(self) -> None:
        events = list(
            ask_talent_knowledge(
                "conv-e2e-2",
                "帮我按 Agent 方向发现一批候选人",
                inject_state={"intent": UserIntent.TALENT_DISCOVERY.value},
            )
        )
        answer_event = next(e for e in events if e.type == "answer")
        self.assertIn("不在实现范围内", answer_event.payload["answer"])


class TestHealthRouteE2E(unittest.TestCase):
    """/health 路由调 run_health_check。"""

    def setUp(self) -> None:
        from agi_talent_radar.web.auth import (
            build_auth_blueprint,
            configure_app_session,
            install_auth_middleware,
        )
        from flask import Flask

        self.app = Flask(__name__)
        self.app.config["TESTING"] = True
        configure_app_session(self.app)
        self.app.register_blueprint(build_auth_blueprint())
        install_auth_middleware(self.app)
        self.client = self.app.test_client()

    @patch("agi_talent_radar.core.health.run_health_check")
    def test_health_returns_per_service_report(self, mock_health) -> None:
        from agi_talent_radar.core.health import HealthReport, ServiceHealth

        mock_health.return_value = HealthReport(
            overall="degraded",
            services=[
                ServiceHealth(name="mysql", status="ok", required=True),
                ServiceHealth(name="openalex", status="degraded", required=False),
            ],
            checked_at="2026-07-28T12:00:00",
        )
        rv = self.client.get("/health")
        self.assertEqual(rv.status_code, 200)  # degraded 不是 down
        data = rv.get_json()
        self.assertEqual(data["overall"], "degraded")
        self.assertEqual(len(data["services"]), 2)
        self.assertEqual(data["services"][1]["status"], "degraded")

    @patch("agi_talent_radar.core.health.run_health_check")
    def test_health_returns_503_when_mysql_down(self, mock_health) -> None:
        from agi_talent_radar.core.health import HealthReport, ServiceHealth

        mock_health.return_value = HealthReport(
            overall="down",
            services=[
                ServiceHealth(name="mysql", status="down", required=True),
            ],
            checked_at="2026-07-28T12:00:00",
        )
        rv = self.client.get("/health")
        self.assertEqual(rv.status_code, 503)


class TestKnowledgeRouteE2E(unittest.TestCase):
    """/api/knowledge/ask SSE 路由端到端。"""

    def setUp(self) -> None:
        from agi_talent_radar.web.auth import (
            build_auth_blueprint,
            configure_app_session,
            install_auth_middleware,
        )
        from agi_talent_radar.web.knowledge_api import build_knowledge_blueprint
        from flask import Flask

        self.app = Flask(__name__)
        self.app.config["TESTING"] = True
        configure_app_session(self.app)
        self.app.register_blueprint(build_auth_blueprint())
        self.app.register_blueprint(build_knowledge_blueprint())
        install_auth_middleware(self.app)
        # 放行鉴权（鉴权由 test_auth 独立覆盖）
        self._auth = patch(
            "agi_talent_radar.web.auth.is_authenticated", return_value=True
        )
        self._auth.start()
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        self._auth.stop()

    def test_ask_returns_sse_stream(self) -> None:
        rv = self.client.post(
            "/api/knowledge/ask",
            json={"prompt": "人才库里有哪些候选人？"},
        )
        self.assertEqual(rv.status_code, 200)
        self.assertIn("text/event-stream", rv.content_type)
        body = rv.data.decode("utf-8")
        # SSE 应包含 data: 前缀的事件
        self.assertIn("data: ", body)
        self.assertIn('"type"', body)

    def test_ask_rejects_empty_prompt(self) -> None:
        rv = self.client.post("/api/knowledge/ask", json={"prompt": ""})
        self.assertEqual(rv.status_code, 400)


if __name__ == "__main__":
    unittest.main()