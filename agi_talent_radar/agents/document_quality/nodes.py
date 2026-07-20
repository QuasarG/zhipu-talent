from __future__ import annotations

from agi_talent_radar.core.models import CandidateResume, DimensionScore, DocumentQualityAssessment


DOCUMENT_DIMENSIONS = (
    ("information_architecture", "信息架构与可读性", 0.8),
    ("evidence_expression", "证据表达质量", 1.1),
    ("content_consistency", "内容一致性与专业度", 0.7),
    ("targeting", "目标导向与信息取舍", 0.4),
)


def run_document_quality(state: dict) -> dict:
    resume = CandidateResume.model_validate(state["resume"])
    analysis = resume.document_analysis
    quality = analysis.get("quality_dimensions") if isinstance(analysis, dict) else None
    if not isinstance(quality, dict):
        assessment = DocumentQualityAssessment(
            score=0,
            available=False,
            rationale="非视觉简历或多模态模型未返回版面质量结果，不计分也不扣分。",
            warnings=["简历表达质量不可用。"] if resume.source_format == "pdf" else [],
        )
        return {"document_quality": assessment.model_dump()}

    scores: list[DimensionScore] = []
    for key, label, max_points in DOCUMENT_DIMENSIONS:
        raw = quality.get(key, {})
        if not isinstance(raw, dict):
            raw = {"score": raw}
        score = max(0.0, min(5.0, round(float(raw.get("score", 0)), 1)))
        scores.append(
            DimensionScore(
                key=key,
                label=label,
                score=score,
                max_points=max_points,
                weighted_score=round(score / 5 * max_points, 2),
                rationale=str(raw.get("rationale", "多模态模型未提供说明。")),
                evidence_ids=[],
                risk_notes=[],
            )
        )
    total = round(sum(item.weighted_score for item in scores), 2)
    assessment = DocumentQualityAssessment(
        score=total,
        available=True,
        rationale="简历表达质量仅作低权重辅助信号，不评价模板、照片或视觉风格。",
        dimension_scores=scores,
        evidence_refs=[str(item) for item in analysis.get("evidence_refs", [])],
        warnings=[str(item) for item in analysis.get("warnings", [])],
    )
    return {"document_quality": assessment.model_dump()}
