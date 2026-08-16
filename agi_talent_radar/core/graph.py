from __future__ import annotations

from langgraph.graph import END, StateGraph

from agi_talent_radar.agents.aggregation import run_global_critic, run_portfolio_aggregator
from agi_talent_radar.agents.academic.nodes import run_resume_academic_check
from agi_talent_radar.agents.common_potential import run_common_critic, run_common_scorer
from agi_talent_radar.agents.evidence_extractor import run_evidence_extractor
from agi_talent_radar.agents.formatter import run_formatter
from agi_talent_radar.agents.normalizer import run_normalizer
from agi_talent_radar.agents.publication_scorer import run_publication_scorer
from agi_talent_radar.agents.routing import run_route_auditor, run_track_router
from agi_talent_radar.agents.safety_net import run_safety_net
from agi_talent_radar.agents.tracks.shared.engine import run_dynamic_tracks
from agi_talent_radar.core.models import TalentState


NODE_LABELS = {
    "normalizer": "脱敏与标准化",
    "academic_check": "论文外部核验",
    "evidence_extractor": "深度证据挖掘",
    "track_router": "多 Track 路由",
    "route_auditor": "Track 路由校验",
    "common_scorer": "通用潜力打分",
    "common_critic": "通用潜力校准",
    "dynamic_tracks": "岗位 Track 评估",
    "portfolio_aggregator": "跨 Track 加权汇总",
    "global_critic": "全局一致性复核",
    "publication_scorer": "论文质量加分",
    "safety_net": "特殊优势兜底",
    "formatter": "结构化组装",
}

NODE_DESCRIPTIONS = {
    "normalizer": "统一简历字段、时间与文本格式，生成稳定的评估输入。",
    "academic_check": "核对论文声明与外部学术数据，输出逐篇核验结论。",
    "evidence_extractor": "从教育、项目、经历和成果中提取可引用证据。",
    "track_router": "依据证据选择适合的岗位 Track（来自 JD 池），并分配权重。",
    "route_auditor": "复核 Track 路由是否完整、一致且有证据支撑。",
    "common_scorer": "计算所有候选人共享的通用潜力维度。",
    "common_critic": "校准通用潜力评分并标记证据不足或过度推断。",
    "dynamic_tracks": "按 JD 池中激活的岗位 Track 逐一评估专业能力。",
    "portfolio_aggregator": "合并通用评分与各 Track 结果，计算组合评分。",
    "global_critic": "执行最终一致性复核，检查结论、风险和证据链。",
    "publication_scorer": "按 CCF 分级与核验状态，为已发表成果额外加分。",
    "safety_net": "识别分项评分未覆盖的稀缺外部成就（状元/竞赛最高奖等），少量加分。",
    "formatter": "组装结构化结果、面试问题与培养建议。",
}


def evaluation_graph_catalog() -> dict:
    """返回供前端稳定渲染的完整评估图谱。"""

    def nodes(*keys: str) -> list[dict]:
        return [
            {
                "node": key,
                "label": NODE_LABELS[key],
                "description": NODE_DESCRIPTIONS[key],
                "order": list(NODE_LABELS).index(key),
            }
            for key in keys
        ]

    return {
        "phases": [
            {
                "key": "preparation",
                "label": "准备与证据",
                "description": "整理输入并建立可追溯的证据基础。",
                "groups": [
                    {
                        "key": "preparation_chain",
                        "label": "准备链",
                        # 论文核验已前移到导入阶段异步完成，评估内不再展示该节点
                        "nodes": nodes("normalizer", "evidence_extractor"),
                    }
                ],
            },
            {
                "key": "routing",
                "label": "路由决策",
                "description": "选择专业评估方向并复核分配。",
                "groups": [
                    {
                        "key": "routing_chain",
                        "label": "路由链",
                        "nodes": nodes("track_router", "route_auditor"),
                    }
                ],
            },
            {
                "key": "parallel",
                "label": "并行评估",
                "description": "通用评分与各专业 Track 并行运行。",
                "groups": [
                    {
                        "key": "common_track",
                        "label": "通用评分链",
                        "nodes": nodes("common_scorer", "common_critic"),
                    },
                    {
                        "key": "specialized_tracks",
                        "label": "岗位 Track（JD 池驱动）",
                        "description": "仅路由命中的岗位 Track 参与计算，未命中不评分。",
                        "collapsible": True,
                        "nodes": nodes("dynamic_tracks"),
                    },
                ],
            },
            {
                "key": "aggregation",
                "label": "汇总与输出",
                "description": "聚合多 Track 结果并生成最终评估。",
                "groups": [
                    {
                        "key": "aggregation_chain",
                        "label": "汇总链",
                        "nodes": nodes("portfolio_aggregator", "global_critic", "publication_scorer", "safety_net", "formatter"),
                    }
                ],
            },
        ]
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
    workflow.add_node("dynamic_tracks", run_dynamic_tracks)
    workflow.add_node("portfolio_aggregator", run_portfolio_aggregator)
    workflow.add_node("global_critic", run_global_critic)
    workflow.add_node("publication_scorer", run_publication_scorer)
    workflow.add_node("safety_net", run_safety_net)
    workflow.add_node("formatter", run_formatter)

    workflow.set_entry_point("normalizer")
    workflow.add_edge("normalizer", "academic_check")
    workflow.add_edge("academic_check", "evidence_extractor")
    workflow.add_edge("evidence_extractor", "track_router")
    workflow.add_edge("track_router", "route_auditor")
    workflow.add_edge("route_auditor", "common_scorer")
    workflow.add_edge("common_scorer", "common_critic")
    workflow.add_edge("route_auditor", "dynamic_tracks")
    workflow.add_edge(["common_critic", "dynamic_tracks"], "portfolio_aggregator")
    workflow.add_edge("portfolio_aggregator", "global_critic")
    workflow.add_edge("global_critic", "publication_scorer")
    workflow.add_edge("publication_scorer", "safety_net")
    workflow.add_edge("safety_net", "formatter")
    workflow.add_edge("formatter", END)
    return workflow.compile()
