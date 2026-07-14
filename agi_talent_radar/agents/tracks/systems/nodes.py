from agi_talent_radar.agents.tracks.shared.engine import run_track_chain
from agi_talent_radar.agents.tracks.systems.spec import SPEC


def run_systems_track(state: dict) -> dict:
    return run_track_chain(state, SPEC)
