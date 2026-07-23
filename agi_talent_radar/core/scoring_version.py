"""评分配置版本：rubric 权重一变哈希就变，保证新旧评估分数的可比性可区分。"""
from __future__ import annotations

import hashlib
import json

from agi_talent_radar.agents.common_potential.rubric import COMMON_RUBRIC
from agi_talent_radar.agents.tracks.registry import TRACK_SPECS


def current_scoring_version() -> str:
    payload = {
        "common": [[item.key, item.max_points] for item in COMMON_RUBRIC],
        "tracks": {
            key: [[item.key, item.max_points] for item in spec.dimensions]
            for key, spec in sorted(TRACK_SPECS.items())
        },
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    return f"scoring-{digest[:12]}"
