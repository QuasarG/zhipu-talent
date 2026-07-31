from __future__ import annotations

import unittest
from unittest.mock import patch

from agi_talent_radar.agents.academic.models import AcademicReport, PaperClaim
from agi_talent_radar.agents.academic.nodes import align_claims, extract_claims, lookup_claim, run_academic_check, run_resume_academic_check
from agi_talent_radar.agents.academic import nodes as academic_nodes
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
                {"claim_title": "Paper A", "verdict": "verified", "matched_title": "Paper A",
                 "candidate_author_position": 1, "candidate_author_name": "San Zhang",
                 "cited_by_count": 5, "openalex_url": "https://openalex.org/W1"},
                {"claim_title": "Paper B", "verdict": "not_a_verdict"},
            ]
        }
        # Paper A 提供真实候选记录，B 不提供（测 unverifiable 降级）
        candidate_a = {"title": "Paper A", "authors": ["San Zhang"], "source_url": "https://openalex.org/W1"}
        with patch("agi_talent_radar.agents.academic.nodes.llm_client.call_llm_json", return_value=llm_response):
            alignments = align_claims("张三", claims, [[candidate_a], []])

        self.assertEqual(alignments[0].verdict, "verified")
        self.assertEqual(alignments[0].cited_by_count, 5)
        self.assertEqual(alignments[1].verdict, "unverifiable")

    def test_author_position_mismatch_for_false_first_author(self) -> None:
        """复刻截图 bug：声称一作，实际排第 3，必须判 mismatch。"""
        claim = PaperClaim(
            title="Synergizing RAG and Reasoning",
            claimed_role="一作",
            claimed_status="已发表",
        )
        # authors 列表里候选人在第 3 位（截图真实场景）
        candidate = {
            "title": "Synergizing RAG and Reasoning",
            "authors": ["Yunfan Gao", "Yun Xiong", "San Zhang", "Xingzu Wang"],
            "source": "aminer",
            "source_url": "https://www.aminer.cn/pub/xxx",
        }
        # 即使 LLM 被误导标了 verified，后端必须纠正
        response = {
            "alignments": [{
                "claim_title": "Synergizing RAG and Reasoning",
                "verdict": "verified",
                "matched_title": "Synergizing RAG and Reasoning",
                "candidate_author_position": 3,
                "candidate_author_name": "San Zhang",
                "author_position_match": "match",  # LLM 误判
                "discrepancies": [],
            }]
        }
        with patch(
            "agi_talent_radar.agents.academic.nodes.llm_client.call_llm_json",
            return_value=response,
        ):
            alignment = align_claims("San Zhang", [claim], [[candidate]])[0]

        self.assertEqual(alignment.candidate_author_position, 3)
        self.assertEqual(alignment.candidate_author_name, "San Zhang")
        self.assertEqual(alignment.checks.author_position, "mismatch")
        self.assertEqual(alignment.verdict, "mismatch")  # 联动 verdict 强制 mismatch
        self.assertTrue(any("第 3 作者" in d for d in alignment.discrepancies))

    def test_author_position_match_for_real_first_author(self) -> None:
        """真一作：position=1，author_position=match，verdict 不受影响。"""
        claim = PaperClaim(
            title="Real First Author Paper",
            claimed_role="一作",
            claimed_status="已发表",
        )
        candidate = {
            "title": "Real First Author Paper",
            "authors": ["San Zhang", "Li Si", "Wang Wu"],
            "source": "aminer",
        }
        response = {
            "alignments": [{
                "claim_title": "Real First Author Paper",
                "verdict": "verified",
                "matched_title": "Real First Author Paper",
                "candidate_author_position": 1,
                "candidate_author_name": "San Zhang",
                "author_position_match": "match",
            }]
        }
        with patch(
            "agi_talent_radar.agents.academic.nodes.llm_client.call_llm_json",
            return_value=response,
        ):
            alignment = align_claims("张三", [claim], [[candidate]])[0]

        self.assertEqual(alignment.candidate_author_position, 1)
        self.assertEqual(alignment.checks.author_position, "match")
        self.assertEqual(alignment.checks.author_identity, "match")
        self.assertEqual(alignment.verdict, "verified")

    def test_position_check_preserved_when_llm_says_verified(self) -> None:
        """专治 bug 源头：LLM 标 verified 但位次不符，后端强制 mismatch，
        旧逻辑 _inferred_check 会把 author_position 无脑映射成 match。"""
        claim = PaperClaim(
            title="AnimeAgent",
            claimed_role="第一作者",  # 测角色措辞归一（第一作者 → 一作）
            claimed_status="在审",
        )
        candidate = {
            "title": "AnimeAgent",
            "authors": ["Hailong Yan", "Shice Liu", "Tao Wang", "Xiangtao Zhang", "San Zhang"],
        }
        response = {
            "alignments": [{
                "claim_title": "AnimeAgent",
                "verdict": "verified",  # LLM 误判
                "matched_title": "AnimeAgent",
                "candidate_author_position": 5,
                "candidate_author_name": "San Zhang",
            }]
        }
        with patch(
            "agi_talent_radar.agents.academic.nodes.llm_client.call_llm_json",
            return_value=response,
        ):
            alignment = align_claims("San Zhang", [claim], [[candidate]])[0]

        self.assertEqual(alignment.checks.author_position, "mismatch")
        self.assertEqual(alignment.verdict, "mismatch")  # 旧逻辑这里会保持 verified
        self.assertTrue(any("第 5 作者" in d for d in alignment.discrepancies))

    def test_candidate_position_zero_when_author_not_found(self) -> None:
        """authors 里找不到候选人 → position=0、author_identity=mismatch、verdict=mismatch。"""
        claim = PaperClaim(
            title="Ghost Paper",
            claimed_role="一作",
            claimed_status="已发表",
        )
        candidate = {
            "title": "Ghost Paper",
            "authors": ["Alice", "Bob", "Charlie"],  # 没有候选人
        }
        response = {
            "alignments": [{
                "claim_title": "Ghost Paper",
                "verdict": "verified",
                "matched_title": "Ghost Paper",
                "candidate_author_position": 0,
                "candidate_author_name": "",
            }]
        }
        with patch(
            "agi_talent_radar.agents.academic.nodes.llm_client.call_llm_json",
            return_value=response,
        ):
            alignment = align_claims("张三", [claim], [[candidate]])[0]

        self.assertEqual(alignment.candidate_author_position, 0)
        self.assertEqual(alignment.candidate_author_name, "")
        self.assertEqual(alignment.checks.author_identity, "mismatch")
        self.assertEqual(alignment.checks.author_position, "mismatch")
        self.assertEqual(alignment.verdict, "mismatch")  # 身份不符=硬冲突
        self.assertTrue(any("无候选人" in d for d in alignment.discrepancies))

    def test_no_match_yields_pending_checks_and_unverifiable(self) -> None:
        """检索不到论文 → 作者维度 pending（非 mismatch），verdict=unverifiable。"""
        claim = PaperClaim(title="Phantom Paper", claimed_role="一作", claimed_status="已发表")
        response = {"alignments": [{"claim_title": "Phantom Paper", "verdict": "verified", "matched_title": ""}]}
        with patch("agi_talent_radar.agents.academic.nodes.llm_client.call_llm_json", return_value=response):
            alignment = align_claims("张三", [claim], [[]])[0]  # 无候选记录

        self.assertEqual(alignment.verdict, "unverifiable")
        self.assertEqual(alignment.checks.title, "pending")
        self.assertEqual(alignment.checks.author_identity, "pending")
        self.assertEqual(alignment.checks.author_position, "pending")
        self.assertEqual(alignment.checks.publication_status, "pending")

    def test_align_claims_returns_structured_external_record_and_checks(self) -> None:
        claim = PaperClaim(
            title="GlassWing",
            venue="ASE",
            year="2025",
            claimed_role="第一作者",
            claimed_status="已发表",
        )
        candidate = {
            "title": "GlassWing",
            "authors": ["Xiangyu Zhang", "Lingling Fan"],
            "venue": "ASE",
            "year": 2025,
            "source": "aminer",
            "source_url": "https://www.aminer.cn/pub/paper-id",
        }
        response = {
            "alignments": [{
                "claim_title": "GlassWing",
                "verdict": "verified",
                "verified_status": "已发表",
                "matched_title": "GlassWing",
                "candidate_author_position": 1,
                "candidate_author_name": "Xiangyu Zhang",
                "title_match": "match",
                "author_identity_match": "match",
                "author_position_match": "match",
                "publication_status_match": "match",
            }]
        }

        with patch(
            "agi_talent_radar.agents.academic.nodes.llm_client.call_llm_json",
            return_value=response,
        ):
            alignment = align_claims("张向宇", [claim], [[candidate]])[0]

        self.assertEqual(alignment.external_record.source, "aminer")
        self.assertEqual(alignment.external_record.authors, ["Xiangyu Zhang", "Lingling Fan"])
        self.assertEqual(alignment.external_record.year, "2025")
        self.assertEqual(alignment.candidate_author_position, 1)
        self.assertEqual(alignment.candidate_author_name, "Xiangyu Zhang")
        self.assertEqual(alignment.checks.author_position, "match")
        self.assertEqual(alignment.checks.publication_status, "match")

    def test_run_academic_check_end_to_end_with_mocks(self) -> None:
        extract_response = {
            "claims": [
                {"title": "A Reliable Agent", "venue": "ICSE", "year": "2024", "claimed_role": "一作", "claimed_status": "已发表"}
            ]
        }
        align_response = {
            "alignments": [
                {
                    "claim_title": "A Reliable Agent",
                    "verdict": "verified",
                    "matched_title": "A Reliable Agent",
                    "cited_by_count": 3,
                    "openalex_url": "https://openalex.org/W1",
                    "candidate_author_position": 1,
                    "candidate_author_name": "San Zhang",
                }
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

    def test_run_academic_check_uses_aminer_first_search_by_default(self) -> None:
        claim = PaperClaim(title="GlassWing", claimed_status="已发表")
        alignment = academic_nodes.ClaimAlignment(
            claim=claim,
            verdict="verified",
            matched_title="GlassWing",
            openalex_url="https://www.aminer.cn/pub/paper-id",
        )
        with (
            patch("agi_talent_radar.agents.academic.nodes.extract_claims", return_value=[claim]),
            patch("agi_talent_radar.agents.academic.nodes.lookup_claim", return_value=([], None)) as lookup,
            patch("agi_talent_radar.agents.academic.nodes.align_claims", return_value=[alignment]),
        ):
            report = run_academic_check("张向宇", ["GlassWing"])

        self.assertIs(lookup.call_args.kwargs["search_fn"], academic_nodes.search_papers)
        self.assertEqual(report.alignments[0].openalex_url, "https://www.aminer.cn/pub/paper-id")

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

    def test_resume_pipeline_preserves_preloaded_academic_report(self) -> None:
        report = {
            "alignments": [
                {
                    "claim": {"title": "A Reliable Agent"},
                    "verdict": "mismatch",
                    "discrepancies": ["作者列表中没有候选人"],
                }
            ],
            "warnings": [],
        }
        state = {
            "normalized": {
                "id": "c1",
                "name": "张三",
                "stage": "博士候选人",
                "publications": ["A Reliable Agent"],
                "raw_text": "A Reliable Agent",
            },
            "academic_report": report,
        }

        with patch("agi_talent_radar.agents.academic.nodes.run_academic_check") as check:
            result = run_resume_academic_check(state)

        check.assert_not_called()
        self.assertEqual(result["academic_report"], report)

    def test_llm_position_trusted_but_role_conflict_detected(self) -> None:
        """作者消歧全权交给 LLM：LLM 报位次+名字自洽即信任，后端只做位次/角色联动。

        LLM 把候选人定位到第 6 位（Haofen Wang 位置），claim 却声称一作 →
        verdict 联动 mismatch；幻觉位次文案被 _derive_discrepancies 清掉。
        """
        claim = PaperClaim(
            title="U-NiAH",
            claimed_role="一作",
            claimed_status="已发表",
        )
        candidate = {
            "title": "U-NiAH",
            "authors": ["Yunfan Gao", "Yun Xiong", "Wenlong Wu", "Zijing Huang", "Bohan Li", "Haofen Wang"],
        }
        response = {
            "alignments": [{
                "claim_title": "U-NiAH",
                "verdict": "verified",
                "matched_title": "U-NiAH",
                "candidate_author_position": 6,
                "candidate_author_name": "Haofen Wang",
                "discrepancies": ["声称一作，实际为第 5 作者"],  # LLM 写错位次（5 vs 实际6）
            }]
        }
        with patch(
            "agi_talent_radar.agents.academic.nodes.llm_client.call_llm_json",
            return_value=response,
        ):
            alignment = align_claims("San Zhang", [claim], [[candidate]])[0]

        # LLM 报的位次 6 处确实是 Haofen Wang，名字自洽 → 信任位次 6
        self.assertEqual(alignment.candidate_author_position, 6)
        # 一作声称但实际第 6 位 → mismatch
        self.assertEqual(alignment.checks.author_position, "mismatch")
        self.assertEqual(alignment.verdict, "mismatch")
        # discrepancies 被 _derive_discrepancies 用后端权威结论覆盖
        self.assertTrue(any("第 6 作者" in d for d in alignment.discrepancies))


if __name__ == "__main__":
    unittest.main()
