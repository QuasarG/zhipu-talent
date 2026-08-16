"""评分配置版本：任何影响分数的参数一变哈希就变，保证新旧评估分数的可比性可区分。

track 部分取自 JD 池当前 active 的 spec（key + spec_version + 维度权重），
JD 池变动即版本变动——同一版本的评估才可横向比较。
"""
from __future__ import annotations

import hashlib
import json

from agi_talent_radar.agents.common_potential.rubric import COMMON_RUBRIC
from agi_talent_radar.core.scoring_config import COMMON_WEIGHTS, DEFAULT as CFG, RAW_MAX


def _active_track_payload(session=None) -> dict:
    """当前 active track 的权重快照；调用方有 session 就复用（测试可传内存库）。"""
    from agi_talent_radar.agents.tracks.registry import load_active_specs
    from agi_talent_radar.core.db.repository import list_active_jds

    if session is not None:
        specs = load_active_specs(session)
        versions = {row.track_key: row.spec_version for row in list_active_jds(session)}
    else:
        from agi_talent_radar.core.db.runtime import get_session

        with get_session() as owned:
            specs = load_active_specs(owned)
            versions = {row.track_key: row.spec_version for row in list_active_jds(owned)}
    return {
        key: {"spec_version": versions.get(key, 0), "weights": {d.key: d.max_points for d in spec.dimensions}}
        for key, spec in sorted(specs.items())
    }


def _config_payload(tracks: dict) -> dict:
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
        "track_weights": tracks,
        "caps": caps,
        "portfolio_floors": floors,
        "bounds": bounds,
        "thresholds": thresholds,
    }


def current_scoring_version(session=None) -> str:
    tracks = _active_track_payload(session)
    payload = {
        "common": [[item.key, item.max_points] for item in COMMON_RUBRIC],
        "tracks": tracks,
        "config": _config_payload(tracks),
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    return f"scoring-{digest[:12]}"
