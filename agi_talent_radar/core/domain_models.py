"""人才研究平台新领域 Pydantic 模型。

按 ``CONTEXT.md`` 和 ``docs/backend_use_case_decisions.md`` 收敛的语义形状。
本模块不挂 SQLAlchemy ORM，仅作为真值形状契约，
后续阶段（1/2/4/5/6/7）会据此迁移数据库表和 API schema。

注意：
- 所有枚举都暴露 ``__all__`` 列表，方便契约测试检查成员稳定。
- ``EngagementStatusChange`` 与 ``CandidateSource`` 等只读字段为可选，
  不强制旧数据立即拥有这些列；迁移期允许 NULL。
- 本文件不可 import 任何 ORM 或连接器，避免被旧代码反向耦合。
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# 简历提交 / 版本
# ---------------------------------------------------------------------------


class ResumeSubmission(BaseModel):
    """一次简历导入动作。评估完成前不是人才，只是待评估材料。"""

    model_config = ConfigDict(frozen=False, extra="forbid")

    id: str
    person_id: str | None = None
    source_format: Literal["pdf", "jsonl", "md", "txt"]
    raw_text: str
    parse_status: Literal["pending", "parsed", "failed"] = "pending"
    created_at: datetime


class ResumeVersion(BaseModel):
    """同一份简历在不同评估轮次的版本。原文永不被新版本覆盖。"""

    model_config = ConfigDict(extra="forbid")

    submission_id: str
    version: int
    raw_text: str
    structured: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# 人才来源 / 人才档案
# ---------------------------------------------------------------------------


class CandidateSourceKind(str, Enum):
    """人才来源类型：与 ``CandidateSource.source_kind`` 对应。"""

    RESUME_EVALUATION = "resume_evaluation"
    PERSON_INVESTIGATION = "person_investigation"

    @classmethod
    def all(cls) -> tuple[str, ...]:
        return tuple(member.value for member in cls)


class CandidateSource(BaseModel):
    """人才档案可以同时拥有多个来源。"""

    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    source_kind: CandidateSourceKind
    source_record_id: str
    created_at: datetime
    note: str = ""


class Candidate(BaseModel):
    """已入人才库的人才档案。与 Person 一一关联。"""

    model_config = ConfigDict(extra="forbid")

    id: str
    person_id: str
    sources: list[CandidateSourceKind] = Field(default_factory=list)
    current_resume_version_id: str | None = None
    engagement_status: str = "newly_admitted"
    admitted_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# HR 跟进状态
# ---------------------------------------------------------------------------


class EngagementStatus(str, Enum):
    """HR 人工跟进状态枚举，与 ``Candidate.engagement_status`` 对应。

    跟进状态与能力评分、推荐 Track、论文核验完全独立。
    系统不得基于分数或舆情切换状态。
    """

    APPLIED = "newly_admitted"
    NEWLY_ADMITTED = "newly_admitted"
    SCREENING = "screening"
    INTERVIEWING = "interviewing"
    OFFER_PENDING = "offer_pending"
    OFFERED = "offered"
    HIRED = "hired"
    DEPARTED = "departed"
    REJECTED = "rejected"
    TO_CONTACT = "to_contact"
    CONTACTED = "contacted"
    ONGOING_FOLLOW = "ongoing_follow"
    CLOSED = "closed"

    @classmethod
    def all(cls) -> tuple[str, ...]:
        return (
            cls.APPLIED.value,
            cls.SCREENING.value,
            cls.INTERVIEWING.value,
            cls.OFFER_PENDING.value,
            cls.OFFERED.value,
            cls.HIRED.value,
            cls.DEPARTED.value,
            cls.REJECTED.value,
        )

    @classmethod
    def accepted(cls) -> tuple[str, ...]:
        return tuple(member.value for member in cls)


class EngagementStatusChange(BaseModel):
    """人工修改跟进状态的不可变审计记录。"""

    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    previous: EngagementStatus | None = None
    current: EngagementStatus
    changed_by: str
    changed_at: datetime
    note: str = ""


# ---------------------------------------------------------------------------
# 论文自述 / 外部核验
# ---------------------------------------------------------------------------


class ClaimedPublicationStatus(str, Enum):
    """简历中的论文自述状态。属于候选人陈述，不等于外部核验事实。"""

    DRAFT = "draft"
    SUBMITTED = "submitted"
    IN_REVIEW = "in_review"
    ACCEPTED = "accepted"
    PUBLISHED = "published"
    UNKNOWN = "unknown"

    @classmethod
    def all(cls) -> tuple[str, ...]:
        return tuple(member.value for member in cls)


class PublicationClaim(BaseModel):
    """简历中的论文自述。AI 仅做语义提取，不依赖关键词匹配。"""

    model_config = ConfigDict(extra="forbid")

    id: str
    evaluation_id: int
    title: str
    venue: str = ""
    year: str = ""
    claimed_role: str = ""
    claimed_status: ClaimedPublicationStatus = ClaimedPublicationStatus.UNKNOWN
    source_quote: str = ""
    rationale: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class PublicationVerificationStatus(str, Enum):
    """外部核验状态。人工确认状态另存，不混为一列。"""

    VERIFIED = "verified"
    PENDING = "pending"
    CONFLICT = "conflict"

    @classmethod
    def all(cls) -> tuple[str, ...]:
        return tuple(member.value for member in cls)


class PublicationVerification(BaseModel):
    """论文的外部核验事实。可独立重试，不重跑整份评估。"""

    model_config = ConfigDict(extra="forbid")

    id: int
    claim_id: str
    source: Literal["openalex", "aminer", "manual"]
    matched_title: str = ""
    verified_status: PublicationVerificationStatus = PublicationVerificationStatus.PENDING
    author_position_match: Literal["match", "mismatch", "pending"] = "pending"
    identity_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    conflicts: list[str] = Field(default_factory=list)
    failure_reason: str = ""
    checked_at: datetime | None = None


# ---------------------------------------------------------------------------
# 入库身份归并
# ---------------------------------------------------------------------------


class IdentityDecision(str, Enum):
    """入库身份归并的决策结果。"""

    NEW = "new"
    MATCHED = "matched"
    NEEDS_REVIEW = "needs_review"
    CONFLICT = "conflict"

    @classmethod
    def all(cls) -> tuple[str, ...]:
        return tuple(member.value for member in cls)


class IdentityEvidence(BaseModel):
    """入库前收集到的身份证据。"""

    model_config = ConfigDict(extra="forbid")

    stable_ids: dict[str, str] = Field(default_factory=dict)
    name_variants: list[str] = Field(default_factory=list)
    emails: list[str] = Field(default_factory=list)
    affiliations: list[str] = Field(default_factory=list)
    timeline: list[dict[str, Any]] = Field(default_factory=list)
    directions: list[str] = Field(default_factory=list)
    publications: list[dict[str, Any]] = Field(default_factory=list)


class IdentityResolution(BaseModel):
    """入库身份归并输出。仅返回决策与证据，不回写 HR 状态。"""

    model_config = ConfigDict(extra="forbid")

    matched_person_id: str | None = None
    decision: IdentityDecision
    confidence: float = Field(ge=0.0, le=1.0)
    supporting_evidence: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 外部事实（人才知识库与人物调查共享）
# ---------------------------------------------------------------------------


class ExternalFactVerification(str, Enum):
    """外部事实的人工核验状态。"""

    CONFIRMED = "confirmed"
    PENDING = "pending"
    CONFLICT = "conflict"
    DISPROVED = "disproved"
    SUPERSEDED = "superseded"

    @classmethod
    def all(cls) -> tuple[str, ...]:
        return tuple(member.value for member in cls)


class ExternalFact(BaseModel):
    """外部事实版本。重新检索时不覆盖旧记录，只追加新版本。"""

    model_config = ConfigDict(extra="forbid")

    id: int
    person_id: str
    source: str
    fact_type: str
    identity_key: str
    dedupe_key: str
    payload: dict[str, Any] = Field(default_factory=dict)
    source_url: str = ""
    verification_status: ExternalFactVerification = ExternalFactVerification.PENDING
    valid_from: datetime
    superseded_at: datetime | None = None
    supersedes_id: int | None = None
    query_context: dict[str, Any] = Field(default_factory=dict)
    raw_payload_hash: str = ""


# ---------------------------------------------------------------------------
# Track 推荐
# ---------------------------------------------------------------------------


class TrackRecommendation(BaseModel):
    """基于简历能力证据的宽泛 Track 推荐（评估输出的一部分）。"""

    model_config = ConfigDict(extra="forbid")

    evaluation_id: int
    tracks: list[dict[str, Any]] = Field(default_factory=list)


__all__ = [
    "ResumeSubmission",
    "ResumeVersion",
    "CandidateSourceKind",
    "CandidateSource",
    "Candidate",
    "EngagementStatus",
    "EngagementStatusChange",
    "ClaimedPublicationStatus",
    "PublicationClaim",
    "PublicationVerificationStatus",
    "PublicationVerification",
    "IdentityDecision",
    "IdentityEvidence",
    "IdentityResolution",
    "ExternalFactVerification",
    "ExternalFact",
    "TrackRecommendation",
]
