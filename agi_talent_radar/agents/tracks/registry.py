from __future__ import annotations

from collections.abc import Callable

from agi_talent_radar.agents.tracks.agent import run_agent_track
from agi_talent_radar.agents.tracks.agent import SPEC as AGENT_SPEC
from agi_talent_radar.agents.tracks.ai4science import run_ai4science_track
from agi_talent_radar.agents.tracks.ai4science import SPEC as AI4SCIENCE_SPEC
from agi_talent_radar.agents.tracks.base import run_base_track
from agi_talent_radar.agents.tracks.base import SPEC as BASE_SPEC
from agi_talent_radar.agents.tracks.multimodal import run_multimodal_track
from agi_talent_radar.agents.tracks.multimodal import SPEC as MULTIMODAL_SPEC
from agi_talent_radar.agents.tracks.safety import run_safety_track
from agi_talent_radar.agents.tracks.safety import SPEC as SAFETY_SPEC
from agi_talent_radar.agents.tracks.shared.spec import TrackSpec
from agi_talent_radar.agents.tracks.systems import run_systems_track
from agi_talent_radar.agents.tracks.systems import SPEC as SYSTEMS_SPEC
from agi_talent_radar.core.models import TrackKey


TRACK_SPECS: dict[TrackKey, TrackSpec] = {
    spec.key: spec
    for spec in [BASE_SPEC, AGENT_SPEC, SAFETY_SPEC, MULTIMODAL_SPEC, SYSTEMS_SPEC, AI4SCIENCE_SPEC]
}

TRACK_RUNNERS: dict[TrackKey, Callable[[dict], dict]] = {
    "base": run_base_track,
    "agent": run_agent_track,
    "safety": run_safety_track,
    "multimodal": run_multimodal_track,
    "systems": run_systems_track,
    "ai4science": run_ai4science_track,
}
