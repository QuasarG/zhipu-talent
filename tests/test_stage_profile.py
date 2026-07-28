from __future__ import annotations

import unittest

from agi_talent_radar.agents.common_potential.nodes import _has_stage_appropriate_verification
from agi_talent_radar.core.models import EvidenceItem
from agi_talent_radar.core.stage_profile import ADVANCED, EARLY, profile_for_stage


class StageProfileTest(unittest.TestCase):
    def test_normalizes_common_early_and_advanced_stage_descriptions(self) -> None:
        self.assertEqual(profile_for_stage("博士一年级").key, "early")
        self.assertEqual(profile_for_stage("大三").key, "early")
        self.assertEqual(profile_for_stage("博士候选人").key, "advanced")

    def test_early_owned_project_can_satisfy_stage_appropriate_verification(self) -> None:
        evidence = [
            EvidenceItem(
                id="e1",
                dimension="track_specific",
                source="项目",
                quote="独立设计项目原型",
                strength=3,
                has_ownership=True,
            ),
            EvidenceItem(
                id="e2",
                dimension="track_specific",
                source="项目二",
                quote="负责实现核心模块",
                strength=3,
                has_ownership=True,
            )
        ]
        self.assertTrue(_has_stage_appropriate_verification(evidence, EARLY))
        self.assertFalse(_has_stage_appropriate_verification(evidence, ADVANCED))


if __name__ == "__main__":
    unittest.main()
