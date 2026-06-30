from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Iterable

from agi_talent_radar.core.graph import build_graph
from agi_talent_radar.core.import_agent import run_import_agents
from agi_talent_radar.core.io import load_resumes, render_summary_markdown, save_json
from agi_talent_radar.core.models import BatchResult, CandidateEvaluation, CandidateResume, ImportClassification
from agi_talent_radar.core.rubric import DIMENSION_LABELS, RUBRIC


def run_candidate(resume: CandidateResume | dict) -> CandidateEvaluation:
    validated = resume if isinstance(resume, CandidateResume) else CandidateResume.model_validate(resume)
    graph = build_graph()
    state = graph.invoke({"resume": validated.model_dump(), "loop_count": 0})
    return CandidateEvaluation.model_validate(state["final_output"])


def run_batch(resumes: Iterable[CandidateResume | dict]) -> BatchResult:
    validated_resumes = [
        resume if isinstance(resume, CandidateResume) else CandidateResume.model_validate(resume)
        for resume in resumes
    ]
    import_classifications, import_trace = run_import_agents(validated_resumes)
    import_by_id = {item.id: item for item in import_classifications}
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [
            executor.submit(_evaluate_one, resume, import_by_id[resume.id])
            for resume in validated_resumes
        ]
        evaluations = [future.result() for future in futures]
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
        import_agent_trace=import_trace,
        notes=[
            "批量导入先经过初评分类 Agent 和回顾确认 Agent；分类只用于展示，不筛除候选人。",
            "逐人深评使用 DeepSeek/OpenAI-compatible JSON 模式；没有配置 DEEPSEEK_API_KEY 会直接失败。",
            "所有主观结论必须绑定 EvidenceItem；Critic 会检查证据和评分逻辑。",
            "结果用于初筛辅助，不替代人工面谈和论文 / 项目真实性核验。",
        ],
    )


def _evaluate_one(resume: CandidateResume, classification: ImportClassification) -> CandidateEvaluation:
    return _attach_import_classification(run_candidate(resume), classification)


def _attach_import_classification(
    evaluation: CandidateEvaluation,
    classification: ImportClassification,
) -> CandidateEvaluation:
    data = evaluation.model_dump()
    data["import_category"] = classification.final_category
    data["import_confidence"] = classification.confidence
    data["import_review_notes"] = classification.review_notes
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
