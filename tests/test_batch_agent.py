from __future__ import annotations

import unittest
from pathlib import Path

from agi_talent_radar.core.io import load_resumes
from agi_talent_radar.core.runner import run_batch, run_candidate


ROOT = Path(__file__).resolve().parents[1]


class BatchAgentTest(unittest.TestCase):
    def test_load_jsonl_resumes(self) -> None:
        resumes = load_resumes(ROOT / "10_ai_phd_resumes.jsonl")
        self.assertEqual(len(resumes), 10)
        self.assertEqual(resumes[0].id, "candidate_01")
        self.assertTrue(resumes[0].projects)

    def test_single_candidate_returns_structured_result(self) -> None:
        resume = load_resumes(ROOT / "10_ai_phd_resumes.jsonl")[0]
        result = run_candidate(resume)
        self.assertEqual(result.id, "candidate_01")
        self.assertGreaterEqual(result.overall_score, 60)
        self.assertTrue(result.evidence)
        self.assertTrue(result.dimension_scores)
        self.assertTrue(result.interview_questions)
        self.assertNotIn("985", "\n".join(result.normalized_education))

    def test_batch_result_is_sorted_and_tiered(self) -> None:
        resumes = load_resumes(ROOT / "10_ai_phd_resumes.jsonl")
        result = run_batch(resumes)
        scores = [item.overall_score for item in result.evaluations]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertEqual(len(result.evaluations), 10)
        tiered_ids = [candidate_id for ids in result.tiers.values() for candidate_id in ids]
        self.assertEqual(sorted(tiered_ids), sorted(item.id for item in result.evaluations))

    def test_evidence_quotes_are_from_resume_text(self) -> None:
        resume = load_resumes(ROOT / "10_ai_phd_resumes.jsonl")[6]
        result = run_candidate(resume)
        raw_text = "\n".join(
            [
                resume.target_role,
                resume.stage,
                " ".join(resume.education),
                " ".join(resume.directions),
                " ".join(project.name + " " + " ".join(project.details) for project in resume.projects),
                " ".join(resume.publications),
                "、".join(resume.skills),
            ]
        )
        for evidence in result.evidence:
            self.assertIn(evidence.quote, raw_text)


if __name__ == "__main__":
    unittest.main()
