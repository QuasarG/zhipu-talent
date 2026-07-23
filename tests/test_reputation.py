from __future__ import annotations

import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from agi_talent_radar.agents.reputation.models import PersonIdentity, ReputationEvent, ReputationReport, SearchHit
from agi_talent_radar.agents.reputation.nodes import (
    build_queries,
    classify_events,
    collect_hits,
    grade_risk,
    run_reputation_check,
)
from agi_talent_radar.core.connectors.base import ConnectorUnavailableError, Fact
from agi_talent_radar.core.db.orm import Base, ExternalFactORM, PersonORM, ReputationReportORM
from agi_talent_radar.core.reputation_service import review_reputation_report, run_guest_check


def _fact(title: str, url: str, content: str = "") -> Fact:
    return Fact(
        source="web_search",
        fact_type="search_hit",
        payload={"title": title, "content": content, "media": "", "publish_date": "2026-01"},
        source_url=url,
    )


class ReputationChainTest(unittest.TestCase):
    def test_build_queries_strips_empty_org_and_keeps_domains(self) -> None:
        queries = build_queries(PersonIdentity(name="张三", org=""))
        self.assertEqual(len(queries), 7)
        self.assertIn(("张三 抄袭", ""), queries)
        self.assertIn(("张三", "pubpeer.com"), queries)
        self.assertIn(("张三", "retractionwatch.com"), queries)

    def test_collect_hits_dedups_and_degrades_on_failure(self) -> None:
        def fake_search(query, count=8, domain_filter=""):
            if "学术不端" in query:
                raise ConnectorUnavailableError("搜索服务不可用")
            return [_fact("新闻 A", "https://a.com/1"), _fact("新闻 A 转载", "https://a.com/1")]

        hits, warnings = collect_hits(PersonIdentity(name="张三"), search_fn=fake_search)

        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].url, "https://a.com/1")
        self.assertEqual(len(warnings), 1)

    def test_classify_events_filters_false_positive_and_unknown_urls(self) -> None:
        hits = [SearchHit(query="q", title="t", content="c", url="https://a.com/1")]
        llm_response = {
            "events": [
                {"category": "学术不端", "identity_match": "confirmed", "summary": "撤稿事件", "status": "已有结论", "source_urls": ["https://a.com/1"], "publish_date": "2026-01"},
                {"category": "误报", "identity_match": "confirmed", "summary": "中性报道", "source_urls": ["https://a.com/1"]},
                {"category": "抄袭争议", "identity_match": "rejected", "summary": "同名者", "source_urls": ["https://a.com/1"]},
                {"category": "学术不端", "identity_match": "confirmed", "summary": "编造来源", "source_urls": ["https://fake.example.com"]},
            ]
        }
        with patch("agi_talent_radar.agents.reputation.nodes.llm_client.call_llm_json", return_value=llm_response):
            events = classify_events(PersonIdentity(name="张三"), hits)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].category, "学术不端")

    def test_grade_risk_levels(self) -> None:
        red_event = ReputationEvent(category="抄袭争议", identity_match="confirmed", summary="x", source_urls=["https://a.com/1"])
        cleared_event = ReputationEvent(category="抄袭争议", identity_match="confirmed", summary="x", status="已澄清", source_urls=["https://a.com/1"])
        probable_event = ReputationEvent(category="学术不端", identity_match="probable", summary="x", source_urls=["https://a.com/1"])
        minor_event = ReputationEvent(category="公开冲突", identity_match="confirmed", summary="x", source_urls=["https://a.com/1"])

        self.assertEqual(grade_risk([red_event])[0], "red")
        self.assertEqual(grade_risk([cleared_event])[0], "green")
        self.assertEqual(grade_risk([probable_event])[0], "yellow")
        self.assertEqual(grade_risk([minor_event])[0], "yellow")
        self.assertEqual(grade_risk([])[0], "green")

    def test_run_reputation_check_end_to_end_with_mocks(self) -> None:
        def fake_search(query, count=8, domain_filter=""):
            return [_fact("某教授论文被撤稿", "https://a.com/1", "张三 某大学 论文 撤稿")]

        llm_response = {
            "events": [
                {"category": "学术不端", "identity_match": "confirmed", "summary": "论文被撤稿", "status": "已有结论", "source_urls": ["https://a.com/1"], "publish_date": "2026-01"}
            ]
        }
        with patch("agi_talent_radar.agents.reputation.nodes.llm_client.call_llm_json", return_value=llm_response):
            report = run_reputation_check(PersonIdentity(name="张三", org="某大学"), search_fn=fake_search)

        self.assertEqual(report.level, "red")
        self.assertEqual(len(report.hits), 1)
        self.assertEqual(report.events[0].source_urls, ["https://a.com/1"])


class GuestCheckServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)

    def tearDown(self) -> None:
        self.engine.dispose()

    def _stub_report(self, level: str) -> ReputationReport:
        events = []
        if level != "green":
            events = [ReputationEvent(category="抄袭争议", identity_match="confirmed", summary="争议", source_urls=["https://a.com/1"])]
        return ReputationReport(
            level=level,
            events=events,
            hits=[SearchHit(query="q", title="t", content="c", url="https://a.com/1")],
            rationale="测试",
        )

    def test_guest_check_persists_report_and_merges_person(self) -> None:
        with patch("agi_talent_radar.core.reputation_service.run_reputation_check", return_value=self._stub_report("red")):
            with self.Session() as session:
                first = run_guest_check(session, name="李四", org="某研究院", direction="大模型安全")
                second = run_guest_check(session, name="李四", org="某研究院", direction="大模型安全")

                self.assertEqual(first["person_id"], second["person_id"])
                self.assertEqual(first["level"], "red")
                self.assertEqual(first["review_status"], "pending")
                self.assertEqual(int(session.scalar(select(func.count()).select_from(PersonORM))), 1)
                self.assertEqual(int(session.scalar(select(func.count()).select_from(ExternalFactORM))), 2)

                reviewed = review_reputation_report(session, first["report_id"], "confirmed", reviewer="hr", note="属实")
                self.assertEqual(reviewed.review_status, "confirmed")
                self.assertEqual(reviewed.reviewer, "hr")

    def test_green_report_auto_confirmed(self) -> None:
        with patch("agi_talent_radar.core.reputation_service.run_reputation_check", return_value=self._stub_report("green")):
            with self.Session() as session:
                result = run_guest_check(session, name="王五")
                self.assertEqual(result["review_status"], "confirmed")
                self.assertEqual(int(session.scalar(select(func.count()).select_from(ReputationReportORM))), 1)


if __name__ == "__main__":
    unittest.main()
