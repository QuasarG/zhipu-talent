from __future__ import annotations

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import declarative_base, relationship


Base = declarative_base()


dimension_evidence_links = Table(
    "dimension_evidence_links",
    Base.metadata,
    Column("dimension_score_id", Integer, ForeignKey("dimension_scores.id", ondelete="CASCADE"), primary_key=True),
    Column("evidence_id", Integer, ForeignKey("evaluation_evidence.id", ondelete="CASCADE"), primary_key=True),
)

assignment_evidence_links = Table(
    "assignment_evidence_links",
    Base.metadata,
    Column("track_assignment_id", Integer, ForeignKey("track_assignments.id", ondelete="CASCADE"), primary_key=True),
    Column("evidence_id", Integer, ForeignKey("evaluation_evidence.id", ondelete="CASCADE"), primary_key=True),
)

track_evaluation_evidence_links = Table(
    "track_evaluation_evidence_links",
    Base.metadata,
    Column("track_evaluation_id", Integer, ForeignKey("track_evaluations.id", ondelete="CASCADE"), primary_key=True),
    Column("evidence_id", Integer, ForeignKey("evaluation_evidence.id", ondelete="CASCADE"), primary_key=True),
)


class SchemaVersionORM(Base):
    __tablename__ = "schema_versions"

    version = Column(Integer, primary_key=True)
    description = Column(String(255), nullable=False)
    applied_at = Column(DateTime, server_default=func.now(), nullable=False)


class CandidateORM(Base):
    """候选人档案。

    阶段 1 之后语义被拆开：

    - 阶段 1 之前：CandidateORM 同时承担"刚导入的简历" + "已入人才库人才"。
    - 阶段 1 之后：CandidateORM 只表示已入人才库的人才档案，新增
      ``person_id``、``engagement_status``、``current_resume_version_id``、
      ``admitted_at`` 字段；旧 ``group`` 列保留作为审计与前端兼容，
      但不再被自动改写（详见阶段 4 workbench 拆解）。

    评估完成前的"占位候选人"角色由 ``ResumeSubmissionORM`` 承担，
    但保留 id 复用以便兼容老 workbench 路由（迁移期允许）。
    """

    __tablename__ = "candidates"

    id = Column(String(32), primary_key=True)
    name = Column(String(128), default="")
    target_role = Column(String(256), default="")
    stage = Column(String(128), default="")
    raw_text = Column(Text, default="")
    group = Column(String(32), default="pending", index=True)
    import_level = Column(String(8), default="")
    import_category = Column(String(128), default="")
    import_confidence = Column(Float, default=0.0)
    education = Column(Text, default="")
    directions = Column(Text, default="")
    experiences = Column(Text, default="")
    projects = Column(Text, default="")
    publications = Column(Text, default="")
    skills = Column(Text, default="")
    screening_tags = Column(Text, default="")
    source_format = Column(String(32), default="text")
    document_analysis = Column(Text, default="")
    # 导入阶段论文核验结果（OpenAlex）：{alignments:[...], warnings:[...]}
    # 与 EvaluationORM.academic_report 同构，但挂在 candidate 上，
    # 导入时即可产出，不等评估。
    academic_report = Column(JSON, default=dict)
    # 论文核验状态：none | running | done
    # 与 academic_report 配合：done 时 verdict 数据已就绪
    academic_check_status = Column(String(16), default="none", nullable=False)
    academic_check_at = Column(DateTime)
    # 阶段 1 新增列（保留原 group 作为审计，迁移期允许 NULL）
    person_id = Column(String(36), ForeignKey("persons.id", ondelete="SET NULL"), index=True)
    engagement_status = Column(String(32), default="newly_admitted", nullable=False)
    # 阶段 13：HR 手动补充的信息（简历上没有的），评估时注入 raw_text
    supplementary_info = Column(Text, default="")
    # 兼容老 candidate ↔ resume_versions 关系：不带 FK，业务层校验。
    current_resume_version_id = Column(String(36), index=True)
    admitted_at = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    evaluations = relationship("EvaluationORM", back_populates="candidate", cascade="all, delete-orphan")
    sources = relationship("CandidateSourceORM", back_populates="candidate", cascade="all, delete-orphan")
    engagement_history = relationship(
        "EngagementStatusHistoryORM",
        back_populates="candidate",
        cascade="all, delete-orphan",
        order_by="EngagementStatusHistoryORM.created_at",
    )


class EvaluationORM(Base):
    __tablename__ = "evaluations"
    __table_args__ = (
        Index("ix_evaluations_candidate_created", "candidate_id", "created_at"),
        Index("ix_evaluations_status", "status"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    candidate_id = Column(String(32), ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False)
    person_id = Column(String(36), ForeignKey("persons.id", ondelete="SET NULL"))
    config_version = Column(String(64), default="")
    status = Column(String(24), default="running", nullable=False)
    error_message = Column(Text, default="")
    overall_score = Column(Integer, default=0)
    level = Column(String(8), default="")
    tier = Column(String(64), default="")
    decision_method = Column(Text, default="")
    one_liner = Column(Text, default="")
    core_strengths = Column(JSON, default=list)
    potential_risks = Column(JSON, default=list)
    interview_questions = Column(JSON, default=list)
    cultivation_direction = Column(JSON, default=list)
    recommended_tracks = Column(JSON, default=list)
    stage_profile = Column(String(64), default="")
    academic_report = Column(JSON, default=dict)
    critic_flags = Column(JSON, default=list)
    normalized_education = Column(JSON, default=list)
    screening_tags = Column(JSON, default=list)
    common_score = Column(Float, default=0.0)
    document_score = Column(Float, default=0.0)
    routing_confidence = Column(Float, default=0.0)
    evaluation_mode = Column(String(64), default="multi_track_v1")
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    completed_at = Column(DateTime)

    candidate = relationship("CandidateORM", back_populates="evaluations")
    person = relationship("PersonORM", back_populates="evaluations")
    node_runs = relationship(
        "EvaluationNodeRunORM",
        back_populates="evaluation",
        cascade="all, delete-orphan",
        order_by="EvaluationNodeRunORM.sequence",
    )
    evidence_items = relationship(
        "EvaluationEvidenceORM",
        back_populates="evaluation",
        cascade="all, delete-orphan",
        order_by="EvaluationEvidenceORM.order_index",
    )
    track_assignments = relationship(
        "TrackAssignmentORM",
        back_populates="evaluation",
        cascade="all, delete-orphan",
        order_by="TrackAssignmentORM.order_index",
    )
    track_evaluations = relationship(
        "TrackEvaluationORM",
        back_populates="evaluation",
        cascade="all, delete-orphan",
        order_by="TrackEvaluationORM.order_index",
    )
    dimension_scores = relationship(
        "DimensionScoreORM",
        back_populates="evaluation",
        cascade="all, delete-orphan",
        order_by="DimensionScoreORM.order_index",
    )


class EvaluationNodeRunORM(Base):
    __tablename__ = "evaluation_node_runs"
    __table_args__ = (
        UniqueConstraint("evaluation_id", "node_key", name="uq_node_run_evaluation_node"),
        Index("ix_node_runs_evaluation_phase", "evaluation_id", "phase"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    evaluation_id = Column(Integer, ForeignKey("evaluations.id", ondelete="CASCADE"), nullable=False)
    node_key = Column(String(64), nullable=False)
    phase = Column(String(32), nullable=False)
    status = Column(String(24), nullable=False)
    message = Column(Text, default="")
    sequence = Column(Integer, default=0, nullable=False)
    started_at = Column(DateTime, server_default=func.now(), nullable=False)
    completed_at = Column(DateTime)

    evaluation = relationship("EvaluationORM", back_populates="node_runs")


class EvaluationEvidenceORM(Base):
    __tablename__ = "evaluation_evidence"
    __table_args__ = (
        UniqueConstraint("evaluation_id", "evidence_key", name="uq_evidence_evaluation_key"),
        Index("ix_evidence_evaluation_dimension", "evaluation_id", "dimension"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    evaluation_id = Column(Integer, ForeignKey("evaluations.id", ondelete="CASCADE"), nullable=False)
    evidence_key = Column(String(64), nullable=False)
    dimension = Column(String(64), nullable=False)
    source = Column(Text, default="")
    quote = Column(Text, default="")
    signals = Column(JSON, default=list)
    strength = Column(Integer, default=1)
    has_metric = Column(Boolean, default=False)
    has_specific_tool = Column(Boolean, default=False)
    has_ownership = Column(Boolean, default=False)
    track_hints = Column(JSON, default=list)
    page = Column(Integer)
    bbox = Column(JSON, default=list)
    extraction_confidence = Column(Float, default=1.0)
    order_index = Column(Integer, default=0, nullable=False)

    evaluation = relationship("EvaluationORM", back_populates="evidence_items")


class TrackAssignmentORM(Base):
    __tablename__ = "track_assignments"
    __table_args__ = (
        UniqueConstraint("evaluation_id", "track", name="uq_assignment_evaluation_track"),
        Index("ix_assignments_track_weight", "track", "weight"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    evaluation_id = Column(Integer, ForeignKey("evaluations.id", ondelete="CASCADE"), nullable=False)
    track = Column(String(32), nullable=False)
    weight = Column(Float, nullable=False)
    confidence = Column(Float, nullable=False)
    rationale = Column(Text, default="")
    order_index = Column(Integer, default=0, nullable=False)

    evaluation = relationship("EvaluationORM", back_populates="track_assignments")
    evidence_items = relationship("EvaluationEvidenceORM", secondary=assignment_evidence_links)


class TrackEvaluationORM(Base):
    __tablename__ = "track_evaluations"
    __table_args__ = (
        UniqueConstraint("evaluation_id", "track", name="uq_track_evaluation_track"),
        Index("ix_track_evaluations_track_score", "track", "calibrated_score"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    evaluation_id = Column(Integer, ForeignKey("evaluations.id", ondelete="CASCADE"), nullable=False)
    track = Column(String(32), nullable=False)
    label = Column(String(128), default="")
    weight = Column(Float, nullable=False)
    confidence = Column(Float, nullable=False)
    raw_score = Column(Float, default=0.0)
    calibrated_score = Column(Float, default=0.0)
    risk_notes = Column(JSON, default=list)
    critic_flags = Column(JSON, default=list)
    order_index = Column(Integer, default=0, nullable=False)

    evaluation = relationship("EvaluationORM", back_populates="track_evaluations")
    dimension_scores = relationship(
        "DimensionScoreORM",
        back_populates="track_evaluation",
        order_by="DimensionScoreORM.order_index",
        passive_deletes=True,
        overlaps="dimension_scores,evaluation",
    )
    evidence_items = relationship("EvaluationEvidenceORM", secondary=track_evaluation_evidence_links)


class DimensionScoreORM(Base):
    __tablename__ = "dimension_scores"
    __table_args__ = (
        UniqueConstraint(
            "evaluation_id",
            "scope",
            "track_key",
            "dimension_key",
            name="uq_dimension_evaluation_scope_track_key",
        ),
        Index("ix_dimensions_evaluation_scope", "evaluation_id", "scope"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    evaluation_id = Column(Integer, ForeignKey("evaluations.id", ondelete="CASCADE"), nullable=False)
    track_evaluation_id = Column(Integer, ForeignKey("track_evaluations.id", ondelete="CASCADE"))
    scope = Column(String(16), nullable=False)
    track_key = Column(String(32), default="", nullable=False)
    dimension_key = Column(String(64), nullable=False)
    label = Column(String(128), default="")
    score = Column(Float, default=0.0)
    weighted_score = Column(Float, default=0.0)
    max_points = Column(Float, default=0.0)
    rationale = Column(Text, default="")
    risk_notes = Column(JSON, default=list)
    order_index = Column(Integer, default=0, nullable=False)

    evaluation = relationship("EvaluationORM", back_populates="dimension_scores", overlaps="dimension_scores,track_evaluation")
    track_evaluation = relationship("TrackEvaluationORM", back_populates="dimension_scores", overlaps="dimension_scores,evaluation")
    evidence_items = relationship("EvaluationEvidenceORM", secondary=dimension_evidence_links)


class PersonORM(Base):
    """人员主档：同一自然人多次评估/邀请归并到一档。

    阶段 2 引入稳定标识 ``identifiers``（JSON 字典，key 为邮箱/ORCID/
    AMiner ID 等），用于入库身份归并的第一层确定性匹配。
    """

    __tablename__ = "persons"

    id = Column(String(36), primary_key=True)
    name = Column(String(128), default="", index=True)
    org = Column(String(256), default="")
    direction = Column(String(256), default="")
    fingerprint = Column(String(64), unique=True, nullable=False, index=True)
    person_type = Column(String(32), default="student")
    # 阶段 2：稳定标识字典（{email/orcid/aminer_id/...: value}）。
    identifiers = Column(JSON, default=dict)
    # 阶段 12：结构化教育经历 [{school, degree, period}]；org 始终等于最高学历学校。
    schools = Column(JSON, default=list)
    # 阶段 2：是否处于身份冲突（pending merge review）状态。
    identity_conflict = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    evaluations = relationship("EvaluationORM", back_populates="person")
    reputation_reports = relationship("ReputationReportORM", back_populates="person", cascade="all, delete-orphan")
    external_facts = relationship("ExternalFactORM", back_populates="person", cascade="all, delete-orphan")


class ExternalFactORM(Base):
    """外部证据缓存 + 版本化外部事实（阶段 6）。

    旧字段：source / fact_type / payload / source_url / fetched_at / expires_at
    新字段（阶段 6）：
    - identity_key         稳定身份键（person_id|fact_type|subject）
    - dedupe_key           稳定去重键（source|fact_type|title|source_url hash）
    - verification_status  confirmed/pending/conflict/disproved/superseded
    - valid_from           本版本生效起始时间
    - supersedes_id        替代了哪条旧事实；NULL 表示首版
    - superseded_at        被新版本替代的时间；NULL 表示当前版本
    - query_context        触发本次查询的上下文
    - raw_payload_hash     原始 payload 哈希，用于检测内容是否变化
    """

    __tablename__ = "external_facts"
    __table_args__ = (
        Index("ix_external_facts_person_source", "person_id", "source"),
        Index("ix_external_facts_identity_key", "identity_key"),
        Index("ix_external_facts_dedupe_status", "dedupe_key", "verification_status"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    person_id = Column(String(36), ForeignKey("persons.id", ondelete="CASCADE"), nullable=False)
    source = Column(String(32), nullable=False)
    fact_type = Column(String(64), nullable=False)
    payload = Column(JSON, default=dict)
    source_url = Column(Text, default="")
    fetched_at = Column(DateTime, server_default=func.now(), nullable=False)
    expires_at = Column(DateTime)
    # 阶段 6 版本字段
    identity_key = Column(String(128), default="")
    dedupe_key = Column(String(64), default="")
    verification_status = Column(String(16), default="pending", nullable=False)
    valid_from = Column(DateTime)
    supersedes_id = Column(Integer, ForeignKey("external_facts.id", ondelete="SET NULL"))
    superseded_at = Column(DateTime)
    query_context = Column(JSON, default=dict)
    raw_payload_hash = Column(String(64), default="")

    person = relationship("PersonORM", back_populates="external_facts")


class ReputationReportORM(Base):
    """舆情风险报告：红/黄/绿 + 事件证据，人工复核后才终态。"""

    __tablename__ = "reputation_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    person_id = Column(String(36), ForeignKey("persons.id", ondelete="CASCADE"), nullable=False)
    evaluation_id = Column(Integer, ForeignKey("evaluations.id", ondelete="SET NULL"))
    level = Column(String(8), default="green")
    events = Column(JSON, default=list)
    review_status = Column(String(24), default="pending", index=True)
    reviewer = Column(String(128), default="")
    review_note = Column(Text, default="")
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    reviewed_at = Column(DateTime)

    person = relationship("PersonORM", back_populates="reputation_reports")


class TaskORM(Base):
    """异步任务：外部核查等慢操作的状态机。"""

    __tablename__ = "tasks"

    id = Column(String(36), primary_key=True)
    task_type = Column(String(32), nullable=False)
    status = Column(String(24), default="queued", index=True)
    payload = Column(JSON, default=dict)
    progress = Column(JSON, default=dict)
    error_message = Column(Text, default="")
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)


# ---------------------------------------------------------------------------
# 阶段 1 新表（schema_version=7）：提交 / 版本 / 来源 / 跟进 / 身份归并
# ---------------------------------------------------------------------------


CANDIDATE_SOURCE_KINDS = ("resume_evaluation", "person_investigation")


class ResumeSubmissionORM(Base):
    """一次简历导入动作。评估完成前不是人才，只是待评估材料。

    ``CandidateORM`` 现阶段仍承担"占位候选人"角色，迁移期允许 CandidateORM
    拥有相同的 ``id`` 字符串用于兼容；完成阶段 1.7 后会切断 id 复用。
    """

    __tablename__ = "resume_submissions"
    __table_args__ = (
        Index("ix_resume_submissions_status_created", "parse_status", "created_at"),
    )

    id = Column(String(36), primary_key=True)
    # 兼容老 CandidateORM id：保留为业务字段但不带 FK，避免与
    # CandidateORM.current_resume_version_id 形成 FK 环。
    candidate_id = Column(String(32), index=True)
    person_id = Column(String(36), ForeignKey("persons.id", ondelete="SET NULL"))
    source_format = Column(String(16), nullable=False)
    filename = Column(String(256), default="")
    raw_text = Column(Text, default="")
    structured = Column(JSON, default=dict)
    parse_status = Column(String(16), default="pending", nullable=False)
    parse_error = Column(Text, default="")
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)


class ResumeVersionORM(Base):
    """同一份简历在不同评估轮次的版本。原文永不被新版本覆盖。"""

    __tablename__ = "resume_versions"
    __table_args__ = (
        UniqueConstraint("submission_id", "version", name="uq_resume_version_submission_version"),
        Index("ix_resume_versions_submission", "submission_id"),
    )

    id = Column(String(36), primary_key=True)
    submission_id = Column(String(36), ForeignKey("resume_submissions.id", ondelete="CASCADE"), nullable=False)
    version = Column(Integer, nullable=False)
    raw_text = Column(Text, default="")
    structured = Column(JSON, default=dict)
    note = Column(String(256), default="")
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class CandidateSourceORM(Base):
    """人才档案可以同时拥有多个来源（与 CANDIDATE_SOURCE_KINDS 对应）。

    唯一约束 (candidate_id, source_kind) 保证同一来源不被重复追加；
    评估成功后会追加 ``resume_evaluation``，人物调查后人工加入追加
    ``person_investigation``。
    """

    __tablename__ = "candidate_sources"
    __table_args__ = (
        UniqueConstraint("candidate_id", "source_kind", name="uq_candidate_source_kind"),
        Index("ix_candidate_sources_kind", "source_kind"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    candidate_id = Column(String(32), ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False)
    source_kind = Column(String(32), nullable=False)
    source_record_id = Column(String(64), default="")
    note = Column(Text, default="")
    created_by = Column(String(128), default="")
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    candidate = relationship("CandidateORM", back_populates="sources")


class EngagementStatusHistoryORM(Base):
    """HR 跟进状态变更的不可变审计记录。

    每次人工修改都新增一行；HR 跟进状态与能力评分、推荐 Track、论文核验
    完全独立。
    """

    __tablename__ = "engagement_status_history"
    __table_args__ = (
        Index("ix_engagement_history_candidate_created", "candidate_id", "created_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    candidate_id = Column(String(32), ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False)
    previous_status = Column(String(32), default="")
    current_status = Column(String(32), nullable=False)
    changed_by = Column(String(128), nullable=False)
    note = Column(Text, default="")
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    candidate = relationship("CandidateORM", back_populates="engagement_history")


class IdentitySuggestionORM(Base):
    """入库身份归并节点的待审核建议。

    首版策略：稳定标识精确一致可自动归并；AI 模糊结果一律先生成
    ``pending`` 建议，由人工确认后由 ``MergeAuditORM`` 串联处理。
    """

    __tablename__ = "identity_suggestions"
    __table_args__ = (
        Index("ix_identity_suggestions_status", "decision", "status"),
        Index("ix_identity_suggestions_submission", "submission_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    submission_id = Column(String(36), ForeignKey("resume_submissions.id", ondelete="CASCADE"), nullable=False)
    matched_person_id = Column(String(36), ForeignKey("persons.id", ondelete="SET NULL"))
    decision = Column(String(16), nullable=False)
    confidence = Column(Float, default=0.0, nullable=False)
    supporting_evidence = Column(JSON, default=list)
    conflicts = Column(JSON, default=list)
    status = Column(String(16), default="pending", nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    reviewed_at = Column(DateTime)
    reviewer = Column(String(128), default="")
    review_note = Column(Text, default="")


class MergeAuditORM(Base):
    """人工合并 / 解除合并的审计记录。"""

    __tablename__ = "merge_audit"
    __table_args__ = (
        Index("ix_merge_audit_action", "action", "created_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    action = Column(String(16), nullable=False)  # merge / unmerge
    primary_person_id = Column(String(36), ForeignKey("persons.id", ondelete="CASCADE"), nullable=False)
    merged_person_id = Column(String(36), ForeignKey("persons.id", ondelete="CASCADE"), nullable=False)
    operator = Column(String(128), nullable=False)
    note = Column(Text, default="")
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


# ---------------------------------------------------------------------------
# 阶段 3：论文自述与外部核验拆表（schema_version=9）
# ---------------------------------------------------------------------------


class PublicationClaimORM(Base):
    """简历中的论文自述（候选人说的话，不等于外部事实）。

    AI 仅做语义提取，不依赖关键词匹配；保留原文证据、理由和置信度。
    """

    __tablename__ = "publication_claims"
    __table_args__ = (
        UniqueConstraint("evaluation_id", "claim_key", name="uq_claim_evaluation_key"),
        Index("ix_publication_claims_evaluation", "evaluation_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    evaluation_id = Column(Integer, ForeignKey("evaluations.id", ondelete="CASCADE"), nullable=False)
    claim_key = Column(String(64), nullable=False)
    title = Column(Text, default="")
    venue = Column(Text, default="")
    year = Column(String(16), default="")
    claimed_role = Column(String(32), default="")
    # 受控枚举：draft/submitted/in_review/accepted/published/unknown
    claimed_status = Column(String(32), default="unknown", nullable=False)
    source_quote = Column(Text, default="")
    rationale = Column(Text, default="")
    confidence = Column(Float, default=0.0, nullable=False)
    order_index = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    verification = relationship(
        "PublicationVerificationORM",
        back_populates="claim",
        uselist=False,
        cascade="all, delete-orphan",
    )


class PublicationVerificationORM(Base):
    """论文的外部核验事实。与自述解耦，可独立重试，不重跑整份评估。

    核验状态枚举：verified / pending / conflict；
    人工确认状态另存在 ``human_status``，不混为一列。
    """

    __tablename__ = "publication_verifications"
    __table_args__ = (
        Index("ix_publication_verifications_claim", "claim_id"),
        Index("ix_publication_verifications_status", "verified_status"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    claim_id = Column(Integer, ForeignKey("publication_claims.id", ondelete="CASCADE"), nullable=False)
    source = Column(String(32), default="openalex", nullable=False)
    matched_title = Column(Text, default="")
    verified_status = Column(String(16), default="pending", nullable=False)
    # match / mismatch / pending
    author_position_match = Column(String(16), default="pending", nullable=False)
    identity_confidence = Column(Float, default=0.0, nullable=False)
    conflicts = Column(JSON, default=list)
    failure_reason = Column(Text, default="")
    checked_at = Column(DateTime)
    # 人工确认：unreviewed / confirmed / dismissed
    human_status = Column(String(16), default="unreviewed", nullable=False)
    human_reviewer = Column(String(128), default="")
    human_note = Column(Text, default="")
    human_reviewed_at = Column(DateTime)

    claim = relationship("PublicationClaimORM", back_populates="verification")
