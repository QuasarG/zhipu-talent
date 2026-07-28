from agi_talent_radar.agents.tracks.safety.spec import SPEC
from agi_talent_radar.agents.tracks.shared.engine import apply_dimension_floors, run_track_chain
from agi_talent_radar.core.models import DimensionScore, EvidenceItem
from agi_talent_radar.agents.tracks.safety.weights import PORTFOLIO_FLOORS


def run_safety_track(state: dict) -> dict:
    return run_track_chain(state, SPEC, _calibrate_security_portfolio)


def _calibrate_security_portfolio(
    scores: list[DimensionScore],
    evidence: list[EvidenceItem],
) -> list[DimensionScore]:
    strong_sources = {item.source for item in evidence if item.strength >= 4 and item.source}
    owned = sum(item.has_ownership for item in evidence)
    tools = sum(item.has_specific_tool for item in evidence)
    published = sum(_is_published_result(item) for item in evidence)
    if len(strong_sources) < 6 or owned < 3 or tools < 1 or published < 2:
        return scores
    return apply_dimension_floors(
        scores,
        PORTFOLIO_FLOORS,
        "多项独立安全项目、可运行工具和至少两项正式发表成果交叉验证了成熟的安全研究组合",
    )


def _is_published_result(item: EvidenceItem) -> bool:
    text = " ".join([item.source, item.quote, *item.signals]).lower()
    return item.strength >= 4 and any(token in text for token in ("已发表", "已接收", "ccf-a", "journal"))
