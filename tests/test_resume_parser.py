from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from agi_talent_radar.agents.resume_parser import (
    ParsedResume,
    _looks_like_venue_only,
    iter_parse_resume_chunks,
    parse_raw_resume,
)

# 张三简历的真实 publications 列表（rapidocr 解析后 LLM 输出）
SAMPLE_PUBS = [
    "HingeMem: Boundary Guided Long-Term Memory with Query Adaptive Retrieval for Scalable Dialogues. WWW 2026. (CCF-A)",
    "Scene-Aware Memory Discrimination: Deciding Which Personal Knowledge Stays. Knowledge-Based Systems (KBS) 2026.",
    "ODDA: An OODA-Driven Diverse Data Augmentation Framework for Low-Resource Relation Extraction. ACL 2025. (CCF-A)",
    "Information Processing & Management (IPM) 2025. (标题缺失，不列为论文)",  # LLM 自注
    "C3Flow: SIMD-Style Concurrent Claude Code Workflow for Scaling DeepResearch. SIGIR 2026. (CCF-A)",
    "U-NiAH: Unified RAG and LLM Evaluation for Long Context Needle-in-a-Haystack. Transactions on Information Systems (TOIS) 2026.",
]


class ParsedResumeCoerceTest(unittest.TestCase):
    """LLM 输出 dict 列表时归一成字符串列表。"""

    def test_publications_dict_to_string(self) -> None:
        data = {"publications": [
            {"title": "Paper A", "venue": "WWW 2026", "year": "2026"},
            {"title": "", "venue": "IPM 2025"},  # 空 title 丢弃
            "Plain String Paper. CVPR 2025.",
        ]}
        p = ParsedResume.model_validate(data)
        self.assertEqual(p.publications, ["Paper A. WWW 2026. 2026", "Plain String Paper. CVPR 2025."])

    def test_education_structured_passthrough(self) -> None:
        # education 现为结构化对象透传，不再压成字符串；保留学历/专业/时间
        data = {"education": [
            {"school": "Fudan", "degree": "PhD", "major": "CS", "period": "2022-2025"},
            "清华 本科",  # 字符串仍兼容
        ]}
        p = ParsedResume.model_validate(data)
        self.assertEqual(p.education[0], {"school": "Fudan", "degree": "PhD", "major": "CS", "period": "2022-2025"})
        self.assertEqual(p.education[1], "清华 本科")


class VenueOnlyFilterTest(unittest.TestCase):
    def test_drops_llm_self_noted_venue(self) -> None:
        # 后端只兜底拦 LLM 自注"标题缺失/不列为论文"的条目，其余交给 LLM
        for pub in SAMPLE_PUBS:
            if _looks_like_venue_only(pub):
                self.assertIn("标题缺失", pub)
                self.assertEqual(pub, "Information Processing & Management (IPM) 2025. (标题缺失，不列为论文)")

    def test_keeps_real_papers(self) -> None:
        kept = [p for p in SAMPLE_PUBS if not _looks_like_venue_only(p)]
        self.assertEqual(len(kept), len(SAMPLE_PUBS) - 1)

    def test_self_note_variants(self) -> None:
        self.assertTrue(_looks_like_venue_only("IPM 2025. (不列为论文)"))
        self.assertTrue(_looks_like_venue_only("IPM 2025. (无独立标题)"))
        self.assertFalse(_looks_like_venue_only(""))


class IterParseResumeChunksTest(unittest.TestCase):
    """单次 LLM 流：字段组完整后立即产出，最后合并为 complete。"""

    _EVENTS = [
        {
            "section": "basic",
            "fields": {
                "name": "张三",
                "target_role": "AI 研究员",
                "stage": "博三",
                "directions": ["Agent"],
                "screening_tags": ["LLM"],
            },
        },
        {"section": "education", "fields": {"education": ["PhD"]}},
        {"section": "experiences", "fields": {"experiences": []}},
        {"section": "projects", "fields": {"projects": [{"name": "Agent 平台", "details": ["负责架构"]}]}},
        {
            "section": "publications",
            "fields": {
                "publications": [
                    "Paper A. AAAI 2025.",
                    "IPM 2025. (标题缺失，不列为论文)",
                ]
            },
        },
        {"section": "skills", "fields": {"skills": ["Python"]}},
    ]

    def _stream(self, events=None):
        text = "\n".join(json.dumps(item, ensure_ascii=False) for item in (events or self._EVENTS))
        # 刻意切在 JSON 行内部，验证网络 token 分片不会触发过早解析。
        return iter([text[:37], text[37:119], text[119:271], text[271:]])

    def test_uses_one_llm_call_and_yields_six_field_groups(self) -> None:
        with patch(
            "agi_talent_radar.agents.resume_parser.llm_client.call_llm_stream",
            return_value=self._stream(),
        ) as stream_call:
            chunks = list(iter_parse_resume_chunks("c1", "raw text"))

        section_chunks = [c for c in chunks if c[0] == "section"]
        complete_chunks = [c for c in chunks if c[0] == "complete"]
        self.assertEqual(len(section_chunks), 6)
        self.assertEqual(len(complete_chunks), 1)
        stream_call.assert_called_once()

    def test_field_group_chunk_carries_ordered_progress(self) -> None:
        with patch(
            "agi_talent_radar.agents.resume_parser.llm_client.call_llm_stream",
            return_value=self._stream(),
        ):
            chunks = list(iter_parse_resume_chunks("c1", "raw text"))

        progress = [(c[1], c[2], c[3]) for c in chunks if c[0] == "section"]
        self.assertEqual(
            progress,
            [
                ("基本信息", 1, 6),
                ("教育经历", 2, 6),
                ("工作经历", 3, 6),
                ("项目经历", 4, 6),
                ("论文成果", 5, 6),
                ("技能", 6, 6),
            ],
        )

    def test_complete_chunk_filters_venue_and_merges(self) -> None:
        with patch(
            "agi_talent_radar.agents.resume_parser.llm_client.call_llm_stream",
            return_value=self._stream(),
        ):
            complete = [c for c in iter_parse_resume_chunks("c1", "raw text") if c[0] == "complete"][0]

        merged = complete[4]
        # 期刊自注条目被兜底过滤，只留真论文
        self.assertEqual(merged.publications, ["Paper A. AAAI 2025."])
        self.assertEqual(merged.education, ["PhD"])
        self.assertEqual(merged.skills, ["Python"])
        self.assertEqual(merged.name, "张三")

    def test_full_raw_text_and_visual_sections_share_the_single_request(self) -> None:
        visual_sections = [{"name": "基本信息", "text": "张三"}]
        with patch(
            "agi_talent_radar.agents.resume_parser.llm_client.call_llm_stream",
            return_value=self._stream(),
        ) as stream_call:
            list(iter_parse_resume_chunks("c1", "第一页\n第二页项目", has_ocr=True, pre_sections=visual_sections))

        payload = stream_call.call_args.args[1]
        self.assertEqual(payload["raw_text"], "第一页\n第二页项目")
        self.assertEqual(payload["visual_section_names"], ["基本信息"])
        self.assertTrue(payload["has_ocr"])

    def test_missing_field_group_fails_instead_of_saving_partial_resume(self) -> None:
        with patch(
            "agi_talent_radar.agents.resume_parser.llm_client.call_llm_stream",
            return_value=self._stream(self._EVENTS[:-1]),
        ):
            with self.assertRaisesRegex(ValueError, "缺少字段组：技能"):
                list(iter_parse_resume_chunks("c1", "raw text"))

    def test_empty_text_yields_nothing(self) -> None:
        self.assertEqual(list(iter_parse_resume_chunks("c1", "")), [])

    def test_parse_raw_resume_returns_merged_only(self) -> None:
        with patch(
            "agi_talent_radar.agents.resume_parser.llm_client.call_llm_stream",
            return_value=self._stream(),
        ):
            resume = parse_raw_resume("c1", "raw text")

        self.assertEqual(resume.id, "c1")
        self.assertEqual(resume.publications, ["Paper A. AAAI 2025."])
        self.assertEqual(resume.education, ["PhD"])


if __name__ == "__main__":
    unittest.main()
