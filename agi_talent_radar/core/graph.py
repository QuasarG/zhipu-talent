from __future__ import annotations

from langgraph.graph import END, StateGraph

from agi_talent_radar.agents.aggregation import run_global_critic, run_portfolio_aggregator
from agi_talent_radar.agents.academic.nodes import run_resume_academic_check
from agi_talent_radar.agents.common_potential import run_common_critic, run_common_scorer
from agi_talent_radar.agents.evidence_extractor import run_evidence_extractor
from agi_talent_radar.agents.formatter import run_formatter
from agi_talent_radar.agents.normalizer import run_normalizer
from agi_talent_radar.agents.routing import run_route_auditor, run_track_router
from agi_talent_radar.agents.tracks.registry import TRACK_RUNNERS
from agi_talent_radar.core.models import TalentState


NODE_LABELS = {
    "normalizer": "脱敏与标准化",
    "academic_check": "论文外部核验",
    "evidence_extractor": "深度证据挖掘",
    "track_router": "多 Track 路由",
    "route_auditor": "Track 路由校验",
    "common_scorer": "通用潜力打分",
    "common_critic": "通用潜力校准",
    "base_track": "Base Track 专业评估",
    "agent_track": "Agent Track 专业评估",
    "safety_track": "Safety Track 专业评估",
    "multimodal_track": "Multimodal Track 专业评估",
    "systems_track": "Systems Track 专业评估",
    "ai4science_track": "AI4Science Track 专业评估",
    "portfolio_aggregator": "跨 Track 加权汇总",
    "global_critic": "全局一致性复核",
    "formatter": "结构化组装",
}


def build_graph():
    workflow = StateGraph(TalentState)
    workflow.add_node("normalizer", run_normalizer)
    workflow.add_node("academic_check", run_resume_academic_check)
    workflow.add_node("evidence_extractor", run_evidence_extractor)
    workflow.add_node("track_router", run_track_router)
    workflow.add_node("route_auditor", run_route_auditor)
    workflow.add_node("common_scorer", run_common_scorer)
    workflow.add_node("common_critic", run_common_critic)
    for track_key, runner in TRACK_RUNNERS.items():
        workflow.add_node(f"{track_key}_track", runner)
    workflow.add_node("portfolio_aggregator", run_portfolio_aggregator)
    workflow.add_node("global_critic", run_global_critic)
    workflow.add_node("formatter", run_formatter)

    workflow.set_entry_point("normalizer")
    workflow.add_edge("normalizer", "academic_check")
    workflow.add_edge("academic_check", "evidence_extractor")
    workflow.add_edge("evidence_extractor", "track_router")
    workflow.add_edge("track_router", "route_auditor")
    workflow.add_edge("route_auditor", "common_scorer")
    workflow.add_edge("common_scorer", "common_critic")
    track_nodes = []
    for track_key in TRACK_RUNNERS:
        node_key = f"{track_key}_track"
        workflow.add_edge("route_auditor", node_key)
        track_nodes.append(node_key)
    workflow.add_edge(["common_critic", *track_nodes], "portfolio_aggregator")
    workflow.add_edge("portfolio_aggregator", "global_critic")
    workflow.add_edge("global_critic", "formatter")
    workflow.add_edge("formatter", END)
    return workflow.compile()
