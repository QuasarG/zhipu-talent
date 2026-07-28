from agi_talent_radar.agents.tracks.agent.spec import SPEC
from agi_talent_radar.agents.tracks.shared.engine import apply_dimension_floors, run_track_chain
from agi_talent_radar.core.models import DimensionScore, EvidenceItem
from agi_talent_radar.agents.tracks.agent.weights import PORTFOLIO_FLOORS


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
        PORTFOLIO_FLOORS,
        "多项 Agent 研究工作、明确主要贡献和正式发表成果构成连续的专业证据链",
    )


def _is_published_result(item: EvidenceItem) -> bool:
    text = " ".join([item.source, item.quote, *item.signals]).lower()
    return item.strength >= 4 and any(token in text for token in ("已发表", "已接收", "ccf-a", "journal"))
