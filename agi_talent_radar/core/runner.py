from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable
import json

from agi_talent_radar.agents.common_potential.rubric import COMMON_DIMENSION_LABELS, COMMON_RUBRIC_MODELS
from agi_talent_radar.agents.resume_parser import ensure_structured_resume
from agi_talent_radar.core.import_agent import run_import_agent
from agi_talent_radar.core.io import load_resumes, render_summary_markdown, save_json
from agi_talent_radar.core.models import (
    BatchResult,
    CandidateEvaluation,
    CandidateResume,
    ImportClassification,
    JobDefinition,
)


NODE_LABELS = {
    "material_desk": "材料整备",
    "panel_lead": "评审团",
    "decision_guard": "面试准入门禁",
    "result_formatter": "准入结果组装",
}

NODE_DESCRIPTIONS = {
    "material_desk": "盘点候选人材料并预热文本层，形成主席的全局案卷目录。",
    "panel_lead": "主席动态派出类型化评审任务（查证/深读/岗位对照/仲裁），核收结论后写综合意见。",
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
        "workflow_version": "jd_fit_panel",
        "phases": [
            {
                "key": "preparation",
                "label": "准备",
                "description": "固定本次评估的简历和 JD 集合，整备材料案卷。",
                "groups": [
                    {"key": "input", "label": "评估输入", "nodes": [node("material_desk", 0)]}
                ],
            },
            {
                "key": "assessment",
                "label": "评审",
                "description": "主席派发类型化 mission，评审员读真实材料并回传 findings。",
                "groups": [
                    {"key": "panel", "label": "评审团循环", "nodes": [node("panel_lead", 1)]}
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


def run_candidate(
    resume: CandidateResume | dict,
    academic_report: dict[str, Any] | None = None,
    jobs: Iterable[JobDefinition | dict[str, Any]] | None = None,
) -> CandidateEvaluation:
    """同步执行评审团评估（panel 是唯一评估引擎），返回最终结果。"""
    evaluation: CandidateEvaluation | None = None
    for event in run_candidate_panel_stream(resume, academic_report=academic_report, jobs=jobs):
        if event["type"] == "result":
            evaluation = CandidateEvaluation.model_validate(event["result"])
    if evaluation is None:
        raise RuntimeError("评估流程未返回结果。")
    return evaluation


def _validated_jobs(
    jobs: Iterable[JobDefinition | dict[str, Any]] | None,
) -> list[JobDefinition]:
    if jobs is None:
        return load_active_job_definitions()
    return [job if isinstance(job, JobDefinition) else JobDefinition.model_validate(job) for job in jobs]


def load_active_job_definitions() -> list[JobDefinition]:
    from agi_talent_radar.core.db.repository import list_active_jds
    from agi_talent_radar.core.db.runtime import get_session

    with get_session() as session:
        rows = list_active_jds(session)
        return [
            JobDefinition(
                id=row.id,
                title=row.title,
                team=row.team or "",
                raw_text=row.raw_text or "",
                spec=_load_spec(row.spec),
            )
            for row in rows
        ]


def _load_spec(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def run_batch(resumes: Iterable[CandidateResume | dict]) -> BatchResult:
    validated_resumes = [
        resume if isinstance(resume, CandidateResume) else CandidateResume.model_validate(resume)
        for resume in resumes
    ]
    import_classifications = run_import_agent(validated_resumes)
    import_by_id = {item.id: item for item in import_classifications}
    evaluations = [
        _attach_import_classification(run_candidate(resume), import_by_id[resume.id])
        for resume in validated_resumes
    ]
    evaluations.sort(key=_candidate_decision_rank, reverse=True)
    tiers = {
        "进入面试": [item.id for item in evaluations if item.interview_decision == "interview"],
        "待补信息": [item.id for item in evaluations if item.interview_decision == "hold"],
        "不进入面试": [item.id for item in evaluations if item.interview_decision == "reject"],
    }
    _persist_evaluations(evaluations)
    return BatchResult(
        evaluations=evaluations,
        tiers=tiers,
        dimension_labels=COMMON_DIMENSION_LABELS,
        rubric=COMMON_RUBRIC_MODELS,
        import_classifications=import_classifications,
        notes=[
            "批量导入使用单一轻量 Agent，只提取基本信息和分类，不筛除候选人。",
            "逐人深评使用评审团（panel）链路：主席派类型化评审员读真实材料并对照激活 JD。",
            "硬门槛优先判定；unmet 直接拒绝，unknown 进入待补信息。",
            "多 JD 不做加权平均，每个 JD 独立输出进入面试、待补信息或不进入面试。",
            "进入面试表示值得投入面试资源验证，不表示最终录用。",
            "如果配置了 MySQL，结果会同时持久化到数据库；数据库失败不会中断评估流程。",
            "结果用于初筛辅助，不替代人工面谈和论文 / 项目真实性核验。",
        ],
    )


def _candidate_decision_rank(item: CandidateEvaluation) -> tuple[int, int]:
    decision_rank = {"": -1, "reject": 0, "hold": 1, "interview": 2}
    return decision_rank[item.interview_decision], item.overall_score


def _persist_evaluations(evaluations: list[CandidateEvaluation]) -> None:
    try:
        from agi_talent_radar.core.database import get_session, save_evaluation

        with get_session() as session:
            for evaluation in evaluations:
                save_evaluation(session, evaluation)
    except Exception as exc:
        import warnings

        warnings.warn(f"保存评估结果到数据库失败: {exc}", stacklevel=2)


def _attach_import_classification(
    evaluation: CandidateEvaluation,
    classification: ImportClassification,
) -> CandidateEvaluation:
    data = evaluation.model_dump()
    data["import_category"] = classification.category
    data["import_confidence"] = classification.confidence
    return CandidateEvaluation.model_validate(data)


def run_batch_from_file(input_path: str | Path, output_dir: str | Path = "outputs") -> BatchResult:
    result = run_batch(load_resumes(input_path))
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    save_json(target_dir / "talent_evaluations.json", result.model_dump())
    (target_dir / "talent_evaluations.md").write_text(
        render_summary_markdown(result.evaluations),
        encoding="utf-8",
    )
    return result


def run_candidate_panel_stream(
    resume: CandidateResume | dict,
    academic_report: dict[str, Any] | None = None,
    jobs: Iterable[JobDefinition | dict[str, Any]] | None = None,
    materials: dict[str, Any] | None = None,
):
    """评审团（panel）评估：主席是带工具的主 agent（spawn_agent 派子评审 agent，
    子 agent 由 spawn prompt 全权约束、不能嵌套），调查充分后输出评分合同，
    经确定性装配成 job_fit_raw；decision_guard / 结果组装复用原节点——评分合同
    不变。见 docs/design/panel-evaluation.md。"""
    from agi_talent_radar.agents.job_fit.nodes import run_decision_guard, run_job_fit_formatter
    from agi_talent_radar.agents.job_fit.panel import run_panel_stream

    validated = resume if isinstance(resume, CandidateResume) else CandidateResume.model_validate(resume)
    structured = ensure_structured_resume(validated)
    job_list = _validated_jobs(jobs)

    state: dict[str, Any] = {
        "prepared_resume": structured.model_dump(),
        "prepared_jobs": [job.model_dump() for job in job_list],
    }
    if academic_report is not None:
        state["academic_report"] = academic_report

    ctx = None
    if materials and materials.get("root"):
        from agi_talent_radar.agents.job_fit.materials import MaterialsContext

        ctx = MaterialsContext(str(materials["root"]), materials.get("allowed"))

    stream_result = yield from run_panel_stream(
        structured.model_dump(), job_list, academic_report, ctx,
    )
    state["job_fit_raw"] = stream_result["job_fit_raw"]
    panel_trace = stream_result["trace"]

    state.update(run_decision_guard(state))
    yield {
        "type": "node", "node": "decision_guard",
        "label": NODE_LABELS["decision_guard"], "status": "done",
        "phase": "decision", "message": "硬门槛与决策阈值裁决完成（确定性规则，评审团不可绕过）。",
    }
    state.update(run_job_fit_formatter(state))
    yield {
        "type": "node", "node": "result_formatter",
        "label": NODE_LABELS["result_formatter"], "status": "done",
        "phase": "decision", "message": "评估结果组装完成。",
    }
    evaluation = CandidateEvaluation.model_validate(state["final_output"])
    yield {"type": "result", "result": evaluation.model_dump(), "trace": panel_trace}
