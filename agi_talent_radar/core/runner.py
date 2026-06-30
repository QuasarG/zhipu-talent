from __future__ import annotations

from pathlib import Path
from typing import Iterable

from agi_talent_radar.agents.resume_parser import ensure_structured_resume
from agi_talent_radar.core.graph import build_graph
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
            "结果用于初筛辅助，不替代人工面谈和论文 / 项目真实性核验。",
        ],
    )


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
