"""人才问答工具层测试：只读工具 handler + 门控工具 execute_gated_action。

用 sqlite 内存库 + FakeEmbeddingClient/InMemoryVectorStore，不打外网、不打真实 MySQL。
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from agi_talent_radar.core.db.orm import (
    Base,
    CandidateORM,
    EvaluationORM,
    ExternalFactORM,
    PersonORM,
    ReputationReportORM,
    ResumeSubmissionORM,
)
from agi_talent_radar.core.embedding import FakeEmbeddingClient
from agi_talent_radar.core.persons import person_fingerprint
from agi_talent_radar.knowledge_agent.tools import (
    ToolContext,
    execute_gated_action,
    tool_aggregate_persons,
    tool_ask_clarification,
    tool_check_reputation,
    tool_get_person_evaluation,
    tool_get_person_profile,
    tool_get_resume_versions,
    tool_propose_add_person,
    tool_resolve_fact_conflict,
    tool_search_knowledge,
    tool_search_persons,
    tool_select_person,
)


def _add_person(session, name: str, org: str = "", direction: str = "", person_id: str = "") -> PersonORM:
    person = PersonORM(
        id=person_id or f"p-{name}",
        name=name,
        org=org,
        direction=direction,
        fingerprint=person_fingerprint(name, org, direction) + person_id,
        person_type="student",
    )
    session.add(person)
    session.commit()
    return person


def _add_submission(session, person_id: str, structured: dict) -> ResumeSubmissionORM:
    submission = ResumeSubmissionORM(
        id=f"sub-{person_id}",
        person_id=person_id,
        source_format="text",
        raw_text="简历原文",
        structured=structured,
    )
    session.add(submission)
    session.commit()
    return submission


def _add_evaluation(session, person_id: str, candidate_id: str, score: int) -> EvaluationORM:
    if session.get(CandidateORM, candidate_id) is None:
        session.add(CandidateORM(id=candidate_id, name="占位"))
        session.commit()
    evaluation = EvaluationORM(
        candidate_id=candidate_id,
        person_id=person_id,
        status="completed",
        overall_score=score,
    )
    session.add(evaluation)
    session.commit()
    return evaluation


class ChatToolsTestBase(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.session = sessionmaker(bind=engine, expire_on_commit=False)()
        self.ctx = ToolContext(self.session)

    def tearDown(self) -> None:
        self.session.close()


class TestSearchPersons(ChatToolsTestBase):
    def test_empty_pool(self) -> None:
        result = tool_search_persons(self.ctx, {})
        self.assertEqual(result["persons"], [])
        self.assertIn("0 人", result["summary"])

    def test_reputation_search_does_not_expose_connector_exception(self) -> None:
        from agi_talent_radar.core.connectors.base import ConnectorUnavailableError

        with patch(
            "agi_talent_radar.core.connectors.web_search.search_web",
            side_effect=ConnectorUnavailableError(
                "HTTP 500 https://provider.example/v1 secret-token stack trace"
            ),
        ):
            result = tool_check_reputation(self.ctx, {"name": "测试人物"})

        self.assertEqual(result["errors"], ["网络搜索暂时不可用，请稍后重试"])
        self.assertNotIn("provider.example", str(result))

    def test_hit_by_name_and_direction(self) -> None:
        _add_person(self.session, "李四", org="清华大学", direction="NLP")
        _add_person(self.session, "张三", org="北京大学", direction="CV")
        by_name = tool_search_persons(self.ctx, {"name": "李"})
        self.assertEqual([p["name"] for p in by_name["persons"]], ["李四"])
        self.assertEqual(by_name["persons"][0]["person_id"], "p-李四")
        by_direction = tool_search_persons(self.ctx, {"direction": "CV"})
        self.assertEqual([p["name"] for p in by_direction["persons"]], ["张三"])
        by_school = tool_search_persons(self.ctx, {"school": "清华"})
        self.assertEqual([p["name"] for p in by_school["persons"]], ["李四"])
        all_persons = tool_search_persons(self.ctx, {})
        self.assertEqual(len(all_persons["persons"]), 2)


class TestGetPersonProfile(ChatToolsTestBase):
    def test_unknown_person(self) -> None:
        result = tool_get_person_profile(self.ctx, {"person_id": "nobody"})
        self.assertFalse(result["found"])

    def test_profile_with_resume(self) -> None:
        person = _add_person(self.session, "李四")
        _add_submission(
            self.session,
            person.id,
            {
                "education": [{"school": "清华大学", "degree": "硕士"}],
                "experiences": [{"organization": "智谱", "role": "实习生"}],
                "skills": ["Python"],
                "publications": ["Paper A"],
            },
        )
        result = tool_get_person_profile(self.ctx, {"person_id": person.id})
        self.assertTrue(result["found"])
        self.assertTrue(result["has_resume"])
        self.assertEqual(result["skills"], ["Python"])
        self.assertEqual(result["publications"], ["Paper A"])
        # 引用注册：citation_id 进入注册表
        self.assertEqual(result["citation_id"], "c1")
        self.assertEqual(self.ctx.sources[0]["id"], "c1")
        self.assertEqual(self.ctx.sources[0]["type"], "resume")

    def test_profile_without_resume(self) -> None:
        person = _add_person(self.session, "王五")
        result = tool_get_person_profile(self.ctx, {"person_id": person.id})
        self.assertTrue(result["found"])
        self.assertFalse(result["has_resume"])
        self.assertEqual(result["education"], [])


class TestAggregatePersons(ChatToolsTestBase):
    def setUp(self) -> None:
        super().setUp()
        p1 = _add_person(self.session, "李四")
        p2 = _add_person(self.session, "张三")
        _add_evaluation(self.session, p1.id, "c-李四", 90)
        _add_evaluation(self.session, p2.id, "c-张三", 70)
        _add_submission(self.session, p1.id, {"publications": ["A", "B"]})
        _add_submission(self.session, p2.id, {"publications": []})

    def test_metric_count(self) -> None:
        result = tool_aggregate_persons(self.ctx, {"metric": "count"})
        self.assertEqual(result["total"], 2)
        self.assertEqual(len(result["rows"]), 2)

    def test_metric_avg_score_sorted_desc(self) -> None:
        result = tool_aggregate_persons(self.ctx, {"metric": "avg_score"})
        self.assertEqual([r["name"] for r in result["rows"]], ["李四", "张三"])
        self.assertEqual(result["rows"][0]["score"], 90)

    def test_metric_pub_count(self) -> None:
        result = tool_aggregate_persons(self.ctx, {"metric": "pub_count"})
        self.assertEqual(result["rows"][0]["name"], "李四")
        self.assertEqual(result["rows"][0]["pub_count"], 2)

    def test_top_n_limit(self) -> None:
        result = tool_aggregate_persons(self.ctx, {"metric": "count", "top_n": 1})
        self.assertEqual(len(result["rows"]), 1)


def _fake_embed_texts(texts, client=None):
    return FakeEmbeddingClient().embed(texts)


class TestSearchKnowledge(ChatToolsTestBase):
    def _fake_store_with_one_point(self):
        from agi_talent_radar.core.embedding import FakeEmbeddingClient
        from agi_talent_radar.core.vector_store import InMemoryVectorStore, VectorPoint
        from agi_talent_radar.knowledge_agent.chunker import (
            KnowledgeChunk,
            chunk_to_payload,
        )

        chunk = KnowledgeChunk(
            text="李四，清华大学，NLP 方向",
            record_type="resume_profile",
            record_id="p-李四:profile",
            person_id="p-李四",
            candidate_id="c-李四",
            fact_status="confirmed",
            source="resume",
            fetched_at="2026-08-01T00:00:00",
        )
        store = InMemoryVectorStore()
        store.upsert(
            [
                VectorPoint(
                    vector=FakeEmbeddingClient().embed(["李四 清华大学 NLP"])[0],
                    payload=chunk_to_payload(chunk, "v1"),
                )
            ]
        )
        return store

    def test_hit_registers_citation(self) -> None:
        store = self._fake_store_with_one_point()
        with (
            patch("agi_talent_radar.core.embedding.embed_texts", side_effect=_fake_embed_texts),
            patch("agi_talent_radar.core.vector_store.QdrantVectorStore", return_value=store),
        ):
            result = tool_search_knowledge(self.ctx, {"query": "李四", "top_k": 5})
        self.assertEqual(len(result["hits"]), 1)
        hit = result["hits"][0]
        self.assertEqual(hit["person_id"], "p-李四")
        self.assertEqual(hit["citation_id"], "c1")
        self.assertEqual(hit["fact_status"], "confirmed")
        self.assertEqual(self.ctx.sources[0]["id"], "c1")
        self.assertEqual(self.ctx.sources[0]["type"], "resume_profile")

    def test_vector_store_down_degrades(self) -> None:
        class DownStore:
            def search(self, *args, **kwargs):
                raise ConnectionError("qdrant down")

        with (
            patch("agi_talent_radar.core.embedding.embed_texts", side_effect=_fake_embed_texts),
            patch("agi_talent_radar.core.vector_store.QdrantVectorStore", return_value=DownStore()),
        ):
            result = tool_search_knowledge(self.ctx, {"query": "李四"})
        self.assertEqual(result["hits"], [])
        self.assertIn("暂不可用", result["summary"])


class TestGatedHandlersNoWrite(ChatToolsTestBase):
    def test_handlers_only_return_confirmation(self) -> None:
        cases = [
            (tool_select_person, {"candidates": [{"person_id": "p1", "name": "李四"}]}, "select_person"),
            (tool_propose_add_person, {"name": "王五"}, "propose_add_person"),
            (tool_resolve_fact_conflict, {"fact_id": 1, "chosen_payload": {}}, "resolve_fact_conflict"),
            (tool_ask_clarification, {"question": "哪位？"}, "clarify"),
        ]
        for handler, args, kind in cases:
            result = handler(self.ctx, args)
            self.assertTrue(result["requires_confirmation"])
            self.assertEqual(result["kind"], kind)
        # handler 阶段不产生任何待写入对象
        self.assertEqual(len(self.session.new), 0)
        self.assertEqual(self.session.query(PersonORM).count(), 0)


class TestExecuteGatedAction(ChatToolsTestBase):
    def test_select_person_returns_brief(self) -> None:
        person = _add_person(self.session, "李四", org="清华大学")
        text = execute_gated_action(
            self.session, "select_person", {"candidates": []}, {"choice": person.id}
        )
        self.assertIn("李四", text)
        self.assertIn("清华大学", text)
        missing = execute_gated_action(
            self.session, "select_person", {"candidates": []}, {"choice": "nobody"}
        )
        self.assertIn("不存在", missing)

    def test_propose_add_person_approved_creates_guest(self) -> None:
        text = execute_gated_action(
            self.session,
            "propose_add_person",
            {"name": "王五", "org": "MIT", "direction": "RL", "note": "调查结论"},
            {"approved": True},
        )
        self.assertIn("加入人才库", text)
        person = self.session.query(PersonORM).filter_by(name="王五").one()
        self.assertEqual(person.person_type, "guest")
        self.assertEqual(person.identifiers.get("agent_note"), "调查结论")
        # 重复批准幂等：不重复建人
        execute_gated_action(
            self.session,
            "propose_add_person",
            {"name": "王五", "org": "MIT", "direction": "RL"},
            {"approved": True},
        )
        self.assertEqual(self.session.query(PersonORM).filter_by(name="王五").count(), 1)

    def test_review_then_add_person_reuses_profile_and_keeps_reputation(self) -> None:
        review_payload = {
            "name": "李博杰",
            "org": "北京智源人工智能研究院",
            "items": [
                {
                    "title": "公开争议已经人工确认",
                    "url": "https://example.test/reputation",
                    "sentiment": "negative",
                }
            ],
        }
        review_decision = {"verdicts": [{"index": 0, "action": "confirmed"}]}
        execute_gated_action(
            self.session, "review_reputation", review_payload, review_decision
        )

        add_payload = {
            "name": "李博杰",
            "org": "北京智源人工智能研究院",
            "direction": "多模态大模型",
            "note": "问答调查完成",
        }
        first = execute_gated_action(
            self.session, "propose_add_person", add_payload, {"approved": True}
        )
        second = execute_gated_action(
            self.session, "propose_add_person", add_payload, {"approved": True}
        )

        persons = self.session.query(PersonORM).filter_by(name="李博杰").all()
        self.assertEqual(len(persons), 1)
        person = persons[0]
        self.assertEqual(person.direction, "多模态大模型")
        self.assertEqual(person.identifiers.get("agent_note"), "问答调查完成")
        self.assertEqual(len(person.reputation_reports), 1)
        self.assertEqual(person.reputation_reports[0].level, "red")
        self.assertEqual(person.reputation_reports[0].review_status, "confirmed")
        self.assertIn(f"person_id={person.id}", first)
        self.assertIn(f"person_id={person.id}", second)

    def test_propose_add_person_rejected(self) -> None:
        text = execute_gated_action(
            self.session, "propose_add_person", {"name": "王五"}, {"approved": False}
        )
        self.assertIn("暂不", text)
        self.assertEqual(self.session.query(PersonORM).count(), 0)

    def test_resolve_fact_conflict_approved(self) -> None:
        person = _add_person(self.session, "李四")
        fact_a = ExternalFactORM(
            person_id=person.id, source="aminer", fact_type="scholar",
            payload={"citation_count": 100}, identity_key="k1", verification_status="conflict",
        )
        fact_b = ExternalFactORM(
            person_id=person.id, source="web_search", fact_type="scholar",
            payload={"citation_count": 999}, identity_key="k1", verification_status="conflict",
        )
        self.session.add_all([fact_a, fact_b])
        self.session.commit()

        text = execute_gated_action(
            self.session,
            "resolve_fact_conflict",
            {"fact_id": fact_a.id, "chosen_payload": {"citation_count": 100}, "note": "以 AMiner 为准"},
            {"approved": True},
        )
        self.assertIn("裁定已落库", text)
        self.session.expire_all()
        self.assertEqual(fact_a.verification_status, "confirmed")
        self.assertEqual(fact_a.payload["citation_count"], 100)
        self.assertEqual(fact_a.payload["resolution_note"], "以 AMiner 为准")
        self.assertEqual(fact_b.verification_status, "superseded")
        self.assertIsNotNone(fact_b.superseded_at)

    def test_resolve_fact_conflict_rejected_keeps_status(self) -> None:
        person = _add_person(self.session, "李四")
        fact = ExternalFactORM(
            person_id=person.id, source="aminer", fact_type="scholar",
            payload={}, identity_key="k1", verification_status="conflict",
        )
        self.session.add(fact)
        self.session.commit()
        text = execute_gated_action(
            self.session, "resolve_fact_conflict", {"fact_id": fact.id}, {"approved": False}
        )
        self.assertIn("暂不裁定", text)
        self.assertEqual(fact.verification_status, "conflict")

    def test_clarify_passes_answer_through(self) -> None:
        text = execute_gated_action(self.session, "clarify", {}, {"answer": "张三"})
        self.assertEqual(text, "用户回答：张三")
        by_choice = execute_gated_action(self.session, "clarify", {}, {"choice": "选项A"})
        self.assertEqual(by_choice, "用户回答：选项A")

    def test_review_reputation_mixed_verdicts(self) -> None:
        person = _add_person(self.session, "李四", org="清华大学")
        payload = {
            "person_id": person.id,
            "name": "李四",
            "items": [
                {"title": "李四被质疑数据造假", "url": "http://x/1", "sentiment": "negative", "concern": "只有自媒体来源"},
                {"title": "李四获优秀学生奖", "url": "http://x/2", "sentiment": "positive", "concern": ""},
            ],
        }
        decision = {"verdicts": [{"index": 0, "action": "confirmed"}, {"index": 1, "action": "dismissed"}]}
        text = execute_gated_action(self.session, "review_reputation", payload, decision)
        # 确认的进总结，驳回的明确禁止
        self.assertIn("已确认", text)
        self.assertIn("数据造假", text)
        self.assertIn("严禁", text)
        self.assertIn("优秀学生奖", text)
        report = self.session.query(ReputationReportORM).filter_by(person_id=person.id).one()
        self.assertEqual(report.level, "red")  # 确认的负面 → red
        self.assertEqual(report.review_status, "confirmed")
        self.assertEqual(report.events[0]["review_status"], "confirmed")
        self.assertEqual(report.events[1]["review_status"], "dismissed")

    def test_review_reputation_all_dismissed_is_green(self) -> None:
        payload = {
            "name": "库外人",
            "org": "某实验室",
            "items": [{"title": "库外人涉争议", "url": "http://x/3", "sentiment": "negative"}],
        }
        decision = {"verdicts": [{"index": 0, "action": "dismissed"}]}
        text = execute_gated_action(self.session, "review_reputation", payload, decision)
        self.assertIn("已驳回", text)
        person = self.session.query(PersonORM).filter_by(name="库外人").one()
        self.assertEqual(person.person_type, "guest")  # 库外人物自动建档
        report = self.session.query(ReputationReportORM).filter_by(person_id=person.id).one()
        self.assertEqual(report.level, "green")

    def test_review_reputation_requires_name(self) -> None:
        text = execute_gated_action(
            self.session, "review_reputation", {"items": [{"title": "x"}]}, {"verdicts": []}
        )
        self.assertIn("缺少人物姓名", text)


class TestSearchPersonsCitationMeta(ChatToolsTestBase):
    def test_citation_meta_carries_person_detail(self) -> None:
        person = _add_person(self.session, "李四", org="清华大学", direction="NLP")
        _add_evaluation(self.session, person.id, "c-李四", 90)
        result = tool_search_persons(self.ctx, {"name": "李四"})
        citation_id = result["persons"][0]["citation_id"]
        source = next(s for s in self.ctx.sources if s["id"] == citation_id)
        meta = source["meta"]
        self.assertEqual(meta["person_id"], person.id)
        self.assertEqual(meta["org"], "清华大学")
        self.assertEqual(meta["direction"], "NLP")
        self.assertEqual(meta["overall_score"], 90)

    def test_citation_meta_without_evaluation(self) -> None:
        _add_person(self.session, "张三")
        result = tool_search_persons(self.ctx, {"name": "张三"})
        source = self.ctx.sources[0]
        self.assertEqual(source["meta"]["person_id"], "p-张三")
        self.assertNotIn("overall_score", source["meta"])

    def test_profile_evaluation_versions_citations_carry_meta(self) -> None:
        # 三个人物工具的引用都必须带 person meta，前端才能渲染跳转卡片
        person = _add_person(self.session, "李四", org="清华大学")
        _add_evaluation(self.session, person.id, "c-李四", 88)
        result = tool_get_person_profile(self.ctx, {"person_id": person.id})
        meta = self.ctx.sources[-1]["meta"]
        self.assertEqual(meta["person_id"], person.id)
        self.assertEqual(meta["overall_score"], 88)
        self.assertEqual(result["citation_id"], self.ctx.sources[-1]["id"])
        tool_get_person_evaluation(self.ctx, {"person_id": person.id})
        self.assertEqual(self.ctx.sources[-1]["meta"]["person_id"], person.id)
        tool_get_resume_versions(self.ctx, {"person_id": person.id})
        self.assertEqual(self.ctx.sources[-1]["meta"]["person_id"], person.id)


if __name__ == "__main__":
    unittest.main()
