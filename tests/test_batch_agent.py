from __future__ import annotations

import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from agi_talent_radar.agents.normalizer import run_normalizer
from agi_talent_radar.agents.critic import route_after_critic, run_critic
from agi_talent_radar.agents.evidence_integrity import is_quote_traceable
from agi_talent_radar.core.io import load_resumes
from agi_talent_radar.core.runner import run_batch, run_candidate
from tests.llm_fixtures import mock_deepseek_json
from tests.resume_fixtures import make_resume_fixtures


ROOT = Path(__file__).resolve().parents[1]


class BatchAgentTest(unittest.TestCase):
    def test_load_jsonl_resumes(self) -> None:
        source = make_resume_fixtures()[0]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "resume.jsonl"
            path.write_text(source.model_dump_json() + "\n", encoding="utf-8")
            resumes = load_resumes(path)
        self.assertEqual(len(resumes), 1)
        self.assertEqual(resumes[0].id, source.id)
        self.assertTrue(resumes[0].projects)

    def test_single_candidate_returns_structured_result(self) -> None:
        resume = make_resume_fixtures()[0]
        with mock_deepseek_json():
            result = run_candidate(resume)
        self.assertEqual(result.id, resume.id)
        self.assertGreaterEqual(result.overall_score, 55)
        self.assertIn(result.level, {"B", "C"})
        self.assertIn(result.tier, {"建议沟通", "暂缓 / 需补充信息"})
        self.assertNotIn("学校/GPA/排名", result.one_liner)
        self.assertTrue(result.evidence)
        self.assertTrue(result.dimension_scores)
        self.assertTrue(result.interview_questions)
        self.assertNotIn("985", "\n".join(result.normalized_education))
        self.assertNotIn("GPA 3.82", "\n".join(result.normalized_education))
        self.assertNotIn("方向方向", result.one_liner)

    def test_normalizer_folds_academic_background_into_tiers(self) -> None:
        resume = make_resume_fixtures()[0]
        with mock_deepseek_json():
            state = run_normalizer({"resume": resume.model_dump(), "loop_count": 0})
        normalized = state["normalized"]
        folded = "\n".join(normalized["education_blind"])
        self.assertIn("学校层级=", folded)
        self.assertIn("具体学校/GPA/排名已折叠", folded)
        self.assertNotIn("985", folded)
        self.assertNotIn("3.82", folded)
        self.assertIn("background_signal_tiers", normalized)

    def test_batch_result_is_sorted_and_tiered(self) -> None:
        resumes = make_resume_fixtures()
        with (
            mock_deepseek_json(),
            patch("agi_talent_radar.core.import_agent._persist_single_import"),
            patch("agi_talent_radar.core.runner._persist_evaluations"),
        ):
            result = run_batch(resumes)
        scores = [item.overall_score for item in result.evaluations]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertEqual(len(result.evaluations), len(resumes))
        tiered_ids = [candidate_id for ids in result.tiers.values() for candidate_id in ids]
        self.assertEqual(sorted(tiered_ids), sorted(item.id for item in result.evaluations))
        self.assertEqual(len(result.import_classifications), len(resumes))
        self.assertTrue(result.evaluations[0].import_category)

    def test_evidence_quotes_are_from_resume_text(self) -> None:
        resume = make_resume_fixtures()[0]
        with mock_deepseek_json():
            result = run_candidate(resume)
        raw_text = "\n".join(
            [
                resume.target_role,
                resume.stage,
                " ".join(resume.education),
                "、".join(resume.directions),
                " ".join(project.name + " " + " ".join(project.details) for project in resume.projects),
                " ".join(resume.publications),
                "、".join(resume.skills),
            ]
        )
        for evidence in result.evidence:
            self.assertIn(evidence.quote, raw_text)

    def test_critic_does_not_flag_joined_skill_evidence_as_hallucination(self) -> None:
        resume = make_resume_fixtures()[2]
        with mock_deepseek_json():
            result = run_candidate(resume)
        joined_flags = "\n".join(result.critic_flags)
        self.assertNotIn("疑似幻觉证据", joined_flags)

    def test_semantic_reordered_quote_is_traceable(self) -> None:
        raw_text = "设计构图-出题-求解-验证-反思的多智能体闭环系统"
        quote = "多智能体系统包含构图、出题、求解、验证和反思闭环"
        self.assertTrue(is_quote_traceable(quote, raw_text))

    def test_critic_rewrites_untraceable_evidence_before_exposing_flag(self) -> None:
        resume = make_resume_fixtures()[1]
        with mock_deepseek_json():
            normalized = run_normalizer({"resume": resume.model_dump(), "loop_count": 0})["normalized"]
        state = {
            "normalized": normalized,
            "evidence": [
                {
                    "id": "e999",
                    "dimension": "engineering_practice",
                    "source": "项目：不存在",
                    "quote": "使用虚构框架把吞吐提升999%",
                    "signals": ["技术栈:虚构框架", "量化结果:999%"],
                    "strength": 5,
                    "has_metric": True,
                    "has_specific_tool": True,
                    "has_ownership": False,
                }
            ],
            "scores": [
                {
                    "key": "engineering_practice",
                    "label": "工程实践能力",
                    "score": 4.5,
                    "weighted_score": 14.4,
                    "rationale": "e999 支撑该维度判断。",
                    "evidence_ids": ["e999"],
                    "risk_notes": [],
                }
            ],
            "critic_flags": [],
            "loop_count": 0,
            "evidence_loop_count": 0,
            "score_loop_count": 0,
        }
        with mock_deepseek_json():
            updated = run_critic(state)

        self.assertTrue(updated["critic_needs_evidence_rewrite"])
        self.assertEqual(route_after_critic(updated), "evidence_extractor")
        self.assertEqual(updated["critic_flags"], [])
        self.assertIn("疑似幻觉证据", "\n".join(updated["evidence_repair_feedback"]))


if __name__ == "__main__":
    unittest.main()
