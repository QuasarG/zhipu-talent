from __future__ import annotations

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
    """流式解析：逐节产出 section 事件，最后产 complete 事件。"""

    _SECTIONS = [
        {"name": "论文", "text": "Paper A. AAAI 2025."},
        {"name": "教育", "text": "PhD at Fudan"},
        {"name": "技能", "text": "Python"},
    ]

    def _mock_extract(self, section, current_date, has_ocr):
        name = section["name"]
        if name == "论文":
            return ParsedResume(publications=["Paper A. AAAI 2025.", "IPM 2025. (标题缺失，不列为论文)"])
        if name == "教育":
            return ParsedResume(name="张三", education=["PhD"], stage="博三")
        return ParsedResume(skills=["Python"])

    def test_yields_sections_then_complete(self) -> None:
        with (
            patch("agi_talent_radar.agents.resume_parser.reorganize_resume_text", return_value=self._SECTIONS),
            patch("agi_talent_radar.agents.resume_parser._extract_section_fields", side_effect=self._mock_extract),
        ):
            chunks = list(iter_parse_resume_chunks("c1", "raw text"))

        section_chunks = [c for c in chunks if c[0] == "section"]
        complete_chunks = [c for c in chunks if c[0] == "complete"]
        self.assertEqual(len(section_chunks), 3)
        self.assertEqual(len(complete_chunks), 1)

    def test_section_chunk_carries_progress(self) -> None:
        with (
            patch("agi_talent_radar.agents.resume_parser.reorganize_resume_text", return_value=self._SECTIONS),
            patch("agi_talent_radar.agents.resume_parser._extract_section_fields", side_effect=self._mock_extract),
        ):
            chunks = list(iter_parse_resume_chunks("c1", "raw text"))

        section_names = {c[1] for c in chunks if c[0] == "section"}
        self.assertEqual(section_names, {"论文", "教育", "技能"})
        for kind, _, done, total, _ in chunks:
            if kind == "section":
                self.assertEqual(total, 3)
                self.assertGreaterEqual(done, 1)
                self.assertLessEqual(done, 3)

    def test_complete_chunk_filters_venue_and_merges(self) -> None:
        with (
            patch("agi_talent_radar.agents.resume_parser.reorganize_resume_text", return_value=self._SECTIONS),
            patch("agi_talent_radar.agents.resume_parser._extract_section_fields", side_effect=self._mock_extract),
        ):
            complete = [c for c in iter_parse_resume_chunks("c1", "raw text") if c[0] == "complete"][0]

        merged = complete[4]
        # 期刊自注条目被兜底过滤，只留真论文
        self.assertEqual(merged.publications, ["Paper A. AAAI 2025."])
        self.assertEqual(merged.education, ["PhD"])
        self.assertEqual(merged.skills, ["Python"])
        self.assertEqual(merged.name, "张三")

    def test_empty_text_yields_nothing(self) -> None:
        self.assertEqual(list(iter_parse_resume_chunks("c1", "")), [])

    def test_parse_raw_resume_returns_merged_only(self) -> None:
        with (
            patch("agi_talent_radar.agents.resume_parser.reorganize_resume_text", return_value=self._SECTIONS),
            patch("agi_talent_radar.agents.resume_parser._extract_section_fields", side_effect=self._mock_extract),
        ):
            resume = parse_raw_resume("c1", "raw text")

        self.assertEqual(resume.id, "c1")
        self.assertEqual(resume.publications, ["Paper A. AAAI 2025."])
        self.assertEqual(resume.education, ["PhD"])


if __name__ == "__main__":
    unittest.main()
