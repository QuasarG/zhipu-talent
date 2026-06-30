from __future__ import annotations

import io
import unittest
from pathlib import Path

from agi_talent_radar.web.workbench import create_app


ROOT = Path(__file__).resolve().parents[1]


class WorkbenchTest(unittest.TestCase):
    def setUp(self) -> None:
        self.app = create_app().test_client()

    def test_index_loads(self) -> None:
        response = self.app.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("AGI Talent Radar", response.get_data(as_text=True))

    def test_evaluations_api_returns_batch_result(self) -> None:
        response = self.app.get("/api/evaluations")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(len(data["evaluations"]), 10)
        self.assertIn("强烈建议沟通", data["tiers"])

    def test_upload_jsonl_runs_batch(self) -> None:
        content = (ROOT / "10_ai_phd_resumes.jsonl").read_bytes()
        response = self.app.post(
            "/api/evaluate-upload",
            data={"file": (io.BytesIO(content), "resumes.jsonl")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(len(data["evaluations"]), 10)


if __name__ == "__main__":
    unittest.main()
