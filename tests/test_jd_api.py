"""JD 池 API 契约测试：CRUD / 可选 spec 起草 / 激活 / active JD 列表。

DATABASE_URL 在 setUpClass 才切内存库（不在 import 时改）：模块级改 env 会污染
按字母序更晚 import 的同类测试模块（它们 import 时捕获的是被我改过的值）。
"""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from agi_talent_radar.web.workbench import create_app
from agi_talent_radar.core.db.runtime import get_engine
from agi_talent_radar.core.db.orm import Base
from tests.track_fixtures import make_spec


class JdApiTest(unittest.TestCase):
    _saved_url: str | None = None

    @classmethod
    def setUpClass(cls) -> None:
        cls._saved_url = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = "sqlite://"
        Base.metadata.create_all(get_engine())

    @classmethod
    def tearDownClass(cls) -> None:
        if cls._saved_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = cls._saved_url

    def setUp(self) -> None:
        self._auth = patch("agi_talent_radar.web.auth.is_authenticated", return_value=True)
        self._auth.start()
        self.client = create_app().test_client()
        self._ids: list[str] = []

    def tearDown(self) -> None:
        for jd_id in self._ids:
            self.client.delete(f"/api/jds/{jd_id}")
        self._auth.stop()

    def _create(self) -> str:
        resp = self.client.post("/api/jds", json={"title": "多模态生成", "team": "多模态团队", "raw_text": "熟悉 diffusion……"})
        self.assertEqual(resp.status_code, 201)
        jd_id = resp.get_json()["id"]
        self._ids.append(jd_id)
        return jd_id

    def test_create_validates_required_fields(self) -> None:
        resp = self.client.post("/api/jds", json={"title": "", "raw_text": ""})
        self.assertEqual(resp.status_code, 400)

    def test_parse_returns_title_and_team(self) -> None:
        with patch(
            "agi_talent_radar.agents.jd_spec.parse_jd_brief",
            return_value={"title": "多模态生成算法研究", "team": "智谱多模态大模型团队"},
        ):
            resp = self.client.post("/api/jds/parse", json={"text": "【团队介绍】智谱多模态……"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["team"], "智谱多模态大模型团队")
        self.assertEqual(self.client.post("/api/jds/parse", json={"text": ""}).status_code, 400)

    def test_raw_jd_can_activate_without_legacy_spec(self) -> None:
        jd_id = self._create()

        resp = self.client.post(f"/api/jds/{jd_id}/status", json={"status": "active"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["status"], "active")

        tracks = self.client.get("/api/tracks/active").get_json()
        self.assertEqual(tracks, [{"key": jd_id, "label": "多模态生成"}])

    def test_legacy_spec_can_still_be_drafted(self) -> None:
        jd_id = self._create()

        spec = make_spec("multimodal_gen", "多模态生成", keywords=("diffusion", "蒸馏"))
        with patch("agi_talent_radar.agents.jd_spec.draft_track_spec", return_value=spec):
            resp = self.client.post(f"/api/jds/{jd_id}/generate-spec")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["spec"]["key"], "multimodal_gen")
        self.assertEqual(body["spec_version"], 1)

        self.assertEqual(body["track_key"], "multimodal_gen")

    def test_edit_raw_text_falls_back_to_draft(self) -> None:
        jd_id = self._create()
        spec = make_spec("multimodal_gen", "多模态生成")
        with patch("agi_talent_radar.agents.jd_spec.draft_track_spec", return_value=spec):
            self.client.post(f"/api/jds/{jd_id}/generate-spec")
        self.client.post(f"/api/jds/{jd_id}/status", json={"status": "active"})

        resp = self.client.patch(f"/api/jds/{jd_id}", json={"title": "多模态生成", "team": "", "raw_text": "改了原文"})
        self.assertEqual(resp.get_json()["status"], "draft")

    def test_delete_removes_from_active_tracks(self) -> None:
        jd_id = self._create()
        spec = make_spec("multimodal_gen", "多模态生成")
        with patch("agi_talent_radar.agents.jd_spec.draft_track_spec", return_value=spec):
            self.client.post(f"/api/jds/{jd_id}/generate-spec")
        self.client.post(f"/api/jds/{jd_id}/status", json={"status": "active"})

        self.client.delete(f"/api/jds/{jd_id}")
        self._ids.remove(jd_id)
        self.assertEqual(self.client.get("/api/tracks/active").get_json(), [])


if __name__ == "__main__":
    unittest.main()
