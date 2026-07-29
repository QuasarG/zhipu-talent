from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, TypedDict

from pydantic import BaseModel, Field, field_validator, model_validator


TrackKey = Literal["base", "agent", "safety", "multimodal", "systems", "ai4science"]


class ResumeProject(BaseModel):
    name: str = ""
    details: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize_visual_project(cls, value: Any) -> Any:
        if isinstance(value, str):
            return {"name": value, "details": []}
        if not isinstance(value, dict):
            return value
        data = dict(value)
        name = data.get("name") or data.get("title") or data.get("project") or ""
        details = data.get("details")
        if details is None:
            details = [
                data.get(key)
                for key in (
                    "description",
                    "responsibility",
                    "role",
                    "method",
                    "methods",
                    "result",
                    "results",
                    "achievements",
                    "tech_stack",
                )
                if data.get(key) not in (None, "", [], {})
            ]
        return {"name": _structured_text(name), "details": _text_items(details)}

    @field_validator("details", mode="before")
    @classmethod
    def normalize_details(cls, value: Any) -> list[str]:
        return _text_items(value)


class ResumeExperience(BaseModel):
    organization: str = ""
    role: str = ""
    experience_type: str = ""
    start_date: str = ""
    end_date: str = ""
    period: str = ""
    details: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize_visual_experience(cls, value: Any) -> Any:
        if isinstance(value, str):
            return {"organization": value, "details": []}
        if not isinstance(value, dict):
            return value
        data = dict(value)
        details = data.get("details")
        if details is None:
            details = [
                data.get(key)
                for key in (
                    "description",
                    "responsibilities",
                    "responsibility",
                    "achievements",
                    "achievement",
                    "results",
                    "result",
                    "projects",
                    "tech_stack",
                )
                if data.get(key) not in (None, "", [], {})
            ]
        return {
            "organization": _structured_text(
                data.get("organization")
                or data.get("company")
                or data.get("employer")
                or data.get("institution")
                or data.get("lab")
                or ""
            ),
            "role": _structured_text(data.get("role") or data.get("position") or data.get("title") or ""),
            "experience_type": _structured_text(
                data.get("experience_type") or data.get("employment_type") or data.get("type") or ""
            ),
            "start_date": _structured_text(data.get("start_date") or data.get("start") or ""),
            "end_date": _structured_text(data.get("end_date") or data.get("end") or ""),
            "period": _structured_text(data.get("period") or data.get("duration") or ""),
            "details": _text_items(details),
        }

    @field_validator("details", mode="before")
    @classmethod
    def normalize_details(cls, value: Any) -> list[str]:
        return _text_items(value)


class CandidateResume(BaseModel):
    id: str
    name: str = ""
    target_role: str = ""
    stage: str = ""
    education: list[str] = Field(default_factory=list)
    directions: list[str] = Field(default_factory=list)
    experiences: list[ResumeExperience] = Field(default_factory=list)
    projects: list[ResumeProject] = Field(default_factory=list)
    publications: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    screening_tags: list[str] = Field(default_factory=list)
    raw_text: str = ""
    source_format: str = "text"
    document_analysis: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def normalize_experience_aliases(cls, value: Any) -> Any:
        if not isinstance(value, dict) or value.get("experiences") is not None:
            return value
        data = dict(value)
        aliases = ("work_experience", "work_experiences", "internships", "employment", "employment_history")
        combined: list[Any] = []
        for key in aliases:
            item = data.get(key)
            if isinstance(item, list):
                combined.extend(item)
            elif item not in (None, ""):
                combined.append(item)
        data["experiences"] = combined
        return data

    @field_validator(
        "education",
        "directions",
        "publications",
        "skills",
        "screening_tags",
        mode="before",
    )
    @classmethod
    def normalize_visual_text_lists(cls, value: Any) -> list[str]:
        return _text_items(value)


_FIELD_LABELS = {
    "school": "学校",
    "institution": "机构",
    "organization": "机构",
    "company": "公司",
    "employer": "单位",
    "degree": "学位",
    "major": "专业",
    "department": "院系",
    "start_date": "开始时间",
    "end_date": "结束时间",
    "period": "时间",
    "advisor": "导师",
    "title": "题目",
    "authors": "作者",
    "venue": "会议/期刊",
    "conference": "会议",
    "journal": "期刊",
    "year": "年份",
    "status": "状态",
    "description": "描述",
    "role": "角色",
    "position": "岗位",
    "experience_type": "经历类型",
    "employment_type": "用工类型",
    "result": "结果",
    "results": "结果",
    "tech_stack": "技术栈",
}


def _text_items(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    values = value if isinstance(value, (list, tuple, set)) else [value]
    normalized = [_structured_text(item) for item in values]
    return [item for item in normalized if item]


def _structured_text(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        parts = []
        for key, item in value.items():
            text = _structured_text(item)
            if not text:
                continue
            label = _FIELD_LABELS.get(str(key), str(key))
            parts.append(f"{label}: {text}")
        return "；".join(parts)
    if isinstance(value, (list, tuple, set)):
        return "、".join(item for item in (_structured_text(entry) for entry in value) if item)
    return str(value).strip()


class BackgroundSignalTiers(BaseModel):
    school_tier: str = "not_provided"
    gpa_tier: str = "not_provided"
    rank_tier: str = "not_provided"
    degree_tier: str = "mixed_or_unclear"
    academic_signal_tier: str = "weak_or_unknown"
    rationale: str = ""


class OrganizationSignalTier(BaseModel):
    index: int = Field(ge=0)
    organization_tier: str = "unknown"
    organization_type: str = "unknown"
    sector: str = "other_or_unknown"
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
    experiences_raw: list[ResumeExperience] = Field(default_factory=list)
    experiences_blind: list[ResumeExperience] = Field(default_factory=list)
    organization_signal_tiers: list[OrganizationSignalTier] = Field(default_factory=list)
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


class DirectionRecommendation(BaseModel):
    track: TrackKey
    label: str
    score: float = Field(ge=0, le=60)
    confidence: float = Field(ge=0, le=1)
    rationale: str = ""
    evidence_ids: list[str] = Field(default_factory=list)


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
    recommended_tracks: list[DirectionRecommendation] = Field(default_factory=list)
    stage_profile: str = ""
    routing_confidence: float = Field(default=0, ge=0, le=1)
    evaluation_mode: str = "multi_track_v1"


class ImportClassification(BaseModel):
    id: str
    name: str
    category: str
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
    academic_report: dict[str, Any]
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
