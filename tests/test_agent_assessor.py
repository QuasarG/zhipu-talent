from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agi_talent_radar.agents.job_fit.agent_assessor import MaterialsContext, _extract_text_layer


class MaterialsContextTests(unittest.TestCase):
    def test_jsonl_is_read_as_source_material(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "resume.jsonl"
            source.write_text('{"name":"测试候选人","skills":["Python"]}\n', encoding="utf-8")
            context = MaterialsContext(directory, {"resume.jsonl"})

            text = _extract_text_layer(context, "resume.jsonl")

        self.assertIn("测试候选人", text)
        self.assertIn("Python", text)

    def test_allowed_files_cannot_escape_candidate_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "resume.txt"
            source.write_text("safe", encoding="utf-8")
            context = MaterialsContext(directory, {"resume.txt"})

            self.assertEqual(context.resolve("resume.txt"), str(source))
            self.assertIsNone(context.resolve("../resume.txt"))
            self.assertIsNone(context.resolve("other.txt"))


if __name__ == "__main__":
    unittest.main()
