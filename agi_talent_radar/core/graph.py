from __future__ import annotations

from langgraph.graph import END, StateGraph

from agi_talent_radar.agents.job_fit.nodes import (
    run_candidate_preparer,
    run_decision_guard,
    run_jd_fit_assessor,
    run_job_fit_formatter,
)
from agi_talent_radar.core.models import TalentState


NODE_LABELS = {
    "candidate_preparer": "准备候选人与岗位",
    "jd_fit_assessor": "逐 JD 证据对照",
    "decision_guard": "面试准入门禁",
    "result_formatter": "准入结果组装",
}

NODE_DESCRIPTIONS = {
    "candidate_preparer": "校验一份结构化简历和当前激活的 JD，建立候选人 × JD 评估输入。",
    "jd_fit_assessor": "一次模型调用分别核对每个 JD 的硬门槛、固定维度和简历原文证据。",
    "decision_guard": "按确定性规则处理 unmet、unknown 和岗位匹配阈值，模型不能绕过硬门槛。",
    "result_formatter": "输出每个 JD 的独立准入结论，并推荐最匹配方向，不生成跨 JD 混合总分。",
}


def evaluation_graph_catalog() -> dict:
    def node(key: str, order: int) -> dict:
        return {
            "node": key,
            "label": NODE_LABELS[key],
            "description": NODE_DESCRIPTIONS[key],
            "order": order,
        }

    return {
        "workflow_version": "jd_fit_v2",
        "phases": [
            {
                "key": "preparation",
                "label": "准备",
                "description": "固定本次评估的简历和 JD 集合。",
                "groups": [
                    {"key": "input", "label": "评估输入", "nodes": [node("candidate_preparer", 0)]}
                ],
            },
            {
                "key": "assessment",
                "label": "岗位对照",
                "description": "每个 JD 独立评估，但合并为一次模型请求以降低限流风险。",
                "groups": [
                    {"key": "job_fit", "label": "逐 JD 评估", "nodes": [node("jd_fit_assessor", 1)]}
                ],
            },
            {
                "key": "decision",
                "label": "准入决策",
                "description": "硬门槛优先，随后判断是否值得投入面试资源。",
                "groups": [
                    {
                        "key": "guard_and_output",
                        "label": "门禁与输出",
                        "nodes": [node("decision_guard", 2), node("result_formatter", 3)],
                    }
                ],
            },
        ],
    }


def build_graph():
    workflow = StateGraph(TalentState)
    workflow.add_node("candidate_preparer", run_candidate_preparer)
    workflow.add_node("jd_fit_assessor", run_jd_fit_assessor)
    workflow.add_node("decision_guard", run_decision_guard)
    workflow.add_node("result_formatter", run_job_fit_formatter)

    workflow.set_entry_point("candidate_preparer")
    workflow.add_edge("candidate_preparer", "jd_fit_assessor")
    workflow.add_edge("jd_fit_assessor", "decision_guard")
    workflow.add_edge("decision_guard", "result_formatter")
    workflow.add_edge("result_formatter", END)
    return workflow.compile()
