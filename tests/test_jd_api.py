"""JD 池新契约：入池生成岗位卡、显式选择、补充要求与普通归档。"""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from agi_talent_radar.agents.interview_admission.contracts import AssessmentCard
from agi_talent_radar.core.db.orm import Base
from agi_talent_radar.core.db.runtime import get_engine
from agi_talent_radar.web.workbench import create_app


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
        with patch(
            "agi_talent_radar.agents.interview_admission.generate_assessment_card",
            return_value=_card("建设高质量多模态生成模型与评测交付体系"),
        ):
            response = self.client.post(
                "/api/jds",
                json={"title": "多模态生成", "team": "多模态团队", "raw_text": "负责生成模型训练与评测"},
            )
        self.assertEqual(response.status_code, 201, response.get_json())
        body = response.get_json()
        self.assertEqual(body["card_status"], "ready")
        self.assertNotIn("status", body)
        self._ids.append(body["id"])
        return body["id"]

    def test_create_validates_required_fields(self) -> None:
        self.assertEqual(self.client.post("/api/jds", json={"title": "", "raw_text": ""}).status_code, 400)

    def test_parse_returns_title_and_team(self) -> None:
        with patch(
            "agi_talent_radar.agents.jd_spec.parse_jd_brief",
            return_value={"title": "多模态生成算法研究", "team": "智谱多模态大模型团队"},
        ):
            response = self.client.post("/api/jds/parse", json={"text": "【团队介绍】智谱多模态……"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["team"], "智谱多模态大模型团队")

    def test_ready_jd_is_selectable_without_activation(self) -> None:
        jd_id = self._create()
        self.assertEqual(self.client.get("/api/tracks/active").get_json(), [{"key": jd_id, "label": "多模态生成"}])

    def test_supplements_regenerate_card_and_accumulate_as_current_list(self) -> None:
        jd_id = self._create()
        with patch(
            "agi_talent_radar.services.interview_assessment_service.generate_assessment_card",
            return_value=_card("建设更新后的多模态模型训练与评测体系"),
        ):
            response = self.client.post(
                f"/api/jds/{jd_id}/assessment-card",
                json={"supplements": ["重点关注复杂工具调用", "重视评测闭环"]},
            )
        body = response.get_json()
        self.assertEqual(response.status_code, 200, body)
        self.assertEqual(body["supplements"], ["重点关注复杂工具调用", "重视评测闭环"])
        self.assertEqual(body["assessment_card"]["role_summary"], "建设更新后的多模态模型训练与评测体系")

    def test_edit_and_card_replacement_are_one_visible_operation(self) -> None:
        jd_id = self._create()
        with patch(
            "agi_talent_radar.agents.interview_admission.generate_assessment_card",
            return_value=_card("建设修改后的智能体研发评测与交付体系"),
        ):
            response = self.client.patch(
                f"/api/jds/{jd_id}",
                json={"title": "Agent 研发", "team": "Agent 团队", "raw_text": "负责 Agent 系统", "supplements": []},
            )
        body = response.get_json()
        self.assertEqual(response.status_code, 200, body)
        self.assertEqual(body["title"], "Agent 研发")
        self.assertEqual(body["assessment_card"]["role_summary"], "建设修改后的智能体研发评测与交付体系")

    def test_archive_only_controls_default_selection_visibility(self) -> None:
        jd_id = self._create()
        response = self.client.post(f"/api/jds/{jd_id}/status", json={"status": "archived"})
        self.assertTrue(response.get_json()["archived"])
        self.assertEqual(self.client.get("/api/tracks/active").get_json(), [])
        response = self.client.post(f"/api/jds/{jd_id}/status", json={"status": "draft"})
        self.assertFalse(response.get_json()["archived"])


def _card(summary: str) -> AssessmentCard:
    return AssessmentCard.model_validate(
        {
            "role_summary": summary,
            "core_tasks": [
                _task("model_training", "生成模型训练", "primary"),
                _task("quality_evaluation", "模型质量评测", "major"),
                _task("engineering_delivery", "工程交付", "supporting"),
            ],
            "background_evidence_guidance": "学历和专业只辅助理解理论基础。",
            "excluded_requirements": [],
        }
    )


def _task(task_id: str, title: str, importance: str) -> dict:
    return {
        "id": task_id,
        "title": title,
        "description": f"围绕{title}完成方案设计、实现、验证与交付。",
        "importance": importance,
        "evaluation_focus": "结合项目难度、本人贡献、技术判断和结果评价。",
        "anchors": {
            "level_2": "实际参与并完成边界清晰的局部工作。",
            "level_3": "能够独立完成核心任务并解决关键问题。",
            "level_4": "复杂约束下成熟交付并沉淀通用能力。",
        },
    }


if __name__ == "__main__":
    unittest.main()
