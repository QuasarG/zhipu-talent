"""identity_service.resolve_intake_identity 单元测试。

覆盖：

1. 稳定标识（orcid / aminer_id / email）单一命中 → MATCHED + 自动归并。
2. 稳定标识同时指向多个 person → CONFLICT，阻止合并。
3. 仅姓名变体命中单候选 → NEEDS_REVIEW（不自动合并）。
4. 仅姓名变体命中多候选 → CONFLICT。
5. 无任何匹配 → NEW。
6. emails 列表兜底也能被第一层命中。
7. 回调注入：可完全替换数据库访问，不依赖真实 engine。
"""
from __future__ import annotations

import unittest

from agi_talent_radar.core.db.orm import PersonORM
from agi_talent_radar.core.domain_models import (
    IdentityDecision,
    IdentityEvidence,
)
from agi_talent_radar.services import identity_service


def _person(person_id: str, name: str = "", org: str = "", direction: str = "") -> PersonORM:
    return PersonORM(
        id=person_id,
        name=name,
        org=org,
        direction=direction,
        fingerprint=f"fp-{person_id}",
    )


class TestStableIdMatching(unittest.TestCase):
    def test_single_orcid_match(self) -> None:
        person_a = _person("p-a", name="张三")
        evidence = IdentityEvidence(stable_ids={"orcid": "0000-0001-2345-6789"})

        result = identity_service.resolve_intake_identity(
            evidence,
            find_person_by_identifier=lambda kind, value: person_a if (kind, value) == ("orcid", "0000-0001-2345-6789") else None,
            find_person_by_fingerprint=lambda *_: None,
        )
        self.assertEqual(result.decision, IdentityDecision.MATCHED)
        self.assertEqual(result.matched_person_id, "p-a")
        self.assertGreater(result.confidence, 0.9)
        self.assertFalse(result.conflicts)

    def test_multiple_persons_on_same_stable_id_set_is_conflict(self) -> None:
        """不同稳定标识同时命中两个 person → CONFLICT。"""
        person_a = _person("p-a", name="张三")
        person_b = _person("p-b", name="李四")
        evidence = IdentityEvidence(
            stable_ids={
                "orcid": "0000-0001-2345-6789",
                "aminer_id": "A123",
            }
        )

        def finder(kind: str, value: str):
            if (kind, value) == ("orcid", "0000-0001-2345-6789"):
                return person_a
            if (kind, value) == ("aminer_id", "a123"):
                return person_b
            return None

        result = identity_service.resolve_intake_identity(
            evidence,
            find_person_by_identifier=finder,
            find_person_by_fingerprint=lambda *_: None,
        )
        self.assertEqual(result.decision, IdentityDecision.CONFLICT)
        self.assertIsNone(result.matched_person_id)
        self.assertTrue(result.conflicts)

    def test_emails_list_falls_back_to_first_layer(self) -> None:
        """evidence.emails 列表作为 email 稳定标识兜底。"""
        person_a = _person("p-a")
        evidence = IdentityEvidence(emails=["zhang3@example.com"])

        result = identity_service.resolve_intake_identity(
            evidence,
            find_person_by_identifier=lambda kind, value: person_a if value == "zhang3@example.com" else None,
            find_person_by_fingerprint=lambda *_: None,
        )
        self.assertEqual(result.decision, IdentityDecision.MATCHED)
        self.assertEqual(result.matched_person_id, "p-a")


class TestFuzzyMatching(unittest.TestCase):
    def test_single_name_variant_candidate_is_needs_review(self) -> None:
        """姓名变体命中单候选 → NEEDS_REVIEW，不自动合并。"""
        candidate = _person("p-fuzzy", name="张三", org="某大学", direction="Agent")
        evidence = IdentityEvidence(name_variants=["张三", "San Zhang"])

        result = identity_service.resolve_intake_identity(
            evidence,
            find_person_by_identifier=lambda *_: None,
            find_person_by_fingerprint=lambda name, *_: candidate if name == "张三" else None,
        )
        self.assertEqual(result.decision, IdentityDecision.NEEDS_REVIEW)
        self.assertEqual(result.matched_person_id, "p-fuzzy")
        # 不应是 0.9 以上（非确定性）
        self.assertLess(result.confidence, 0.9)

    def test_multiple_name_candidates_is_conflict(self) -> None:
        candidate_a = _person("p-a", name="张三")
        candidate_b = _person("p-b", name="张三")
        evidence = IdentityEvidence(name_variants=["张三"])

        def finder(name: str, *_):
            if name == "张三":
                return candidate_a  # 只返回第一个；测试通过两个变体触发多候选
            return None

        evidence_two = IdentityEvidence(name_variants=["张三", "张 三"])
        # 故意构造：两个变体返回不同 person
        def finder_multi(name: str, *_):
            if name == "张三":
                return candidate_a
            if name == "张 三":
                return candidate_b
            return None

        result = identity_service.resolve_intake_identity(
            evidence_two,
            find_person_by_identifier=lambda *_: None,
            find_person_by_fingerprint=finder_multi,
        )
        self.assertEqual(result.decision, IdentityDecision.CONFLICT)
        self.assertTrue(result.conflicts)

    def test_no_match_is_new(self) -> None:
        evidence = IdentityEvidence(name_variants=["不存在的人"])
        result = identity_service.resolve_intake_identity(
            evidence,
            find_person_by_identifier=lambda *_: None,
            find_person_by_fingerprint=lambda *_: None,
        )
        self.assertEqual(result.decision, IdentityDecision.NEW)
        self.assertIsNone(result.matched_person_id)

    def test_empty_name_variants_skips_fuzzy_layer(self) -> None:
        evidence = IdentityEvidence(name_variants=[])
        result = identity_service.resolve_intake_identity(
            evidence,
            find_person_by_identifier=lambda *_: None,
            find_person_by_fingerprint=lambda *_: None,
        )
        self.assertEqual(result.decision, IdentityDecision.NEW)


class TestDefaultAiMatcherDedupCandidates(unittest.TestCase):
    def test_same_person_returned_by_two_variants_is_single_candidate(self) -> None:
        """同一 person 被多个姓名变体命中时，去重后仍为单候选 → NEEDS_REVIEW。"""
        person = _person("p-single", name="张三")
        evidence = IdentityEvidence(name_variants=["张三", "San Zhang"])
        result = identity_service.resolve_intake_identity(
            evidence,
            find_person_by_identifier=lambda *_: None,
            find_person_by_fingerprint=lambda *_: person,
        )
        self.assertEqual(result.decision, IdentityDecision.NEEDS_REVIEW)
        self.assertEqual(result.matched_person_id, "p-single")


class TestCustomAiMatcherInjection(unittest.TestCase):
    def test_custom_ai_matcher_overrides_default(self) -> None:
        person = _person("p-custom", name="张三")
        evidence = IdentityEvidence(name_variants=["张三"])

        def custom_matcher(ev, candidates):
            return identity_service.IdentityResolution(
                matched_person_id=person.id,
                decision=IdentityDecision.MATCHED,
                confidence=0.99,
                supporting_evidence=["自定义匹配器：姓名+机构相符"],
                conflicts=[],
            )

        result = identity_service.resolve_intake_identity(
            evidence,
            find_person_by_identifier=lambda *_: None,
            find_person_by_fingerprint=lambda *_: person,
            ai_matcher=custom_matcher,
        )
        self.assertEqual(result.decision, IdentityDecision.MATCHED)
        self.assertEqual(result.confidence, 0.99)


if __name__ == "__main__":
    unittest.main()