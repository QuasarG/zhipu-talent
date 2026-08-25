from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


TaskImportance = Literal["primary", "major", "supporting"]
EvidenceType = Literal["direct", "transferable", "background"]
ConfidenceLevel = Literal["high", "medium", "low"]
AdmissionDecision = Literal["interview", "no_interview"]


IMPORTANCE_COEFFICIENTS: dict[TaskImportance, int] = {
    "primary": 3,
    "major": 2,
    "supporting": 1,
}


class TaskAnchors(BaseModel):
    level_2: str = Field(min_length=6)
    level_3: str = Field(min_length=6)
    level_4: str = Field(min_length=6)


class CoreTask(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9_]+$")
    title: str = Field(min_length=2, max_length=80)
    description: str = Field(min_length=10)
    importance: TaskImportance
    evaluation_focus: str = Field(min_length=10)
    anchors: TaskAnchors

    @property
    def coefficient(self) -> int:
        return IMPORTANCE_COEFFICIENTS[self.importance]


class AssessmentCard(BaseModel):
    role_summary: str = Field(min_length=10)
    core_tasks: list[CoreTask] = Field(min_length=3, max_length=6)
    background_evidence_guidance: str = Field(min_length=6)
    excluded_requirements: list[str] = Field(default_factory=list)

    @field_validator("core_tasks")
    @classmethod
    def validate_tasks(cls, tasks: list[CoreTask]) -> list[CoreTask]:
        ids = [task.id for task in tasks]
        if len(ids) != len(set(ids)):
            raise ValueError("核心任务 id 不能重复")
        if not any(task.importance == "primary" for task in tasks):
            raise ValueError("岗位卡至少需要一个首要任务")
        return tasks


class CardQualityReview(BaseModel):
    passed: bool
    issues: list[str] = Field(default_factory=list)
    revision_instructions: list[str] = Field(default_factory=list)


class EvidenceQuote(BaseModel):
    quote: str = Field(min_length=2)
    evidence_type: EvidenceType
    confidence: ConfidenceLevel
    relevance: str = Field(min_length=2)


class TaskAssessment(BaseModel):
    task_id: str
    level: int = Field(ge=0, le=4)
    confidence: ConfidenceLevel
    reasoning_summary: str = ""
    transfer_boundary: str = ""
    evidence: list[EvidenceQuote] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class ReviewCorrection(BaseModel):
    task_id: str
    original_level: int = Field(ge=0, le=4)
    revised_level: int = Field(ge=0, le=4)
    reason: str = Field(min_length=2)
    evidence: list[str] = Field(default_factory=list)


class OverallReview(BaseModel):
    corrections: list[ReviewCorrection] = Field(default_factory=list)
    interview_focus: list[dict[str, str]] = Field(default_factory=list)
    summary: str = ""


class PairAssessmentResult(BaseModel):
    candidate_id: str
    jd_id: str
    decision: AdmissionDecision
    decision_reason: str
    total_score: float = Field(ge=0, le=100)
    task_assessments: list[TaskAssessment]
    review_corrections: list[ReviewCorrection] = Field(default_factory=list)
    interview_focus: list[dict[str, str]] = Field(default_factory=list)
    summary: str = ""
    model_usage: list[dict[str, str]] = Field(default_factory=list)
    run_trace: list[dict[str, Any]] = Field(default_factory=list)
