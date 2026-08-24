from __future__ import annotations

import unittest
from unittest.mock import patch

from agi_talent_radar.agents.common_potential import run_common_critic, run_common_scorer
from agi_talent_radar.agents.routing.track_router import _normalize_assignments
from agi_talent_radar.agents.tracks.shared.engine import _supports_high_score
from agi_talent_radar.core.models import CandidateResume, DimensionScore, EvidenceItem, NormalizedResume
from agi_talent_radar.core.resume_ingestion import extract_pdf_text
from agi_talent_radar.core.runner import run_candidate
from tests.llm_fixtures import mock_llm_json
from tests.resume_fixtures import make_resume_fixtures
from tests.track_fixtures import make_dynamic_specs, make_spec, patch_active_specs


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
            make_dynamic_specs(),
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

    def test_jd_spec_normalization_enforces_sixty_point_budget(self) -> None:
        from agi_talent_radar.agents.jd_spec import _normalize_spec

        spec = make_spec("jd_x", dims=(("a", "甲", 10), ("b", "乙", 10), ("c", "丙", 10)))
        normalized = _normalize_spec(spec)

        self.assertAlmostEqual(sum(d.max_points for d in normalized.dimensions), 60.0)
        self.assertEqual(len(normalized.dimensions), 3)

    def test_track_spec_dict_round_trip(self) -> None:
        from agi_talent_radar.agents.tracks.shared.spec import TrackSpec

        spec = make_spec("roundtrip", keywords=("rlhf", "蒸馏"))
        restored = TrackSpec.from_dict(spec.to_dict())

        self.assertEqual(restored.key, spec.key)
        self.assertEqual(restored.dimensions, spec.dimensions)
        self.assertEqual(restored.keywords, spec.keywords)

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

    def test_candidate_uses_normalized_multi_track_portfolio(self) -> None:
        resume = make_resume_fixtures()[0]
        with mock_llm_json(), patch_active_specs():
            result = run_candidate(resume)

        self.assertEqual(result.evaluation_mode, "jd_fit_v2")
        self.assertFalse(result.track_assignments)
        self.assertFalse(result.track_evaluations)
        self.assertEqual(len(result.job_fit_assessments), 6)
        self.assertTrue(all(len(item.dimensions) == 6 for item in result.job_fit_assessments))
        self.assertEqual(result.overall_score, round(max(item.fit_score for item in result.job_fit_assessments)))

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
