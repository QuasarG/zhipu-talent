"""safety_net 与 evidence_extractor 的最小 happy-path 契约测试。

此前这两个评估链关键节点零测试（审计发现）；这里只验证契约面：
- safety_net：空简历短路；LLM 失败兜底为零分；正常路径聚合加分与上限。
- evidence_extractor：LLM 返回证据后 model 校验 + integrity flags 产出。
"""
from __future__ import annotations

import unittest
from unittest.mock import patch


# 字段名对齐 run_safety_net 真实读取：bonus/description/evidence_quote/rationale
SAFETY_BONUSES = {
    "bonuses": [
        {"description": "高考省状元", "evidence_quote": "全省第 1 名", "bonus": 2, "rationale": "可核验"},
        {"description": "ACM 区域赛金牌", "evidence_quote": "金牌", "bonus": 2, "rationale": "可核验"},
        {"description": "开源项目高 Star", "evidence_quote": "GitHub 12k stars", "bonus": 2, "rationale": "可核验"},
    ]
}


class SafetyNetTest(unittest.TestCase):
    def test_empty_resume_short_circuits(self) -> None:
        from agi_talent_radar.agents.safety_net import run_safety_net

        out = run_safety_net({"resume": {"raw_text": "  "}})
        self.assertEqual(out["safety_net_bonuses"], [])
        self.assertEqual(out["safety_net_score"], 0.0)

    def test_llm_failure_falls_back_to_zero(self) -> None:
        from agi_talent_radar.agents.safety_net import run_safety_net

        with patch("agi_talent_radar.agents.safety_net.llm_client.call_llm_json", side_effect=RuntimeError("boom")):
            out = run_safety_net({"resume": {"raw_text": "有内容"}, "track_results": []})
        self.assertEqual(out["safety_net_score"], 0.0)

    def test_aggregates_and_caps_total(self) -> None:
        from agi_talent_radar.agents.safety_net import run_safety_net

        with patch("agi_talent_radar.agents.safety_net.llm_client.call_llm_json", return_value=SAFETY_BONUSES):
            out = run_safety_net(
                {"resume": {"raw_text": "有内容"}, "common_score": 80, "track_results": []}
            )
        # 单条 ≤2，三条 2+2+2=6 → 总分封顶 5
        self.assertLessEqual(out["safety_net_score"], 5.0)
        self.assertGreater(len(out["safety_net_bonuses"]), 0)


class EvidenceExtractorTest(unittest.TestCase):
    def _normalized(self) -> dict:
        from agi_talent_radar.core.models import NormalizedResume

        return NormalizedResume(
            id="r1",
            raw_text="负责 PyTorch 训练管线优化，吞吐提升 30%",
            name="候选人",
            target_role="AI 研究员",
            stage="硕士在读",
        ).model_dump()

    def test_happy_path_validates_and_flags(self) -> None:
        from agi_talent_radar.agents.evidence_extractor import run_evidence_extractor

        llm_out = {
            "evidence": [
                {
                    "id": "e001",
                    "dimension": "engineering_practice",
                    "source": "experience",
                    "quote": "吞吐提升 30%",
                    "signals": ["量化结果"],
                    "strength": 3,
                    "has_metric": True,
                    "has_specific_tool": True,
                    "has_ownership": False,
                    "track_hints": [],
                    "page": None,
                    "bbox": [],
                    "extraction_confidence": 0.9,
                }
            ]
        }
        with patch("agi_talent_radar.agents.evidence_extractor.llm_client.call_llm_json", return_value=llm_out):
            out = run_evidence_extractor({"normalized": self._normalized()})
        self.assertEqual(len(out["evidence"]), 1)
        self.assertIn("evidence_integrity_flags", out)


if __name__ == "__main__":
    unittest.main()
