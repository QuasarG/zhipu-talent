from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, TypedDict

from pydantic import BaseModel, Field


TrackKey = Literal["base", "agent", "safety", "multimodal", "systems", "ai4science"]


class ResumeProject(BaseModel):
    name: str = ""
    details: list[str] = Field(default_factory=list)


class CandidateResume(BaseModel):
    id: str
    name: str = ""
    target_role: str = ""
    stage: str = ""
    education: list[str] = Field(default_factory=list)
    directions: list[str] = Field(default_factory=list)
    projects: list[ResumeProject] = Field(default_factory=list)
    publications: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    screening_tags: list[str] = Field(default_factory=list)
    raw_text: str = ""
    source_format: str = "text"
    document_analysis: dict[str, Any] = Field(default_factory=dict)


class BackgroundSignalTiers(BaseModel):
    school_tier: str = "not_provided"
    gpa_tier: str = "not_provided"
    rank_tier: str = "not_provided"
    degree_tier: str = "mixed_or_unclear"
    academic_signal_tier: str = "weak_or_unknown"
    rationale: str = ""


class NormalizedResume(BaseModel):
    id: str
    name: str
    target_role: str = ""
    stage: str = ""
    education_raw: list[str] = Field(default_factory=list)
    education_blind: list[str] = Field(default_factory=list)
    background_signal_tiers: BackgroundSignalTiers = Field(default_factory=BackgroundSignalTiers)
    directions: list[str] = Field(default_factory=list)
    projects: list[ResumeProject] = Field(default_factory=list)
    publications: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    screening_tags: list[str] = Field(default_factory=list)
    raw_text: str = ""
    blind_note: str = "学校/GPA/排名等具体细节已折叠为分级信号，仅以低权重进入履历维度评分。"


class RubricDimension(BaseModel):
    key: str
    label: str
    weight: float
    why_it_matters: str
    evidence_rule: str


class EvidenceItem(BaseModel):
    id: str
    dimension: str
    source: str
    quote: str
    signals: list[str] = Field(default_factory=list)
    strength: int = Field(ge=1, le=5)
    has_metric: bool = False
    has_specific_tool: bool = False
    has_ownership: bool = False
    track_hints: list[TrackKey] = Field(default_factory=list)
    page: int | None = None
    bbox: list[float] = Field(default_factory=list)
    extraction_confidence: float = Field(default=1.0, ge=0, le=1)


class DimensionScore(BaseModel):
    key: str
    label: str
    score: float = Field(ge=0, le=5)
    weighted_score: float = 0
    max_points: float = 0
    rationale: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)


class TrackAssignment(BaseModel):
    track: TrackKey
    weight: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    rationale: str = ""
    evidence_ids: list[str] = Field(default_factory=list)


class TrackEvaluation(BaseModel):
    track: TrackKey
    label: str
    weight: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    raw_score: float = Field(ge=0, le=60)
    calibrated_score: float = Field(ge=0, le=60)
    dimension_scores: list[DimensionScore] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)
    critic_flags: list[str] = Field(default_factory=list)


class DocumentQualityAssessment(BaseModel):
    score: float = Field(default=0, ge=0, le=3)
    available: bool = False
    rationale: str = ""
    dimension_scores: list[DimensionScore] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class CandidateEvaluation(BaseModel):
    id: str
    name: str
    target_role: str
    stage: str
    overall_score: int
    level: Literal["S", "A", "B", "C"]
    tier: Literal["强烈建议沟通", "建议沟通", "暂缓 / 需补充信息"]
    decision_method: str = ""
    one_liner: str
    core_strengths: list[str]
    potential_risks: list[str]
    interview_questions: list[str]
    cultivation_direction: list[str]
    dimension_scores: list[DimensionScore]
    evidence: list[EvidenceItem]
    critic_flags: list[str] = Field(default_factory=list)
    normalized_education: list[str] = Field(default_factory=list)
    screening_tags: list[str] = Field(default_factory=list)
    import_category: str = ""
    import_confidence: float = 0
    common_score: float = Field(default=0, ge=0, le=37)
    document_score: float = Field(default=0, ge=0, le=3)
    track_assignments: list[TrackAssignment] = Field(default_factory=list)
    track_evaluations: list[TrackEvaluation] = Field(default_factory=list)
    routing_confidence: float = Field(default=0, ge=0, le=1)
    evaluation_mode: str = "multi_track_v1"


class ImportClassification(BaseModel):
    id: str
    name: str
    category: str
    level: str = ""
    confidence: float = Field(ge=0, le=1)
    reason: str


class BatchResult(BaseModel):
    evaluations: list[CandidateEvaluation]
    tiers: dict[str, list[str]]
    dimension_labels: dict[str, str]
    rubric: list[RubricDimension]
    import_classifications: list[ImportClassification] = Field(default_factory=list)
    import_agent_trace: list[str] = Field(default_factory=list)
    evaluation_mode: str = "deepseek_ai_only"
    notes: list[str] = Field(default_factory=list)


class TalentState(TypedDict, total=False):
    resume: dict[str, Any]
    normalized: dict[str, Any]
    evidence: list[dict[str, Any]]
    evidence_integrity_flags: list[str]
    evidence_repair_feedback: list[str]
    scores: list[dict[str, Any]]
    critic_flags: list[str]
    critic_needs_rescore: bool
    critic_needs_evidence_rewrite: bool
    ai_assessment: dict[str, Any]
    loop_count: int
    score_loop_count: int
    evidence_loop_count: int
    document_quality: dict[str, Any]
    track_assignments: list[dict[str, Any]]
    routing_confidence: float
    routing_flags: list[str]
    common_scores: list[dict[str, Any]]
    common_score: float
    common_critic_flags: list[str]
    track_results: Annotated[list[dict[str, Any]], operator.add]
    portfolio_assessment: dict[str, Any]
    global_critic_flags: list[str]
    final_output: dict[str, Any]
