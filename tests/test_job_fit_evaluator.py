from __future__ import annotations

import unittest

from agi_talent_radar.agents.job_fit import evaluate_candidate_against_jobs
from agi_talent_radar.core.models import CandidateResume, JobDefinition


class JobFitEvaluatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.resume = CandidateResume(
            id="candidate-1",
            name="候选人甲",
            raw_text="有实习经历，构建 Coding Agent benchmark，负责 verifier 与 20 万条训练数据闭环。",
        )
        self.jobs = [
            JobDefinition(id="jd-agent", title="Agent 评测", raw_text="必须有实习经验，负责 Agent benchmark。"),
            JobDefinition(id="jd-mm", title="多模态生成", raw_text="负责 diffusion 模型训练。"),
        ]

    def test_each_jd_is_independent_and_best_fit_uses_decision_then_score(self) -> None:
        result = evaluate_candidate_against_jobs(self.resume, self.jobs, llm=_strong_agent_response)

        self.assertEqual([item.decision for item in result.assessments], ["interview", "reject"])
        self.assertEqual(result.best_fit_jd_id, "jd-agent")
        self.assertEqual(result.assessments[0].fit_score, 84.0)
        self.assertEqual(len(result.assessments[0].dimensions), 6)

    def test_unmet_hard_requirement_cannot_be_compensated_by_high_scores(self) -> None:
        resume = self.resume.model_copy(update={"raw_text": "明确无实习经历。"})
        result = evaluate_candidate_against_jobs(
            resume,
            [self.jobs[0]],
            llm=lambda *_: _single_response("unmet", score=5, evidence=["明确无实习经历"]),
        )

        assessment = result.assessments[0]
        self.assertEqual(assessment.fit_score, 100)
        self.assertEqual(assessment.decision, "reject")
        self.assertIn("明确不满足硬门槛", assessment.decision_reason)

    def test_unknown_hard_requirement_means_hold_not_reject(self) -> None:
        result = evaluate_candidate_against_jobs(
            self.resume,
            [self.jobs[0]],
            llm=lambda *_: _single_response("unknown", score=5),
        )

        assessment = result.assessments[0]
        self.assertEqual(assessment.decision, "hold")
        self.assertLessEqual(assessment.confidence, 0.75)

    def test_unknown_requirement_does_not_turn_weak_candidate_into_hold(self) -> None:
        result = evaluate_candidate_against_jobs(
            self.resume,
            [self.jobs[0]],
            llm=lambda *_: _single_response("unknown", score=2),
        )

        self.assertEqual(result.assessments[0].decision, "reject")

    def test_untraceable_met_or_unmet_is_downgraded_to_unknown(self) -> None:
        result = evaluate_candidate_against_jobs(
            self.resume,
            [self.jobs[0]],
            llm=lambda *_: _single_response("unmet", score=5, evidence=["模型自己编的反向事实"]),
        )

        requirement = result.assessments[0].hard_requirements[0]
        self.assertEqual(requirement.status, "unknown")
        self.assertEqual(result.assessments[0].decision, "hold")

    def test_missing_dimension_is_filled_with_zero_and_rejects_weak_match(self) -> None:
        response = _single_response("met", score=4)
        response["assessments"][0]["dimensions"] = [
            {"key": "technical_depth", "score": 4, "rationale": "有方法细节", "evidence": ["verifier"]}
        ]

        result = evaluate_candidate_against_jobs(self.resume, [self.jobs[0]], llm=lambda *_: response)

        assessment = result.assessments[0]
        direct = next(item for item in assessment.dimensions if item.key == "direct_task_match")
        self.assertEqual(direct.score, 0)
        self.assertEqual(assessment.decision, "reject")

    def test_missing_job_assessment_is_an_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "模型遗漏 JD 评估"):
            evaluate_candidate_against_jobs(
                self.resume,
                self.jobs,
                llm=lambda *_: {"assessments": [_assessment("jd-agent", "met", 4)]},
            )


def _strong_agent_response(*_args):
    return {
        "assessments": [
            _assessment("jd-agent", "met", 4.2),
            _assessment("jd-mm", "unmet", 2),
        ]
    }


def _single_response(status: str, score: float, evidence: list[str] | None = None) -> dict:
    return {"assessments": [_assessment("jd-agent", status, score, evidence)]}


def _assessment(jd_id: str, status: str, score: float, evidence: list[str] | None = None) -> dict:
    return {
        "jd_id": jd_id,
        "hard_requirements": [
            {
                "requirement": "必须有实习经验",
                "status": status,
                "evidence": evidence if evidence is not None else (["有实习经历"] if status == "met" else []),
                "rationale": "按简历明文判断",
            }
        ],
        "dimensions": [
            {"key": key, "score": score, "rationale": "有直接证据", "evidence": ["简历原文"]}
            for key in (
                "direct_task_match",
                "technical_depth",
                "ownership",
                "evidence_quality",
                "engineering_scale",
                "transferability",
            )
        ],
        "strengths": [{"summary": "直接做过核心任务", "evidence": ["Coding Agent benchmark"]}],
        "risks": [],
        "missing_information": [],
        "interview_questions": ["请解释 verifier 的失败案例。"],
        "confidence": 0.9,
        "assessment_summary": "核心任务证据充分",
    }


if __name__ == "__main__":
    unittest.main()
