from __future__ import annotations

import unittest

from agi_talent_radar.agents.scorer import _calibrate_scoring
from agi_talent_radar.core.models import DimensionScore, EvidenceItem
from agi_talent_radar.core.rubric import CALIBRATION_REFERENCE, RUBRIC


class ScoringCalibrationTest(unittest.TestCase):
    def test_glossy_cross_domain_profile_is_capped_without_hard_loop_evidence(self) -> None:
        evidence = [
            EvidenceItem(
                id="e001",
                dimension="research_exploration",
                source="项目：医学多任务大模型适配",
                quote="进行SFT、知识蒸馏和RAG增强，降低幻觉率",
                signals=["技术栈:RAG"],
                strength=3,
                has_metric=False,
                has_specific_tool=True,
                has_ownership=False,
            ),
            EvidenceItem(
                id="e002",
                dimension="cultivation_value",
                source="代表成果",
                quote="Data-Free Continual Learning for Multimodal LLMs，拟投CVPR 2026，一作",
                signals=["论文:拟投"],
                strength=2,
                has_metric=False,
                has_specific_tool=False,
                has_ownership=True,
            ),
        ]
        inflated_scores = [
            DimensionScore(
                key=item.key,
                label=item.label,
                score=4.6,
                weighted_score=round(4.6 * item.weight * 20, 2),
                rationale="简历方向光鲜，跨域能力强。",
                evidence_ids=["e001"],
                risk_notes=["缺少量化定义，需确认本人贡献。"],
            )
            for item in RUBRIC
        ]

        calibrated, assessment = _calibrate_scoring(inflated_scores, evidence)
        by_key = {item.key: item for item in calibrated}

        self.assertLessEqual(assessment["overall_score"], 79)
        self.assertLessEqual(by_key["ownership"].score, 3.0)
        self.assertLessEqual(by_key["problem_definition"].score, 1.5)
        self.assertLessEqual(by_key["ai_agent_leverage"].score, 2.0)
        self.assertIn("高潜画像", CALIBRATION_REFERENCE)
        self.assertIn("candidate_02", CALIBRATION_REFERENCE)

    def test_closed_loop_agent_profile_can_remain_in_preferred_band(self) -> None:
        evidence = [
            EvidenceItem(
                id="e001",
                dimension="problem_definition",
                source="项目：可验证几何数据合成框架",
                quote="设计构图-出题-求解-验证-反思的多智能体闭环系统",
                signals=["AI杠杆:Agent", "动作:设计", "验证闭环"],
                strength=5,
                has_metric=False,
                has_specific_tool=True,
                has_ownership=True,
            ),
            EvidenceItem(
                id="e002",
                dimension="ai_agent_leverage",
                source="项目：混合式几何求解器",
                quote="自动拦截约47%错误题目，并修复其中60%以上",
                signals=["量化结果:47%", "验证闭环", "AI杠杆:Agent"],
                strength=5,
                has_metric=True,
                has_specific_tool=True,
                has_ownership=False,
            ),
            EvidenceItem(
                id="e003",
                dimension="ownership",
                source="项目：多模态训练数据质量评估",
                quote="负责benchmark设计、模型评测和错误归因",
                signals=["动作:负责", "验证闭环"],
                strength=5,
                has_metric=False,
                has_specific_tool=True,
                has_ownership=True,
            ),
            EvidenceItem(
                id="e004",
                dimension="engineering_practice",
                source="技能关键词",
                quote="Python, SymPy, PyTorch, verifier, benchmark design",
                signals=["技术栈:SymPy", "技术栈:PyTorch"],
                strength=4,
                has_metric=False,
                has_specific_tool=True,
                has_ownership=False,
            ),
        ]
        strong_scores = [
            DimensionScore(
                key=item.key,
                label=item.label,
                score=4.4 if item.key in {
                    "learning_growth",
                    "research_exploration",
                    "engineering_practice",
                    "ai_agent_leverage",
                    "problem_definition",
                    "ownership",
                    "cultivation_value",
                } else 2.6,
                weighted_score=0,
                rationale="由闭环证据支撑。",
                evidence_ids=[next((e.id for e in evidence if e.dimension == item.key), "e001")],
                risk_notes=[],
            )
            for item in RUBRIC
        ]

        calibrated, assessment = _calibrate_scoring(strong_scores, evidence)

        self.assertGreaterEqual(assessment["overall_score"], 80)
        self.assertEqual(assessment["tier"], "强烈建议沟通")
        self.assertGreaterEqual({item.key: item.score for item in calibrated}["problem_definition"], 4.0)


if __name__ == "__main__":
    unittest.main()
