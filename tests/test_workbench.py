from __future__ import annotations

import io
import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from agi_talent_radar.web.workbench import create_app


ROOT = Path(__file__).resolve().parents[1]


class WorkbenchTest(unittest.TestCase):
    def setUp(self) -> None:
        self.app = create_app().test_client()

    def _parse_sse(self, response) -> list[dict]:
        events: list[dict] = []
        for line in response.data.decode("utf-8").splitlines():
            if line.startswith("data: "):
                payload = line[6:]
                if payload == "[DONE]":
                    events.append({"done": True})
                else:
                    events.append(json.loads(payload))
        return events

    def test_index_loads(self) -> None:
        response = self.app.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("AGI Talent Radar", response.get_data(as_text=True))

    def test_candidates_group_returns_list(self) -> None:
        response = self.app.get("/api/candidates?group=pending")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIsInstance(data, list)

    def test_candidates_group_rejects_invalid_group(self) -> None:
        response = self.app.get("/api/candidates?group=invalid")
        self.assertEqual(response.status_code, 400)

    @patch("agi_talent_radar.web.workbench.run_import_agent_stream")
    def test_upload_jsonl_sse_stream(self, mock_stream) -> None:
        classification = MagicMock()
        classification.id = "candidate_01"
        classification.name = "候选人01"
        classification.category = "研究探索型"
        classification.level = "A"
        classification.confidence = 0.92
        classification.reason = "方向契合度高"
        mock_stream.return_value = iter([classification])
        content = (ROOT / "10_ai_phd_resumes.jsonl").read_bytes()
        response = self.app.post(
            "/api/import-file",
            data={"file": (io.BytesIO(content), "resumes.jsonl")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/event-stream", response.content_type)
        events = self._parse_sse(response)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["type"], "candidate")
        self.assertEqual(events[0]["candidate"]["id"], "candidate_01")
        self.assertEqual(events[0]["index"], 1)
        self.assertEqual(events[0]["total"], 1)
        self.assertEqual(events[1]["type"], "done")

    @patch("agi_talent_radar.web.workbench.run_candidate_stream")
    @patch("agi_talent_radar.core.database.get_candidate_with_latest_evaluation")
    def test_evaluate_candidate(self, mock_get, mock_run_stream) -> None:
        self._seed_candidate("candidate_01")
        mock_row = MagicMock()
        mock_row.id = "candidate_01"
        mock_row.name = "候选人01"
        mock_row.target_role = "大模型研究员"
        mock_row.stage = "博士一年级"
        mock_row.raw_text = ""
        mock_row.education = "[]"
        mock_row.directions = "[]"
        mock_row.projects = "[]"
        mock_row.publications = "[]"
        mock_row.skills = "[]"
        mock_row.screening_tags = "[]"
        mock_get.return_value = (mock_row, None)

        from agi_talent_radar.core.models import CandidateEvaluation

        evaluation = CandidateEvaluation(
            id="candidate_01",
            name="候选人01",
            target_role="大模型研究员",
            stage="博士一年级",
            overall_score=75,
            level="A",
            tier="强烈建议沟通",
            one_liner="高潜候选人",
            core_strengths=[],
            potential_risks=[],
            interview_questions=[],
            cultivation_direction=[],
            dimension_scores=[],
            evidence=[],
        )
        mock_run_stream.return_value = iter([
            {"type": "node", "node": "normalizer", "label": "标准化", "status": "done", "message": "标准化完成"},
            {"type": "result", "result": evaluation.model_dump()},
        ])

        response = self.app.post("/api/candidates/candidate_01/evaluate")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/event-stream", response.content_type)
        events = self._parse_sse(response)
        self.assertEqual(events[0]["type"], "node")
        self.assertEqual(events[-1]["type"], "result")
        self.assertEqual(events[-1]["result"]["overall_score"], 75)

    def _seed_candidate(self, candidate_id: str) -> None:
        try:
            from agi_talent_radar.core.database import CandidateORM, get_session

            with get_session() as session:
                if session.query(CandidateORM).filter_by(id=candidate_id).first():
                    return
                session.add(CandidateORM(id=candidate_id, name="候选人", group="pending"))
                session.commit()
        except Exception:
            pass

    @patch("agi_talent_radar.core.database.move_candidate_group")
    @patch("agi_talent_radar.core.database.get_candidate_with_latest_evaluation")
    def test_move_candidate(self, mock_get, mock_move) -> None:
        mock_row = MagicMock()
        mock_row.id = "candidate_01"
        mock_row.group = "shortlisted"
        mock_get.return_value = (mock_row, None)
        mock_move.return_value = mock_row

        response = self.app.post(
            "/api/candidates/candidate_01/move",
            json={"group": "shortlisted"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["group"], "shortlisted")


if __name__ == "__main__":
    unittest.main()
