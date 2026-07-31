from __future__ import annotations

from dataclasses import replace
import unittest

from agi_talent_radar.core import scoring_version
from agi_talent_radar.core.scoring_config import DEFAULT, AggregateBounds, LevelThresholds
from agi_talent_radar.agents.tracks.registry import TRACK_SPECS
from agi_talent_radar.agents.tracks.shared.spec import TrackDimensionSpec, TrackSpec


class ScoringConfigTest(unittest.TestCase):
    def test_weighted_score_and_pool_thresholds_share_one_rule(self) -> None:
        self.assertEqual(DEFAULT.weighted_score(2.5, 8), 4.0)
        self.assertEqual(DEFAULT.thresholds.pool_for_score(80), "shortlisted")
        self.assertEqual(DEFAULT.thresholds.pool_for_score(60), "alternative")
        self.assertEqual(DEFAULT.thresholds.pool_for_score(59), "rejected")
        self.assertEqual(
            DEFAULT.thresholds.routing_note(),
            "80 分及以上进入优选库，60-79 分进入备选库，低于 60 分进入不建议后续沟通。",
        )

    def test_scoring_version_covers_bounds_and_thresholds(self) -> None:
        original = scoring_version.CFG
        before = scoring_version.current_scoring_version()
        try:
            scoring_version.CFG = replace(
                original,
                aggregate_bounds=AggregateBounds(
                    common_max=original.aggregate_bounds.common_max,
                    overall_min=1.0,
                    overall_max=original.aggregate_bounds.overall_max,
                ),
                thresholds=LevelThresholds(s=91, a=81, b=61),
            )
            self.assertNotEqual(before, scoring_version.current_scoring_version())
        finally:
            scoring_version.CFG = original

    def test_track_specs_explicitly_use_local_weight_data(self) -> None:
        self.assertEqual(TRACK_SPECS["agent"].dimensions[0].max_points, 8)
        self.assertEqual(
            {key: spec.max_points for key, spec in TRACK_SPECS.items()},
            {
                "agent": 60,
                "ai4science": 60,
                "base": 60,
                "multimodal": 60,
                "safety": 60,
                "ai_infra": 60,
            },
        )

    def test_track_spec_preserves_explicit_dimension_weights(self) -> None:
        spec = TrackSpec(
            key="agent",
            label="测试",
            dimensions=(TrackDimensionSpec("custom", "自定义", 7, "测试规则"),),
            evidence_focus="测试",
            high_score_rule="测试",
        )
        self.assertEqual(spec.dimensions[0].max_points, 7)


if __name__ == "__main__":
    unittest.main()
