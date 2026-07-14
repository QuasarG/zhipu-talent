from agi_talent_radar.agents.tracks.agent.spec import SPEC
from agi_talent_radar.agents.tracks.shared.engine import run_track_chain


def run_agent_track(state: dict) -> dict:
    return run_track_chain(state, SPEC)
