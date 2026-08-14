from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from agi_talent_radar.agents.common_potential.rubric import COMMON_DIMENSION_LABELS, COMMON_RUBRIC_MODELS
from agi_talent_radar.agents.resume_parser import ensure_structured_resume
from agi_talent_radar.core.graph import NODE_LABELS, build_graph
from agi_talent_radar.core.import_agent import run_import_agent
from agi_talent_radar.core.io import load_resumes, render_summary_markdown, save_json
from agi_talent_radar.core.models import BatchResult, CandidateEvaluation, CandidateResume, ImportClassification


def run_candidate(
    resume: CandidateResume | dict,
    academic_report: dict[str, Any] | None = None,
) -> CandidateEvaluation:
    validated = resume if isinstance(resume, CandidateResume) else CandidateResume.model_validate(resume)
    structured = ensure_structured_resume(validated)
    graph = build_graph()
    initial_state = {"resume": structured.model_dump(), "track_results": [], "loop_count": 0}
    if academic_report is not None:
        initial_state["academic_report"] = academic_report
    state = graph.invoke(initial_state)
    return CandidateEvaluation.model_validate(state["final_output"])


def run_candidate_stream(
    resume: CandidateResume | dict,
    academic_report: dict[str, Any] | None = None,
):
    """流式执行单候选人评估，边执行边 yield 节点事件和最终结果。"""
    validated = resume if isinstance(resume, CandidateResume) else CandidateResume.model_validate(resume)
    structured = ensure_structured_resume(validated)
    graph = build_graph()
    state: dict = {"resume": structured.model_dump(), "track_results": [], "loop_count": 0}
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
    if node_key == "normalizer":
        normalized = update.get("normalized", {})
        tiers = normalized.get("background_signal_tiers", {})
        school = _tier_text("school_tier", tiers.get("school_tier"))
        academic = _tier_text("academic_signal_tier", tiers.get("academic_signal_tier"))
        education = normalized.get("education_blind", [])
        return f"背景细节已折叠为低权重档位：学校={school}、学业={academic}，生成 {len(education)} 条分级教育信号。"
    if node_key == "evidence_extractor":
        evidence = update.get("evidence", [])
        dimensions = _top_counts([item.get("dimension", "") for item in evidence], limit=3)
        tools = _top_tools(evidence)
        suffix = f"，高频工具/信号：{'、'.join(tools)}" if tools else ""
        return f"提取 {len(evidence)} 条证据，覆盖 {dimensions or '待补证'} 等维度{suffix}。"
    if node_key == "track_router":
        assignments = update.get("track_assignments", [])
        text = "、".join(f"{item.get('track')} {float(item.get('weight', 0)):.0%}" for item in assignments)
        return f"分配至 {text or '待人工确认'}；路由置信度 {float(update.get('routing_confidence', 0)):.0%}。"
    if node_key == "route_auditor":
        flags = update.get("routing_flags", [])
        return f"路由校验发现 {len(flags)} 个待复核点。" if flags else "路由权重与证据覆盖校验通过。"
    if node_key == "common_scorer":
        return f"通用潜力初评分 {float(update.get('common_score', 0)):.1f} / 40。"
    if node_key == "common_critic":
        flags = update.get("common_critic_flags", [])
        return f"通用潜力校准为 {float(update.get('common_score', 0)):.1f} / 40，发现 {len(flags)} 个封顶项。"
    if node_key.endswith("_track"):
        results = update.get("track_results", [])
        if not results:
            return "该 Track 未被路由命中，跳过。"
        result = results[0]
        return f"{result.get('label')} 专业分 {float(result.get('calibrated_score', 0)):.1f} / 60。"
    if node_key == "portfolio_aggregator":
        assessment = update.get("portfolio_assessment", {})
        return (
            f"汇总 {assessment.get('overall_score', '—')} 分：通用 {assessment.get('common_score', 0)}、"
            f"Track {assessment.get('track_score', 0)}。"
        )
    if node_key == "global_critic":
        flags = update.get("global_critic_flags", [])
        if flags:
            return f"全局复核发现 {len(flags)} 个风险点：{_shorten(flags[0], 42)}"
        return "全局复核通过：路由、证据与评分未发现硬性冲突。"
    if node_key == "publication_scorer":
        score = float(update.get("publication_score", 0))
        details = update.get("publication_details", [])
        return f"论文质量加分 {score:.1f} 分（{len(details)} 篇可计分成果）。"
    if node_key == "safety_net":
        bonuses = update.get("safety_net_bonuses", [])
        score = float(update.get("safety_net_score", 0))
        if bonuses:
            return f"识别 {len(bonuses)} 项特殊优势，兜底加分 {score:.1f}。"
        return "未发现需要兜底加分的特殊优势。"
    if node_key == "formatter":
        final = update.get("final_output", {})
        strengths = final.get("core_strengths", [])
        questions = final.get("interview_questions", [])
        return f"组装完成：{_shorten(final.get('one_liner', '已生成画像'), 48)}；生成 {len(strengths)} 条优势和 {len(questions)} 个追问。"
    return "已完成"


def _node_event_status(node_key: str, update: dict) -> str:
    if node_key.endswith("_track") and not update.get("track_results"):
        return "skipped"
    return "done"


def _node_phase(node_key: str) -> str:
    if node_key in {"normalizer", "academic_check", "evidence_extractor"}:
        return "preparation"
    if node_key in {"track_router", "route_auditor"}:
        return "routing"
    if node_key in {"common_scorer", "common_critic"} or node_key.endswith("_track"):
        return "parallel"
    return "aggregation"


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
    evaluations.sort(key=lambda item: item.overall_score, reverse=True)
    tiers = {"能力评估": [item.id for item in evaluations]}
    _persist_evaluations(evaluations)
    return BatchResult(
        evaluations=evaluations,
        tiers=tiers,
        dimension_labels=COMMON_DIMENSION_LABELS,
        rubric=COMMON_RUBRIC_MODELS,
        import_classifications=import_classifications,
        notes=[
            "批量导入使用单一轻量 Agent，只提取基本信息和分类，不筛除候选人。",
            "逐人深评使用智谱 GLM（OpenAI 兼容）JSON 模式；没有配置 LLM_API_KEY 会直接失败。",
            "通用潜力占 40%，Track 专业能力占 60%。",
            "候选人可进入 1-3 个 Track，专业分按 Track 工作分布权重聚合。",
            "分数用于能力摘要与方向推荐，不用于自动筛选、录用或候选人分组。",
            "如果配置了 MySQL，结果会同时持久化到数据库；数据库失败不会中断评估流程。",
            "结果用于初筛辅助，不替代人工面谈和论文 / 项目真实性核验。",
        ],
    )


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
