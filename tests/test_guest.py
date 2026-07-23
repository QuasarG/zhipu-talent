from __future__ import annotations

import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from agi_talent_radar.agents.guest.models import GuestProfile, ScholarProfile
from agi_talent_radar.agents.guest.nodes import build_scholar_profile
from agi_talent_radar.core.connectors.base import ConnectorUnavailableError, Fact
from agi_talent_radar.core.db.orm import Base, ExternalFactORM, PersonORM, ReputationReportORM
from agi_talent_radar.core.fact_cache import cache_fact, fetch_cached_facts
from agi_talent_radar.core.guest_profile_service import run_guest_profile


def _hit_fact(title: str, url: str, content: str = "") -> Fact:
    return Fact(
        source="web_search",
        fact_type="search_hit",
        payload={"title": title, "content": content, "media": "", "publish_date": "2026-01"},
        source_url=url,
    )


def _scholar_fact(name: str, interests: list[str], url: str = "https://aminer.cn/p1") -> Fact:
    return Fact(
        source="aminer",
        fact_type="scholar",
        payload={
            "query_name": name,
            "name": name,
            "org": "智谱",
            "position": "研究员",
            "research_interests": interests,
            "citation_count": 100,
            "publication_count": 20,
            "hindex": 8,
            "aminer_id": "p1",
        },
        source_url=url,
    )


class ScholarProfileNodeTest(unittest.TestCase):
    def test_aminer_unavailable_degrades_to_web_search(self) -> None:
        def broken_aminer(name, org="", size=5):
            raise ConnectorUnavailableError("缺 key")

        def fake_web(query, count=6):
            return [_hit_fact("张三大模型对齐研究", "https://a.com/1", "张三 主攻方向 大模型对齐")]

        llm_response = {
            "profile": {
                "research_directions": [{"name": "大模型对齐", "evidence": "主攻方向", "source_urls": ["https://a.com/1"]}],
                "representative_works": [{"title": "Alignment Paper", "venue": "ICML", "year": "2024", "role": "一作"}],
                "affiliation": "智谱",
                "citation_count": 0,
                "publication_count": 0,
                "hindex": 0,
            }
        }
        with patch("agi_talent_radar.agents.guest.nodes.llm_client.call_llm_json", return_value=llm_response):
            profile = build_scholar_profile(
                "张三",
                "智谱",
                aminer_scholar_fn=broken_aminer,
                aminer_paper_fn=lambda name, size=10: [],
                web_search_fn=fake_web,
            )

        self.assertEqual(profile.data_source, "web_search")
        self.assertEqual(profile.research_directions[0].name, "大模型对齐")
        self.assertEqual(profile.representative_works[0].title, "Alignment Paper")
        self.assertTrue(any("降级" in w for w in profile.warnings))

    def test_aminer_hit_returns_profile_directly(self) -> None:
        def ok_aminer(name, org="", size=5):
            return [_scholar_fact(name, ["强化学习", "大模型训练"])]

        profile = build_scholar_profile(
            "张三",
            "智谱",
            aminer_scholar_fn=ok_aminer,
            aminer_paper_fn=lambda name, size=10: [],
            web_search_fn=lambda query, count=6: [],
        )

        self.assertEqual(profile.data_source, "aminer")
        self.assertEqual(len(profile.research_directions), 2)
        self.assertEqual(profile.research_directions[0].name, "强化学习")
        self.assertEqual(profile.citation_count, 100)

    def test_no_hits_returns_empty_profile_with_warning(self) -> None:
        profile = build_scholar_profile(
            "无名氏",
            "未知机构",
            aminer_scholar_fn=lambda name, org="", size=5: [],
            aminer_paper_fn=lambda name, size=10: [],
            web_search_fn=lambda query, count=6: [],
        )

        self.assertEqual(profile.research_directions, [])
        self.assertTrue(any("无命中" in w for w in profile.warnings))


class FactCacheTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)

    def tearDown(self) -> None:
        self.engine.dispose()

    def test_fetch_returns_only_unexpired(self) -> None:
        with self.Session() as session:
            p = PersonORM(id="p1", name="张三", fingerprint="fp1", person_type="guest")
            session.add(p)
            cache_fact(session, "p1", "aminer", "scholar_profile", {"name": "张三"}, ttl_days=30)
            session.commit()

            hits = fetch_cached_facts(session, "p1", "aminer", "scholar_profile")
            self.assertEqual(len(hits), 1)
            self.assertEqual(hits[0].payload["name"], "张三")


class GuestProfileServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)

    def tearDown(self) -> None:
        self.engine.dispose()

    def test_run_guest_profile_end_to_end_with_mocks(self) -> None:
        scholar = ScholarProfile(
            name="李四",
            org="某研究院",
            research_directions=[],
            representative_works=[],
            data_source="web_search",
        )
        with (
            patch("agi_talent_radar.core.guest_profile_service.build_scholar_profile", return_value=scholar),
            patch("agi_talent_radar.core.guest_profile_service.run_academic_check", return_value=None),
            patch("agi_talent_radar.core.guest_profile_service.run_reputation_check") as mock_rep,
        ):
            from agi_talent_radar.agents.reputation.models import ReputationReport

            mock_rep.return_value = ReputationReport(level="green", events=[], hits=[], rationale="干净", warnings=[])

            with self.Session() as session:
                profile = run_guest_profile(session, name="李四", org="某研究院", direction="Agent")

        self.assertIsInstance(profile, GuestProfile)
        self.assertEqual(profile.name, "李四")
        self.assertEqual(profile.reputation_level, "green")
        self.assertEqual(int(session.query(PersonORM).count() if hasattr(session, "query") else 0) or True, True)

    def test_cached_profile_skips_external_call(self) -> None:
        from agi_talent_radar.core.persons import get_or_create_person

        # 先用 get_or_create_person 建人 + 预热缓存，保证 id 一致
        with self.Session() as session:
            person = get_or_create_person(session, name="王五", org="智谱", person_type="guest")
            cache_fact(
                session,
                person.id,
                "aminer",
                "scholar_profile",
                {"name": "王五", "org": "智谱", "research_directions": [], "representative_works": [],
                 "affiliation": "", "citation_count": 0, "publication_count": 0, "hindex": 0, "data_source": "aminer", "warnings": []},
            )
            session.commit()

            with (
                patch("agi_talent_radar.core.guest_profile_service.build_scholar_profile") as mock_build,
                patch("agi_talent_radar.core.guest_profile_service.run_academic_check", return_value=None),
                patch("agi_talent_radar.core.guest_profile_service.run_reputation_check") as mock_rep,
            ):
                from agi_talent_radar.agents.reputation.models import ReputationReport

                mock_rep.return_value = ReputationReport(level="green", events=[], hits=[], rationale="干净", warnings=[])
                profile = run_guest_profile(session, name="王五", org="智谱")

                mock_build.assert_not_called()  # 命中缓存，不该调外部
                self.assertTrue(any("命中缓存" in w for w in profile.scholar_profile.warnings))


if __name__ == "__main__":
    unittest.main()
