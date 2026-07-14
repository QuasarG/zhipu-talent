from agi_talent_radar.agents.tracks.agent.spec import SPEC
from agi_talent_radar.agents.tracks.shared.engine import apply_dimension_floors, run_track_chain
from agi_talent_radar.core.models import DimensionScore, EvidenceItem


def run_agent_track(state: dict) -> dict:
    return run_track_chain(state, SPEC, _calibrate_agent_portfolio)


def _calibrate_agent_portfolio(
    scores: list[DimensionScore],
    evidence: list[EvidenceItem],
) -> list[DimensionScore]:
    strong_sources = {item.source for item in evidence if item.strength >= 4 and item.source}
    owned = sum(item.has_ownership for item in evidence)
    published = sum(_is_published_result(item) for item in evidence)
    if len(strong_sources) < 3 or owned < 2 or published < 1:
        return scores
    return apply_dimension_floors(
        scores,
        {
            "task_environment": 3.5,
            "agent_method": 3.5,
            "tool_action_loop": 3.0,
            "verification_reliability": 2.5,
            "agent_system": 3.0,
            "agent_research_impact": 4.0,
        },
        "多项 Agent 研究工作、明确主要贡献和正式发表成果构成连续的专业证据链",
    )


def _is_published_result(item: EvidenceItem) -> bool:
    text = " ".join([item.source, item.quote, *item.signals]).lower()
    return item.strength >= 4 and any(token in text for token in ("已发表", "已接收", "ccf-a", "journal"))
