from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable
import json

from agi_talent_radar.agents.common_potential.rubric import COMMON_DIMENSION_LABELS, COMMON_RUBRIC_MODELS
from agi_talent_radar.agents.resume_parser import ensure_structured_resume
from agi_talent_radar.core.graph import NODE_LABELS, build_graph
from agi_talent_radar.core.import_agent import run_import_agent
from agi_talent_radar.core.io import load_resumes, render_summary_markdown, save_json
from agi_talent_radar.core.models import (
    BatchResult,
    CandidateEvaluation,
    CandidateResume,
    ImportClassification,
    JobDefinition,
)


def run_candidate(
    resume: CandidateResume | dict,
    academic_report: dict[str, Any] | None = None,
    jobs: Iterable[JobDefinition | dict[str, Any]] | None = None,
) -> CandidateEvaluation:
    validated = resume if isinstance(resume, CandidateResume) else CandidateResume.model_validate(resume)
    structured = ensure_structured_resume(validated)
    graph = build_graph()
    job_list = _validated_jobs(jobs)
    initial_state = {
        "resume": structured.model_dump(),
        "jobs": [job.model_dump() for job in job_list],
    }
    if academic_report is not None:
        initial_state["academic_report"] = academic_report
    state = graph.invoke(initial_state)
    return CandidateEvaluation.model_validate(state["final_output"])


def run_candidate_stream(
    resume: CandidateResume | dict,
    academic_report: dict[str, Any] | None = None,
    jobs: Iterable[JobDefinition | dict[str, Any]] | None = None,
):
    """流式执行单候选人评估，边执行边 yield 节点事件和最终结果。"""
    validated = resume if isinstance(resume, CandidateResume) else CandidateResume.model_validate(resume)
    structured = ensure_structured_resume(validated)
    graph = build_graph()
    job_list = _validated_jobs(jobs)
    state: dict = {
        "resume": structured.model_dump(),
        "jobs": [job.model_dump() for job in job_list],
    }
    if academic_report is not None:
        state["academic_report"] = academic_report

    for event in graph.stream(state):
        for node_key, update in event.items():
            if node_key in NODE_LABELS:
                summary = _node_summary(node_key, update)
                yield {
                    "type": "node",
                    "node": node_key,
                    "label": NODE_LABELS[node_key],
                    "status": _node_event_status(node_key, update),
                    "phase": _node_phase(node_key),
                    "message": summary,
                }
            state.update(update)

    evaluation = CandidateEvaluation.model_validate(state["final_output"])
    yield {"type": "result", "result": evaluation.model_dump()}


def _node_summary(node_key: str, update: dict) -> str:
    if node_key == "candidate_preparer":
        return f"已固定 1 份简历和 {len(update.get('prepared_jobs', []))} 个 JD。"
    if node_key == "jd_fit_assessor":
        count = len(update.get("job_fit_raw", {}).get("assessments", []))
        return f"一次请求完成 {count} 个 JD 的独立证据对照。"
    if node_key == "decision_guard":
        assessments = update.get("job_fit_result", {}).get("assessments", [])
        decisions = _top_counts([item.get("decision", "") for item in assessments], limit=3)
        return f"硬门槛和阈值校正完成：{decisions or '无有效结论'}。"
    if node_key == "result_formatter":
        final = update.get("final_output", {})
        return (
            f"组装完成：最匹配 {final.get('best_fit_jd_title', '—')}，"
            f"结论 {final.get('interview_decision', '—')}。"
        )
    return "已完成"


def _node_event_status(node_key: str, update: dict) -> str:
    return "done"


def _node_phase(node_key: str) -> str:
    if node_key == "candidate_preparer":
        return "preparation"
    if node_key == "jd_fit_assessor":
        return "assessment"
    return "decision"


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


def _tier_text(key: str, value: str | None) -> str:
    labels = {
        "school_tier": {
            "elite_research": "顶尖研究型",
            "strong_research": "强研究型",
            "specialized_stem": "特色/STEM强相关",
            "general_university": "普通综合类",
            "emerging_or_unknown": "新型或未知",
            "not_provided": "未提供",
        },
        "academic_signal_tier": {
            "very_strong": "很强",
            "strong": "较强",
            "moderate": "中等",
            "weak_or_unknown": "弱或未知",
        },
    }
    return labels.get(key, {}).get(str(value), str(value or "未知"))


def _top_counts(values: list[str], limit: int = 3) -> str:
    counts: dict[str, int] = {}
    for value in values:
        if value:
            counts[value] = counts.get(value, 0) + 1
    return "、".join(key for key, _ in sorted(counts.items(), key=lambda item: item[1], reverse=True)[:limit])


def _top_tools(evidence: list[dict], limit: int = 3) -> list[str]:
    tools: dict[str, int] = {}
    for item in evidence:
        for signal in item.get("signals", []):
            if isinstance(signal, str) and signal.startswith("技术栈:"):
                tool = signal.split(":", 1)[1].strip()
                tools[tool] = tools.get(tool, 0) + 1
    return [tool for tool, _ in sorted(tools.items(), key=lambda item: item[1], reverse=True)[:limit]]


def _shorten(text: str, limit: int) -> str:
    text = str(text).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


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
            "逐人深评使用一次智谱 GLM 请求，对当前激活的全部 JD 分别给出证据对照。",
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
