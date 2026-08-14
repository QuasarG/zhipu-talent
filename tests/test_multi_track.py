from __future__ import annotations

import unittest
from unittest.mock import patch

from agi_talent_radar.agents.common_potential import run_common_critic, run_common_scorer
from agi_talent_radar.agents.routing.track_router import _normalize_assignments
from agi_talent_radar.agents.tracks.registry import TRACK_SPECS
from agi_talent_radar.agents.tracks.agent.nodes import _calibrate_agent_portfolio
from agi_talent_radar.agents.tracks.safety.nodes import _calibrate_security_portfolio
from agi_talent_radar.agents.tracks.shared.engine import _supports_high_score
from agi_talent_radar.core.models import CandidateResume, DimensionScore, EvidenceItem, NormalizedResume
from agi_talent_radar.core.resume_ingestion import extract_pdf_text
from agi_talent_radar.core.runner import run_candidate
from tests.llm_fixtures import mock_llm_json
from tests.resume_fixtures import make_resume_fixtures


class MultiTrackTest(unittest.TestCase):
    def test_common_critic_uses_dimension_specific_high_score_evidence(self) -> None:
        state = {
            "evidence": [
                EvidenceItem(
                    id="e_problem_1",
                    dimension="problem_definition",
                    source="项目 A",
                    quote="负责定义硬件断点检测问题",
                    strength=3,
                    has_ownership=True,
                ).model_dump(),
                EvidenceItem(
                    id="e_problem_2",
                    dimension="problem_definition",
                    source="项目 B",
                    quote="构建 Angr 符号执行引擎",
                    strength=3,
                    has_specific_tool=True,
                ).model_dump(),
                EvidenceItem(
                    id="e_owner",
                    dimension="ownership",
                    source="项目 C",
                    quote="作为项目负责人主导实现",
                    strength=4,
                    has_ownership=True,
                ).model_dump(),
                EvidenceItem(
                    id="e_paper",
                    dimension="evidence_credibility",
                    source="已发表论文",
                    quote="ASE CCF-A 论文",
                    strength=4,
                ).model_dump(),
            ],
            "common_scores": [
                {
                    "key": "problem_definition",
                    "label": "问题定义与独立判断",
                    "score": 4,
                    "weighted_score": 6.4,
                    "max_points": 8,
                    "evidence_ids": ["e_problem_1", "e_problem_2"],
                },
                {
                    "key": "ownership",
                    "label": "Ownership 与贡献边界",
                    "score": 4,
                    "weighted_score": 5.6,
                    "max_points": 7,
                    "evidence_ids": ["e_owner"],
                },
                {
                    "key": "evidence_credibility",
                    "label": "证据可信度与可复现性",
                    "score": 4,
                    "weighted_score": 5.6,
                    "max_points": 7,
                    "evidence_ids": ["e_paper"],
                },
            ],
        }
        result = run_common_critic(state)

        self.assertEqual([item["score"] for item in result["common_scores"]], [4, 4, 4])
        self.assertEqual(result["common_critic_flags"], [])

    def test_common_critic_caps_unverified_rigor(self) -> None:
        state = {
            "evidence": [
                EvidenceItem(
                    id="e_talk",
                    dimension="research_rigor",
                    source="项目 X",
                    quote="参与讨论研究方向，未给出指标或验证",
                    strength=3,
                ).model_dump(),
            ],
            "common_scores": [
                {
                    "key": "research_rigor",
                    "label": "探索严谨性与验证能力",
                    "score": 3.5,
                    "weighted_score": 6.3,
                    "max_points": 9,
                    "evidence_ids": ["e_talk"],
                },
            ],
        }
        result = run_common_critic(state)

        self.assertEqual(result["common_scores"][0]["score"], 2.5)

    def test_common_critic_accepts_runnable_deliverable_as_verification(self) -> None:
        state = {
            "evidence": [
                EvidenceItem(
                    id="e_ship",
                    dimension="evidence_credibility",
                    source="Agent 平台",
                    quote="系统已上线并通过验收",
                    strength=3,
                    has_specific_tool=True,
                ).model_dump(),
            ],
            "common_scores": [
                {
                    "key": "evidence_credibility",
                    "label": "证据可信度与可复现性",
                    "score": 3.5,
                    "weighted_score": 6.3,
                    "max_points": 9,
                    "evidence_ids": ["e_ship"],
                },
            ],
        }
        result = run_common_critic(state)

        self.assertEqual(result["common_scores"][0]["score"], 3.5)

    def test_router_removes_ineligible_llm_systems_assignment(self) -> None:
        normalized = NormalizedResume(
            id="mobile_security",
            name="移动安全候选人",
            target_role="移动安全与安全智能体研究员",
            directions=["Agentic Fuzzing", "Multi-Agent 风险识别"],
            skills=["Angr", "AFL", "神经网络"],
        )
        evidence = [
            EvidenceItem(
                id="e_safety",
                dimension="track_specific",
                source="移动安全项目",
                quote="构建防 Hook 与断点检测框架",
                strength=4,
            ),
            EvidenceItem(
                id="e_agent_1",
                dimension="track_specific",
                source="JANUS",
                quote="Agentic Fuzzing Harness 生成",
                strength=3,
            ),
            EvidenceItem(
                id="e_agent_2",
                dimension="track_specific",
                source="AIntel-Agent",
                quote="Multi-Agent 风险识别",
                strength=3,
            ),
            EvidenceItem(
                id="e_engine",
                dimension="track_specific",
                source="符号执行项目",
                quote="构建混合测试引擎",
                strength=3,
            ),
        ]
        assignments = _normalize_assignments(
            [
                {"track": "safety", "weight": 0.6, "confidence": 0.9, "evidence_ids": ["e_safety"]},
                {
                    "track": "agent",
                    "weight": 0.3,
                    "confidence": 0.8,
                    "evidence_ids": ["e_agent_1", "e_agent_2"],
                },
                {"track": "ai_infra", "weight": 0.1, "confidence": 0.6, "evidence_ids": ["e_engine"]},
            ],
            normalized,
            evidence,
        )

        self.assertEqual([item.track for item in assignments], ["safety", "agent"])
        self.assertAlmostEqual(assignments[0].weight, 2 / 3, places=3)
        self.assertAlmostEqual(assignments[1].weight, 1 / 3, places=3)

    def test_common_scorer_tolerates_mixed_dimension_shapes(self) -> None:
        state = {
            "normalized": {
                "id": "mixed_scores",
                "name": "混合输出候选人",
                "target_role": "AI 研究员",
            },
            "evidence": [],
            "track_assignments": [],
        }
        response = {
            "dimension_scores": [
                "invalid free text",
                {
                    "key": "problem_definition",
                    "score": "4/5",
                    "rationale": "e1 支撑。",
                    "evidence_ids": "e1",
                    "risk_notes": "待验证",
                },
                {"research_rigor": {"score": 3.5, "rationale": "有对照实验。"}},
            ]
        }
        with patch("agi_talent_radar.core.llm_client.call_llm_json", return_value=response):
            result = run_common_scorer(state)

        scores = {item["key"]: item for item in result["common_scores"]}
        self.assertEqual(scores["problem_definition"]["score"], 4.0)
        self.assertEqual(scores["problem_definition"]["evidence_ids"], ["e1"])
        self.assertEqual(scores["research_rigor"]["score"], 3.5)
        self.assertEqual(scores["ownership"]["score"], 0.0)

    def test_visual_resume_structured_lists_are_normalized(self) -> None:
        resume = CandidateResume.model_validate(
            {
                "id": "visual_structured",
                "education": [
                    {
                        "school": "南方科技大学",
                        "degree": "博士",
                        "major": "计算机科学",
                        "advisor": "导师 A",
                    }
                ],
                "work_experience": [
                    {
                        "company": "某 AI 公司",
                        "position": "Agent 研发实习生",
                        "start": "2025.01",
                        "end": "2025.06",
                        "responsibilities": ["构建自动验证闭环"],
                    }
                ],
                "publications": [
                    {
                        "authors": ["Yichen Li", "Author B"],
                        "title": "A Reliable Agent System",
                        "venue": "ICSE 2024",
                        "year": "2024",
                    }
                ],
                "projects": [
                    {
                        "title": "Coding Agent",
                        "description": "构建自动验证闭环",
                        "results": {"pass_rate": "+18%"},
                    }
                ],
            }
        )

        # education 保留结构化 dict（供前端分字段渲染），其他列表压成字符串
        self.assertEqual(resume.education[0]["school"], "南方科技大学")
        self.assertEqual(resume.education[0]["advisor"], "导师 A")
        self.assertEqual(resume.experiences[0].organization, "某 AI 公司")
        self.assertEqual(resume.experiences[0].role, "Agent 研发实习生")
        self.assertEqual(resume.experiences[0].details, ["构建自动验证闭环"])
        self.assertIn("题目: A Reliable Agent System", resume.publications[0])
        self.assertIn("作者: Yichen Li、Author B", resume.publications[0])
        self.assertEqual(resume.projects[0].name, "Coding Agent")
        self.assertTrue(all(isinstance(detail, str) for detail in resume.projects[0].details))

    def test_each_track_rubric_has_sixty_points(self) -> None:
        self.assertEqual(
            set(TRACK_SPECS),
            {"base", "agent", "safety", "multimodal", "ai_infra", "ai4science"},
        )
        for spec in TRACK_SPECS.values():
            self.assertEqual(spec.max_points, 60)
            self.assertEqual(len({item.key for item in spec.dimensions}), len(spec.dimensions))

    def test_security_and_agent_weights_prioritize_method_depth(self) -> None:
        safety = {item.key: item.max_points for item in TRACK_SPECS["safety"].dimensions}
        agent = {item.key: item.max_points for item in TRACK_SPECS["agent"].dimensions}

        self.assertEqual(
            safety,
            {
                "security_insight": 10,
                "method_innovation": 14,
                "validation_rigor": 12,
                "research_impact": 10,
                "security_engineering": 8,
                "ai_safety_transfer": 6,
            },
        )
        self.assertEqual(agent["agent_method"], 14)
        self.assertEqual(agent["verification_reliability"], 10)
        self.assertNotIn("self_evolution", agent)
        self.assertEqual(agent["agent_research_impact"], 10)

    def test_multiple_independent_strong_results_support_high_track_score(self) -> None:
        evidence = [
            EvidenceItem(
                id="e_paper_1",
                dimension="evidence_credibility",
                source="ASE 2023",
                quote="已发表安全研究成果",
                strength=4,
            ),
            EvidenceItem(
                id="e_paper_2",
                dimension="evidence_credibility",
                source="ASE 2025",
                quote="已发表安全研究成果",
                strength=4,
            ),
        ]

        self.assertTrue(_supports_high_score(evidence))

    def test_security_portfolio_calibration_requires_hard_combination_evidence(self) -> None:
        scores = [
            DimensionScore(key=item.key, label=item.label, score=3, max_points=item.max_points)
            for item in TRACK_SPECS["safety"].dimensions
        ]
        evidence = [
            EvidenceItem(
                id=f"e_project_{index}",
                dimension="track_specific",
                source=f"安全项目 {index}",
                quote="负责安全方法与工具实现",
                strength=4,
                has_ownership=True,
                has_specific_tool=index == 0,
            )
            for index in range(6)
        ]
        evidence.extend(
            [
                EvidenceItem(
                    id="e_pub_1",
                    dimension="evidence_credibility",
                    source="ASE 2024",
                    quote="已发表 CCF-A",
                    signals=["发表状态:已发表"],
                    strength=4,
                ),
                EvidenceItem(
                    id="e_pub_2",
                    dimension="evidence_credibility",
                    source="ASE 2025",
                    quote="已发表 CCF-A",
                    signals=["发表状态:已发表"],
                    strength=4,
                ),
            ]
        )

        calibrated = {item.key: item for item in _calibrate_security_portfolio(scores, evidence)}

        self.assertEqual(calibrated["method_innovation"].score, 4.5)
        self.assertEqual(calibrated["validation_rigor"].score, 4.0)
        self.assertEqual(calibrated["ai_safety_transfer"].score, 3.0)

    def test_agent_portfolio_calibration_does_not_require_self_evolution(self) -> None:
        scores = [
            DimensionScore(key=item.key, label=item.label, score=2, max_points=item.max_points)
            for item in TRACK_SPECS["agent"].dimensions
        ]
        evidence = [
            EvidenceItem(
                id=f"e_agent_{index}",
                dimension="track_specific",
                source=f"Agent 成果 {index}",
                quote="共同一作已发表 Agent 研究",
                signals=["发表状态:已发表", "作者位置:共同一作"],
                strength=4,
                has_ownership=True,
            )
            for index in range(3)
        ]

        calibrated = {item.key: item for item in _calibrate_agent_portfolio(scores, evidence)}

        self.assertEqual(calibrated["agent_method"].score, 3.5)
        self.assertEqual(calibrated["agent_research_impact"].score, 4.0)

    def test_candidate_uses_normalized_multi_track_portfolio(self) -> None:
        resume = make_resume_fixtures()[0]
        with mock_llm_json():
            result = run_candidate(resume)

        self.assertGreaterEqual(len(result.track_assignments), 1)
        self.assertLessEqual(len(result.track_assignments), 3)
        self.assertAlmostEqual(sum(item.weight for item in result.track_assignments), 1, places=3)
        self.assertEqual(
            {item.track for item in result.track_assignments},
            {item.track for item in result.track_evaluations},
        )
        track_score = sum(
            evaluation.calibrated_score * next(
                assignment.weight for assignment in result.track_assignments if assignment.track == evaluation.track
            )
            for evaluation in result.track_evaluations
        )
        self.assertEqual(result.overall_score, round(result.common_score + track_score))
        self.assertLessEqual(result.common_score, 40)
        self.assertEqual(result.document_score, 0)

    def test_pdf_text_layer_extraction(self) -> None:
        import fitz

        document = fitz.open()
        page = document.new_page()
        page.insert_text((72, 72), "Zhang San LLM researcher pretraining and evaluation pipeline")
        pdf_bytes = document.tobytes()
        document.close()

        raw_text, ocr_pages = extract_pdf_text(pdf_bytes)

        self.assertIn("Zhang San", raw_text)
        self.assertEqual(ocr_pages, [])


if __name__ == "__main__":
    unittest.main()
