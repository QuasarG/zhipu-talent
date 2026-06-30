from __future__ import annotations

from pathlib import Path
from typing import Iterable

from agi_talent_radar.core.graph import build_graph
from agi_talent_radar.core.io import load_resumes, render_summary_markdown, save_json
from agi_talent_radar.core.models import BatchResult, CandidateEvaluation, CandidateResume
from agi_talent_radar.core.rubric import DIMENSION_LABELS, RUBRIC


def run_candidate(resume: CandidateResume | dict) -> CandidateEvaluation:
    validated = resume if isinstance(resume, CandidateResume) else CandidateResume.model_validate(resume)
    graph = build_graph()
    state = graph.invoke({"resume": validated.model_dump(), "loop_count": 0})
    return CandidateEvaluation.model_validate(state["final_output"])


def run_batch(resumes: Iterable[CandidateResume | dict]) -> BatchResult:
    evaluations = [run_candidate(resume) for resume in resumes]
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
        notes=[
            "评分使用脱敏后的简历内容，学校层级和 GPA 不直接进入综合分。",
            "所有主观结论必须绑定 EvidenceItem；Critic 会检查引文是否来自原简历。",
            "结果用于初筛辅助，不替代人工面谈和论文 / 项目真实性核验。",
        ],
    )


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
