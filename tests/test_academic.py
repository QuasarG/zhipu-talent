from __future__ import annotations

import unittest
from unittest.mock import patch

from agi_talent_radar.agents.academic.models import AcademicReport, PaperClaim
from agi_talent_radar.agents.academic.nodes import align_claims, extract_claims, lookup_claim, run_academic_check, run_resume_academic_check
from agi_talent_radar.core.connectors.base import ConnectorUnavailableError, Fact


def _work_fact(title: str, url: str = "https://openalex.org/W1") -> Fact:
    return Fact(
        source="openalex",
        fact_type="paper",
        payload={"query_title": title, "title": title, "year": 2024, "venue": "NeurIPS", "authors": ["San Zhang"], "cited_by_count": 10, "is_retracted": False},
        source_url=url,
    )


class AcademicChainTest(unittest.TestCase):
    def test_publication_statuses_are_normalized(self) -> None:
        cases = {
            "draft": "草稿",
            "投稿中": "已投稿",
            "under review": "在审",
            "已录用": "已接收",
            "published": "已发表",
        }
        for raw, expected in cases.items():
            self.assertEqual(PaperClaim(title="Paper", claimed_status=raw).claimed_status, expected)

    def test_extract_claims_filters_empty_titles(self) -> None:
        llm_response = {
            "claims": [
                {"title": "A Reliable Agent", "venue": "ICSE", "year": "2024", "claimed_role": "一作", "claimed_status": "已发表"},
                {"title": "", "claimed_status": "不明"},
            ]
        }
        with patch("agi_talent_radar.agents.academic.nodes.llm_client.call_llm_json", return_value=llm_response):
            claims = extract_claims(["A Reliable Agent, ICSE 2024, 一作"])

        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0].claimed_status, "已发表")

    def test_lookup_claim_degrades_to_warning(self) -> None:
        def broken_search(title, count=3):
            raise ConnectorUnavailableError("OpenAlex 超时")

        candidates, warning = lookup_claim(PaperClaim(title="X"), search_fn=broken_search)

        self.assertEqual(candidates, [])
        self.assertIn("超时", warning)

    def test_align_claims_defaults_to_unverifiable(self) -> None:
        claims = [PaperClaim(title="Paper A"), PaperClaim(title="Paper B")]
        llm_response = {
            "alignments": [
                {"claim_title": "Paper A", "verdict": "verified", "matched_title": "Paper A", "cited_by_count": 5, "openalex_url": "https://openalex.org/W1"},
                {"claim_title": "Paper B", "verdict": "not_a_verdict"},
            ]
        }
        with patch("agi_talent_radar.agents.academic.nodes.llm_client.call_llm_json", return_value=llm_response):
            alignments = align_claims("张三", claims, [[], []])

        self.assertEqual(alignments[0].verdict, "verified")
        self.assertEqual(alignments[0].cited_by_count, 5)
        self.assertEqual(alignments[1].verdict, "unverifiable")

    def test_run_academic_check_end_to_end_with_mocks(self) -> None:
        extract_response = {
            "claims": [
                {"title": "A Reliable Agent", "venue": "ICSE", "year": "2024", "claimed_role": "一作", "claimed_status": "已发表"}
            ]
        }
        align_response = {
            "alignments": [
                {"claim_title": "A Reliable Agent", "verdict": "verified", "matched_title": "A Reliable Agent", "cited_by_count": 3, "openalex_url": "https://openalex.org/W1"}
            ]
        }
        responses = iter([extract_response, align_response])
        with patch(
            "agi_talent_radar.agents.academic.nodes.llm_client.call_llm_json",
            side_effect=lambda *args, **kwargs: next(responses),
        ):
            report = run_academic_check(
                "张三",
                ["A Reliable Agent, ICSE 2024"],
                search_fn=lambda title, count=3: [_work_fact("A Reliable Agent")],
            )

        self.assertEqual(report.verified_count, 1)
        self.assertEqual(report.mismatch_count, 0)
        self.assertEqual(report.warnings, [])

    def test_resume_pipeline_checks_publications_for_advanced_stage(self) -> None:
        state = {
            "normalized": {
                "id": "c1",
                "name": "张三",
                "stage": "博士候选人",
                "publications": ["A Reliable Agent"],
                "raw_text": "A Reliable Agent",
            }
        }
        with patch("agi_talent_radar.agents.academic.nodes.run_academic_check") as check:
            check.return_value = AcademicReport(warnings=["mock"])
            result = run_resume_academic_check(state)

        check.assert_called_once()
        self.assertEqual(result["academic_report"]["warnings"], ["mock"])


if __name__ == "__main__":
    unittest.main()
