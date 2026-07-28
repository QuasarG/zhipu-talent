"""评分配置版本：任何影响分数的参数一变哈希就变，保证新旧评估分数的可比性可区分。"""
from __future__ import annotations

import hashlib
import json

from agi_talent_radar.agents.common_potential.rubric import COMMON_RUBRIC
from agi_talent_radar.agents.tracks.registry import TRACK_SPECS
from agi_talent_radar.agents.tracks.agent.weights import PORTFOLIO_FLOORS as AGENT_PORTFOLIO_FLOORS
from agi_talent_radar.agents.tracks.safety.weights import PORTFOLIO_FLOORS as SAFETY_PORTFOLIO_FLOORS
from agi_talent_radar.core.scoring_config import COMMON_WEIGHTS, DEFAULT as CFG, RAW_MAX


def _config_payload() -> dict:
    """把所有影响分数的参数序列化成可哈希的 payload。"""
    caps = {"no_evidence": CFG.caps.no_evidence, "no_verification": CFG.caps.no_verification, "no_high_score_support": CFG.caps.no_high_score_support}
    floors = {
        "strong_sources_min": CFG.portfolio_floors.strong_sources_min,
        "owned_min": CFG.portfolio_floors.owned_min,
        "published_min": CFG.portfolio_floors.published_min,
        "floors": dict(sorted(CFG.portfolio_floors.floors.items())),
    }
    bounds = {
        "common_max": CFG.aggregate_bounds.common_max,
        "overall_min": CFG.aggregate_bounds.overall_min,
        "overall_max": CFG.aggregate_bounds.overall_max,
    }
    thresholds = {"s": CFG.thresholds.s, "a": CFG.thresholds.a, "b": CFG.thresholds.b}
    return {
        "raw_max": RAW_MAX,
        "common_weights": dict(sorted(COMMON_WEIGHTS.items())),
        "track_weights": {
            key: {item.key: item.max_points for item in spec.dimensions}
            for key, spec in sorted(TRACK_SPECS.items())
        },
        "track_portfolio_floors": {
            "agent": dict(sorted(AGENT_PORTFOLIO_FLOORS.items())),
            "safety": dict(sorted(SAFETY_PORTFOLIO_FLOORS.items())),
        },
        "caps": caps,
        "portfolio_floors": floors,
        "bounds": bounds,
        "thresholds": thresholds,
    }


def current_scoring_version() -> str:
    payload = {
        "common": [[item.key, item.max_points] for item in COMMON_RUBRIC],
        "tracks": {
            key: [[item.key, item.max_points] for item in spec.dimensions]
            for key, spec in sorted(TRACK_SPECS.items())
        },
        "config": _config_payload(),
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    return f"scoring-{digest[:12]}"
