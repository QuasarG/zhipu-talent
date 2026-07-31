from agi_talent_radar.agents.tracks.shared.engine import run_track_chain
from agi_talent_radar.agents.tracks.ai_infra.spec import SPEC


def run_ai_infra_track(state: dict) -> dict:
    return run_track_chain(state, SPEC)
