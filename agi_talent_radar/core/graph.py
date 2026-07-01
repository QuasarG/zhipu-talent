from __future__ import annotations

from langgraph.graph import END, StateGraph

from agi_talent_radar.agents.critic import route_after_critic, run_critic
from agi_talent_radar.agents.evidence_extractor import run_evidence_extractor
from agi_talent_radar.agents.formatter import run_formatter
from agi_talent_radar.agents.normalizer import run_normalizer
from agi_talent_radar.agents.scorer import run_scorer
from agi_talent_radar.core.models import TalentState


NODE_LABELS = {
    "normalizer": "脱敏与标准化",
    "evidence_extractor": "深度证据挖掘",
    "scorer": "跨领域对齐打分",
    "critic": "逻辑判官与防幻觉",
    "formatter": "结构化组装",
}


def build_graph():
    workflow = StateGraph(TalentState)
    workflow.add_node("normalizer", run_normalizer)
    workflow.add_node("evidence_extractor", run_evidence_extractor)
    workflow.add_node("scorer", run_scorer)
    workflow.add_node("critic", run_critic)
    workflow.add_node("formatter", run_formatter)

    workflow.set_entry_point("normalizer")
    workflow.add_edge("normalizer", "evidence_extractor")
    workflow.add_edge("evidence_extractor", "scorer")
    workflow.add_edge("scorer", "critic")
    workflow.add_conditional_edges(
        "critic",
        route_after_critic,
        {
            "evidence_extractor": "evidence_extractor",
            "scorer": "scorer",
            "formatter": "formatter",
        },
    )
    workflow.add_edge("formatter", END)
    return workflow.compile()
