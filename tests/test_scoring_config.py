from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch
import unittest

from agi_talent_radar.core import scoring_version
from agi_talent_radar.core.scoring_config import DEFAULT, AggregateBounds, LevelThresholds
from agi_talent_radar.agents.tracks.registry import specs_from_rows
from agi_talent_radar.agents.tracks.shared.spec import TrackDimensionSpec, TrackSpec
from tests.track_fixtures import make_spec


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
        # track 快照走 DB，测试里固定为空集，只验证配置项变更驱动版本号
        with patch.object(scoring_version, "_active_track_payload", return_value={}):
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

    def test_specs_from_rows_skips_broken_specs(self) -> None:
        """JD 池加载：合法 spec 解析成功，坏 JSON / 缺维度的条目跳过不拖死整池。"""
        good = SimpleNamespace(spec=json.dumps(make_spec("good_track").to_dict()))
        broken = SimpleNamespace(spec="{not json")
        empty = SimpleNamespace(spec=json.dumps({"key": "no_dims", "dimensions": []}))

        specs = specs_from_rows([good, broken, empty])

        self.assertEqual(set(specs), {"good_track"})
        self.assertEqual(specs["good_track"].max_points, 60)

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
