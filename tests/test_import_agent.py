from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from agi_talent_radar.core.import_agent import run_import_agent_stream
from agi_talent_radar.core.models import CandidateResume


class ImportIdentityDecisionTest(unittest.TestCase):
    def test_initial_screening_agent_can_reuse_existing_candidate(self) -> None:
        output = {
            "id": "incoming-resume",
            "name": "张向宇",
            "target_role": "Agent 研究员",
            "stage": "博四",
            "category": "Agent / 工具杠杆型",
            "confidence": 0.93,
            "reason": "研究与工程证据完整",
            "identity_decision": "same_person",
            "matched_candidate_id": "candidate-existing",
            "identity_confidence": 0.96,
            "identity_evidence": ["教育时间线一致", "论文与项目经历一致"],
            "identity_conflicts": [],
        }
        resume = CandidateResume(id="incoming-resume", name="张向宇", raw_text="简历")
        existing = [{"id": "candidate-existing", "name": "张向宇"}]

        with patch(
            "agi_talent_radar.core.import_agent.llm_client.call_llm_stream",
            return_value=iter([json.dumps(output, ensure_ascii=False) + "\n"]),
        ):
            result = list(
                run_import_agent_stream(
                    [resume],
                    persist=False,
                    identity_candidates=existing,
                )
            )[0]

        self.assertEqual(result.identity_decision, "same_person")
        self.assertEqual(result.matched_candidate_id, "candidate-existing")
        self.assertEqual(result.identity_evidence, ["教育时间线一致", "论文与项目经历一致"])

    def test_agent_cannot_reference_unknown_candidate(self) -> None:
        output = {
            "id": "incoming-resume",
            "name": "张向宇",
            "category": "研究探索型",
            "confidence": 0.8,
            "reason": "研究经历完整",
            "identity_decision": "same_person",
            "matched_candidate_id": "invented-id",
            "identity_confidence": 0.9,
        }
        resume = CandidateResume(id="incoming-resume", name="张向宇")

        with patch(
            "agi_talent_radar.core.import_agent.llm_client.call_llm_stream",
            return_value=iter([json.dumps(output, ensure_ascii=False) + "\n"]),
        ):
            with self.assertRaisesRegex(ValueError, "未知 matched_candidate_id"):
                list(
                    run_import_agent_stream(
                        [resume],
                        persist=False,
                        identity_candidates=[{"id": "candidate-existing"}],
                    )
                )


if __name__ == "__main__":
    unittest.main()
