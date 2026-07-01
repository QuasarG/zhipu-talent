from __future__ import annotations

from pathlib import Path
from typing import Iterable

from agi_talent_radar.agents.resume_parser import ensure_structured_resume
from agi_talent_radar.core.graph import NODE_LABELS, build_graph
from agi_talent_radar.core.import_agent import run_import_agent
from agi_talent_radar.core.io import load_resumes, render_summary_markdown, save_json
from agi_talent_radar.core.models import BatchResult, CandidateEvaluation, CandidateResume, ImportClassification
from agi_talent_radar.core.rubric import DIMENSION_LABELS, RUBRIC


def run_candidate(resume: CandidateResume | dict) -> CandidateEvaluation:
    validated = resume if isinstance(resume, CandidateResume) else CandidateResume.model_validate(resume)
    structured = ensure_structured_resume(validated)
    graph = build_graph()
    state = graph.invoke({"resume": structured.model_dump(), "loop_count": 0})
    return CandidateEvaluation.model_validate(state["final_output"])


def run_candidate_stream(resume: CandidateResume | dict):
    """流式执行单候选人评估，边执行边 yield 节点事件和最终结果。"""
    validated = resume if isinstance(resume, CandidateResume) else CandidateResume.model_validate(resume)
    structured = ensure_structured_resume(validated)
    graph = build_graph()
    state: dict = {"resume": structured.model_dump(), "loop_count": 0}

    for event in graph.stream(state):
        for node_key, update in event.items():
            if node_key in NODE_LABELS:
                summary = _node_summary(node_key, update)
                yield {
                    "type": "node",
                    "node": node_key,
                    "label": NODE_LABELS[node_key],
                    "status": "done",
                    "message": summary,
                }
            state.update(update)

            # 检测 critic 触发的回炉重写/重打
            if state.get("critic_needs_evidence_rewrite"):
                loop_count = int(state.get("evidence_loop_count", 0))
                yield {
                    "type": "evidence_rewrite",
                    "loop_count": loop_count,
                    "message": f"逻辑判官发现证据可追溯性问题，第 {loop_count} 轮回炉重抽证据…",
                }
            if state.get("critic_needs_rescore"):
                loop_count = int(state.get("score_loop_count", state.get("loop_count", 0)))
                yield {
                    "type": "rescore",
                    "loop_count": loop_count,
                    "message": f"逻辑判官发现评分问题，第 {loop_count} 轮回炉重打…",
                }

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
    if node_key == "scorer":
        scores = update.get("scores", [])
        assessment = update.get("ai_assessment", {})
        top_scores = sorted(scores, key=lambda item: float(item.get("score", 0)), reverse=True)[:2]
        top_text = "、".join(f"{item.get('label', item.get('key', '维度'))}{float(item.get('score', 0)):.1f}" for item in top_scores)
        return f"完成 {len(scores)} 维打分，综合 {assessment.get('overall_score', '—')} / {assessment.get('level', '—')}，最高维度：{top_text or '暂无'}。"
    if node_key == "critic":
        flags = update.get("critic_flags", [])
        if flags:
            return f"逻辑复核发现 {len(flags)} 个风险点：{_shorten(flags[0], 42)}"
        return "逻辑复核通过：证据引用与评分分布未发现硬性冲突。"
    if node_key == "formatter":
        final = update.get("final_output", {})
        strengths = final.get("core_strengths", [])
        questions = final.get("interview_questions", [])
        return f"组装完成：{_shorten(final.get('one_liner', '已生成画像'), 48)}；生成 {len(strengths)} 条优势和 {len(questions)} 个追问。"
    return "已完成"


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
    tiers = {
        "强烈建议沟通": [item.id for item in evaluations if item.tier == "强烈建议沟通"],
        "建议沟通": [item.id for item in evaluations if item.tier == "建议沟通"],
        "暂缓 / 需补充信息": [item.id for item in evaluations if item.tier == "暂缓 / 需补充信息"],
    }
    _persist_evaluations(evaluations)
    return BatchResult(
        evaluations=evaluations,
        tiers=tiers,
        dimension_labels=DIMENSION_LABELS,
        rubric=RUBRIC,
        import_classifications=import_classifications,
        notes=[
            "批量导入使用单一轻量 Agent，只提取基本信息和分类，不筛除候选人。",
            "逐人深评使用 DeepSeek/OpenAI-compatible JSON 模式；没有配置 DEEPSEEK_API_KEY 会直接失败。",
            "潜力维度（70%）关注证据：技术栈、动作动词、量化结果、ownership、验证闭环。",
            "履历维度（30%）低权重参考：学校/GPA、论文、项目丰富度、影响力、方向匹配度。",
            "系统分流规则：80 分及以上进入优选库，60-79 分进入备选库，低于 60 分进入不建议后续沟通。",
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
