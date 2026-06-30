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

            # 检测 critic 触发的回炉重打
            if state.get("critic_needs_rescore"):
                loop_count = int(state.get("loop_count", 0))
                yield {
                    "type": "rescore",
                    "loop_count": loop_count,
                    "message": f"逻辑判官发现评分问题，第 {loop_count + 1} 轮回炉重打…",
                }

    evaluation = CandidateEvaluation.model_validate(state["final_output"])
    yield {"type": "result", "result": evaluation.model_dump()}


def _node_summary(node_key: str, update: dict) -> str:
    if node_key == "normalizer":
        normalized = update.get("normalized", {})
        education = normalized.get("education_raw", [])
        return f"完成简历脱敏与标准化，保留 {len(education)} 条教育背景信号。"
    if node_key == "evidence_extractor":
        evidence = update.get("evidence", [])
        return f"从简历中挖掘出 {len(evidence)} 条可验证证据。"
    if node_key == "scorer":
        scores = update.get("scores", [])
        return f"完成 {len(scores)} 个维度的跨领域对齐打分。"
    if node_key == "critic":
        flags = update.get("critic_flags", [])
        return f"完成逻辑复核，发现 {len(flags)} 个需要关注的点。"
    if node_key == "formatter":
        return "结构化组装完成，生成最终评价与面谈追问。"
    return "已完成"


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
