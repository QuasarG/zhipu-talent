from __future__ import annotations

from typing import Any, Literal, TypedDict

from pydantic import BaseModel, Field


class ResumeProject(BaseModel):
    name: str = ""
    details: list[str] = Field(default_factory=list)


class CandidateResume(BaseModel):
    id: str
    name: str
    target_role: str = ""
    stage: str = ""
    education: list[str] = Field(default_factory=list)
    directions: list[str] = Field(default_factory=list)
    projects: list[ResumeProject] = Field(default_factory=list)
    publications: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    screening_tags: list[str] = Field(default_factory=list)


class NormalizedResume(BaseModel):
    id: str
    name: str
    target_role: str = ""
    stage: str = ""
    education_blind: list[str] = Field(default_factory=list)
    directions: list[str] = Field(default_factory=list)
    projects: list[ResumeProject] = Field(default_factory=list)
    publications: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    screening_tags: list[str] = Field(default_factory=list)
    raw_text: str = ""
    blind_note: str = "学校层级与排名仅用于风险提示，不直接进入潜力评分。"


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


class DimensionScore(BaseModel):
    key: str
    label: str
    score: float = Field(ge=1, le=5)
    weighted_score: float = 0
    rationale: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)


class CandidateEvaluation(BaseModel):
    id: str
    name: str
    target_role: str
    stage: str
    overall_score: int
    level: Literal["S", "A", "B", "C"]
    tier: Literal["强烈建议沟通", "建议沟通", "暂缓 / 需补充信息"]
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


class BatchResult(BaseModel):
    evaluations: list[CandidateEvaluation]
    tiers: dict[str, list[str]]
    dimension_labels: dict[str, str]
    rubric: list[RubricDimension]
    notes: list[str] = Field(default_factory=list)


class TalentState(TypedDict, total=False):
    resume: dict[str, Any]
    normalized: dict[str, Any]
    evidence: list[dict[str, Any]]
    scores: list[dict[str, Any]]
    critic_flags: list[str]
    critic_needs_rescore: bool
    loop_count: int
    final_output: dict[str, Any]
