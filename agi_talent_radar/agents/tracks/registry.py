"""Track 注册表：JD 池驱动的动态 spec 加载。

旧的 6 个硬编码 track（base/agent/safety/...）已废弃：spec 由 JD 池条目携带
（LLM 起草、人批激活），评估时从 DB 实时加载，JD 池变动即 track 集合变动。
"""
from __future__ import annotations

import json

from agi_talent_radar.agents.tracks.shared.spec import TrackSpec


def specs_from_rows(rows) -> dict[str, TrackSpec]:
    """把 JD 条目行解析成 {track_key: TrackSpec}，坏 spec 跳过（不拖死整池）。"""
    result: dict[str, TrackSpec] = {}
    for row in rows:
        try:
            spec = TrackSpec.from_dict(json.loads(row.spec))
        except (json.JSONDecodeError, TypeError, ValueError, AttributeError):
            continue
        if spec.key and spec.dimensions:
            result[spec.key] = spec
    return result


def load_active_specs(session=None) -> dict[str, TrackSpec]:
    """加载 JD 池中 active 条目的 track spec；不传 session 时自开自关。"""
    from agi_talent_radar.core.db.repository import list_active_jds

    if session is not None:
        return specs_from_rows(list_active_jds(session))
    from agi_talent_radar.core.db.runtime import get_session

    with get_session() as owned:
        return specs_from_rows(list_active_jds(owned))
