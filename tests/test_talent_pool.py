from __future__ import annotations

import unittest
from unittest.mock import patch

from agi_talent_radar.core.db.orm import Base, EvaluationORM, PersonORM, ReputationReportORM
from agi_talent_radar.core.persons import get_person_detail, list_persons


def _make_person(person_id: str, name: str, org: str = "", direction: str = "", person_type: str = "guest") -> PersonORM:
    return PersonORM(
        id=person_id,
        name=name,
        org=org,
        direction=direction,
        fingerprint=f"fp-{person_id}",
        person_type=person_type,
    )


class PersonQueryTest(unittest.TestCase):
    def setUp(self) -> None:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)

    def tearDown(self) -> None:
        self.engine.dispose()

    def _seed(self) -> None:
        with self.Session() as session:
            p1 = _make_person("p1", "张三", "智谱", "Agent", "guest")
            p2 = _make_person("p2", "李四", "北航", "优化", "student")
            p1.reputation_reports = [ReputationReportORM(level="red", events=[], review_status="pending")]
            p2.reputation_reports = [ReputationReportORM(level="green", events=[], review_status="confirmed")]
            session.add_all([p1, p2])
            session.commit()

    def test_list_persons_returns_all(self) -> None:
        self._seed()
        with self.Session() as session:
            rows = list_persons(session)
            self.assertEqual(len(rows), 2)

    def test_list_persons_filter_by_type(self) -> None:
        self._seed()
        with self.Session() as session:
            rows = list_persons(session, person_type="guest")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].name, "张三")

    def test_list_persons_filter_by_name(self) -> None:
        self._seed()
        with self.Session() as session:
            rows = list_persons(session, name="李")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].name, "李四")

    def test_list_persons_filter_by_reputation_level(self) -> None:
        self._seed()
        with self.Session() as session:
            rows = list_persons(session, level="red")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].name, "张三")

    def test_get_person_detail_includes_relationships(self) -> None:
        self._seed()
        with self.Session() as session:
            person = get_person_detail(session, "p1")
            self.assertIsNotNone(person)
            self.assertEqual(person.name, "张三")
            self.assertEqual(len(person.reputation_reports), 1)
            self.assertEqual(person.reputation_reports[0].level, "red")

    def test_get_person_detail_missing_returns_none(self) -> None:
        with self.Session() as session:
            self.assertIsNone(get_person_detail(session, "不存在"))


class TalentPoolRouteTest(unittest.TestCase):
    """验证 person 路由 + 复核端点的端到端流程。"""

    def setUp(self) -> None:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)

        # 让 web 层用这个内存库
        import agi_talent_radar.core.db.runtime as runtime

        self._orig_get_engine = runtime.get_engine
        runtime._ENGINES["memory-test"] = self.engine
        runtime.get_engine = lambda *a, **k: self.engine
        self._runtime = runtime

        # 阶段 8 之后路由受鉴权保护；路由测试统一放行。
        self._auth_patch = patch(
            "agi_talent_radar.web.auth.is_authenticated",
            return_value=True,
        )
        self._auth_patch.start()

    def tearDown(self) -> None:
        self._auth_patch.stop()
        self._runtime.get_engine = self._orig_get_engine
        self.engine.dispose()

    def _seed_person_with_report(self) -> int:
        with self.Session() as session:
            person = _make_person("px", "王五", "某公司", person_type="guest")
            person.reputation_reports = [ReputationReportORM(level="yellow", events=[{"category": "项目争议"}], review_status="pending")]
            session.add(person)
            session.commit()
            return person.reputation_reports[0].id

    def test_list_persons_route(self) -> None:
        self._seed_person_with_report()
        from agi_talent_radar.web.workbench import create_app

        client = create_app().test_client()
        resp = client.get("/api/persons")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["name"], "王五")
        self.assertEqual(data[0]["reputation_level"], "yellow")

    def test_get_person_detail_route(self) -> None:
        self._seed_person_with_report()
        from agi_talent_radar.web.workbench import create_app

        client = create_app().test_client()
        resp = client.get("/api/persons/px")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["name"], "王五")
        self.assertEqual(len(data["reputation_reports"]), 1)
        self.assertEqual(data["reputation_reports"][0]["level"], "yellow")

    def test_get_person_reputation_route(self) -> None:
        self._seed_person_with_report()
        from agi_talent_radar.web.workbench import create_app

        client = create_app().test_client()
        resp = client.get("/api/persons/px/reputation")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["review_status"], "pending")

    def test_review_reputation_route_confirms_report(self) -> None:
        report_id = self._seed_person_with_report()
        from agi_talent_radar.web.workbench import create_app

        client = create_app().test_client()
        resp = client.post(
            f"/api/reputation/{report_id}/review",
            json={"action": "confirmed", "reviewer": "hr", "note": "属实"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["review_status"], "confirmed")
        self.assertEqual(data["reviewer"], "hr")

    def test_review_reputation_route_rejects_invalid_action(self) -> None:
        report_id = self._seed_person_with_report()
        from agi_talent_radar.web.workbench import create_app

        client = create_app().test_client()
        resp = client.post(
            f"/api/reputation/{report_id}/review",
            json={"action": "maybe"},
        )
        self.assertEqual(resp.status_code, 400)
    def test_create_person_route_adds_guest(self) -> None:
        from agi_talent_radar.web.workbench import create_app

        client = create_app().test_client()
        resp = client.post(
            "/api/persons",
            json={"name": "赵六", "org": "某实验室", "direction": "Agent"},
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.get_json()
        self.assertEqual(data["name"], "赵六")
        self.assertEqual(data["person_type"], "guest")

        # 创建后能在人才库列表中查到，且相同身份重复创建归并到同一档
        resp2 = client.post(
            "/api/persons",
            json={"name": "赵六", "org": "某实验室", "direction": "Agent"},
        )
        self.assertEqual(resp2.status_code, 201)
        self.assertEqual(resp2.get_json()["id"], data["id"])
        listing = client.get("/api/persons").get_json()
        self.assertEqual(len([p for p in listing if p["name"] == "赵六"]), 1)

    def test_create_person_route_requires_name(self) -> None:
        from agi_talent_radar.web.workbench import create_app

        client = create_app().test_client()
        resp = client.post("/api/persons", json={"org": "某实验室"})
        self.assertEqual(resp.status_code, 400)


if __name__ == "__main__":
    unittest.main()
