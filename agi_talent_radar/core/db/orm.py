from __future__ import annotations

import uuid
from datetime import datetime

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
from sqlalchemy.dialects import mysql


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
    publication_score = Column(Float, default=0.0)
    safety_net_score = Column(Float, default=0.0)
    interview_decision = Column(String(16), default="")
    best_fit_jd_id = Column(String(36), default="")
    best_fit_jd_title = Column(String(200), default="")
    decision_summary = Column(Text, default="")
    job_fit_assessments = Column(JSON, default=list)
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
    # 人才库分组（一对多：一人只在一个分组，NULL=未分组；全局共享）
    group_id = Column(String(36), ForeignKey("talent_groups.id", ondelete="SET NULL"), nullable=True, index=True)
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


CANDIDATE_SOURCE_KINDS = ("resume_import", "resume_evaluation", "person_investigation")


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


class ShareTokenORM(Base):
    """人才档案只读分享令牌。

    一次分享 = 一个 person 的只读视图；令牌随机不可猜，可吊销可续期。
    不落访问日志（内部分享场景，避免无谓表膨胀）。
    """

    __tablename__ = "share_tokens"
    __table_args__ = (Index("ix_share_tokens_token", "token", unique=True),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    token = Column(String(43), nullable=False, unique=True)  # urlsafe base64 32B
    person_id = Column(String(36), ForeignKey("persons.id", ondelete="CASCADE"), nullable=False)
    created_by = Column(String(128), default="")
    revoked = Column(Boolean, default=False, nullable=False)
    expires_at = Column(DateTime, nullable=True)  # NULL = 永久
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


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


# ---------------------------------------------------------------------------
# 人才问答：会话与消息持久化
# ---------------------------------------------------------------------------


def _new_uuid() -> str:
    return uuid.uuid4().hex


class TalentGroupORM(Base):
    """人才库分组：纯手工分类，全局共享，一对多挂 persons.group_id。"""

    __tablename__ = "talent_groups"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    name = Column(String(64), nullable=False)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class JdEntryORM(Base):
    """JD 池条目及其当前岗位评估卡。

    ``status/spec`` 暂留作旧数据兼容，新准入流程只读取岗位卡字段；JD 是否参与
    某次评估由批次显式选择决定，不再由全局 active 状态决定。
    """

    __tablename__ = "jd_entries"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    title = Column(String(200), nullable=False)
    team = Column(String(200), default="")
    raw_text = Column(Text, nullable=False)
    track_key = Column(String(64), default="", index=True)
    spec = Column(Text, default="")
    spec_version = Column(Integer, default=0)
    status = Column(String(16), default="draft", index=True)
    supplements = Column(JSON, default=list)
    assessment_card = Column(JSON, default=dict)
    card_status = Column(String(16), default="generating", nullable=False, index=True)
    card_error = Column(Text, default="")
    card_run_trace = Column(JSON, default=list)
    card_model_usage = Column(JSON, default=list)
    archived = Column(Boolean, default=False, nullable=False, index=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)


class InterviewAssessmentBatchORM(Base):
    """一次显式选择候选人与 JD 后形成的面试准入评估批次。"""

    __tablename__ = "interview_assessment_batches"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    owner_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), index=True)
    status = Column(String(24), default="queued", nullable=False, index=True)
    candidate_ids = Column(JSON, default=list)
    jd_ids = Column(JSON, default=list)
    total_pairs = Column(Integer, default=0, nullable=False)
    completed_pairs = Column(Integer, default=0, nullable=False)
    failed_pairs = Column(Integer, default=0, nullable=False)
    cancelled_pairs = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)


class CandidateJdAssessmentORM(Base):
    """候选人–JD 的唯一当前报告；成功重评时原子覆盖。"""

    __tablename__ = "candidate_jd_assessments"
    __table_args__ = (
        UniqueConstraint("candidate_id", "jd_id", name="uq_candidate_jd_current_assessment"),
        Index("ix_candidate_jd_valid_decision", "jd_id", "is_valid", "decision"),
    )

    id = Column(String(36), primary_key=True, default=_new_uuid)
    candidate_id = Column(
        String(32), ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    jd_id = Column(
        String(36), ForeignKey("jd_entries.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status = Column(String(24), default="completed", nullable=False, index=True)
    is_valid = Column(Boolean, default=True, nullable=False, index=True)
    invalid_reason = Column(Text, default="")
    decision = Column(String(16), nullable=False)
    total_score = Column(Float, default=0.0, nullable=False)
    task_assessments = Column(JSON, default=list)
    review_corrections = Column(JSON, default=list)
    interview_focus = Column(JSON, default=list)
    model_usage = Column(JSON, default=list)
    run_trace = Column(JSON, default=list)
    input_fingerprint = Column(String(64), default="", nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)


class InterviewAssessmentRunORM(Base):
    """配对的一次运行尝试；运行成功后结果晋升为当前报告。"""

    __tablename__ = "interview_assessment_runs"
    __table_args__ = (
        UniqueConstraint("batch_id", "candidate_id", "jd_id", name="uq_batch_candidate_jd_run"),
        Index("ix_interview_runs_pair_status", "candidate_id", "jd_id", "status"),
    )

    id = Column(String(36), primary_key=True, default=_new_uuid)
    batch_id = Column(
        String(36), ForeignKey("interview_assessment_batches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    candidate_id = Column(
        String(32), ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    jd_id = Column(
        String(36), ForeignKey("jd_entries.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status = Column(String(24), default="queued", nullable=False, index=True)
    current_node = Column(String(64), default="")
    input_fingerprint = Column(String(64), default="", nullable=False)
    staged_result = Column(JSON, default=dict)
    run_trace = Column(JSON, default=list)
    model_usage = Column(JSON, default=list)
    error_message = Column(Text, default="")
    cancellation_requested = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)


class InterviewAssessmentPairLockORM(Base):
    """候选人–JD 的跨用户运行锁；终态运行必须释放。"""

    __tablename__ = "interview_assessment_pair_locks"

    candidate_id = Column(
        String(32), ForeignKey("candidates.id", ondelete="CASCADE"), primary_key=True
    )
    jd_id = Column(
        String(36), ForeignKey("jd_entries.id", ondelete="CASCADE"), primary_key=True
    )
    run_id = Column(
        String(36), ForeignKey("interview_assessment_runs.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    acquired_at = Column(DateTime, server_default=func.now(), nullable=False)


class ConversationORM(Base):
    """一段人才问答会话（按 owner 隔离，只有聊天记录分用户）。"""

    __tablename__ = "conversations"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    owner_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(200), default="新对话")
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    messages = relationship(
        "ChatMessageORM",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ChatMessageORM.created_at",
    )


class ChatMessageORM(Base):
    """会话中的单条消息。

    ``content`` 为 JSON segments：``{segments: [{type:"text",...} | {type:"tool",...}
    | {type:"action",...}]}``；``pending_action`` 仅在 status=awaiting_action 时有值。
    """

    __tablename__ = "chat_messages"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    conversation_id = Column(
        String(36), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role = Column(String(16), nullable=False)  # user / assistant
    content = Column(JSON, default=dict)
    citations = Column(JSON)
    status = Column(String(24), default="completed", nullable=False)  # completed / awaiting_action
    pending_action = Column(JSON)
    # 微秒精度保序（MySQL 用 DATETIME(6)，sqlite 测试走通用 DateTime）：秒级会让同秒消息顺序乱掉
    # 用本地时间：与 MySQL NOW()/func.now() 的会话时区一致，混用 UTC 会把新消息排到旧消息前面
    created_at = Column(
        DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"),
        default=lambda: datetime.now(),
        nullable=False,
    )

    conversation = relationship("ConversationORM", back_populates="messages")


class UserORM(Base):
    """平台账号：仅用于会话隔离，不开放注册。"""

    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    username = Column(String(64), nullable=False, unique=True, index=True)
    password_hash = Column(String(256), nullable=False)
    display_name = Column(String(64), default="")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


# ---------------------------------------------------------------------------
# Z.AI Scholarship 2026 奖学金初筛（独立于书院简历评估）
# ---------------------------------------------------------------------------


class ScholarshipApplicationORM(Base):
    """奖学金申请人主档。status 状态机：
    imported → eligible / material_incomplete / ineligible → scored → finalized。
    """

    __tablename__ = "scholarship_applications"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    name = Column(String(128), nullable=False)
    degree_type = Column(String(16), default="")           # master / phd
    expected_graduation = Column(String(16), default="")   # YYYY-MM
    direction = Column(String(256), default="")
    school = Column(String(256), default="")
    advisors = Column(JSON, default=list)                  # 推荐导师姓名列表
    status = Column(String(24), default="imported", index=True)
    screening_detail = Column(JSON, default=dict)          # 缺项/资格原因 + feishu 元信息
    brand_bonus = Column(Float, default=0.0)               # 手动品牌加分（不进 LLM 评分）
    brand_note = Column(Text, default="")
    # 飞书问卷同步字段（webhook/反查写入；为空表示非飞书来源）
    feishu_record_id = Column(String(64), default="", index=True)  # rec 开头，幂等去重键
    name_en = Column(String(128), default="")
    phone = Column(String(64), default="")
    email = Column(String(256), default="")
    country = Column(String(128), default="")
    lab = Column(String(256), default="")
    advisor_title = Column(String(256), default="")        # 导师单位/职务
    grade = Column(String(64), default="")                 # 当前年级原始文案
    research_summary = Column(Text, default="")            # 研究方向简述
    education_history = Column(Text, default="")           # 教育与科研经历
    submitted_at = Column(DateTime)                        # 飞书提交时间
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    materials = relationship(
        "ScholarshipMaterialORM", back_populates="application",
        cascade="all, delete-orphan", order_by="ScholarshipMaterialORM.id",
    )
    evaluations = relationship(
        "ScholarshipEvaluationORM", back_populates="application",
        cascade="all, delete-orphan", order_by="ScholarshipEvaluationORM.id",
    )
    reputation_items = relationship(
        "ScholarshipReputationItemORM", back_populates="application",
        cascade="all, delete-orphan", order_by="ScholarshipReputationItemORM.id",
    )


class ScholarshipMaterialORM(Base):
    """申请人的一份材料：form / resume / supplementary / achievement / letter。"""

    __tablename__ = "scholarship_materials"

    id = Column(Integer, primary_key=True, autoincrement=True)
    application_id = Column(
        String(36), ForeignKey("scholarship_applications.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    kind = Column(String(24), nullable=False)
    filename = Column(String(256), default="")
    raw_text = Column(Text, default="")
    structured = Column(JSON, default=dict)                # 简历结构化等
    advisor_name = Column(String(128), default="")         # kind=letter 时的推荐导师
    anonymized_text = Column(Text, default="")             # 脱敏后的文本（评分只用它）
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    application = relationship("ScholarshipApplicationORM", back_populates="materials")


class ScholarshipEvaluationORM(Base):
    """一次脱敏评分结果。"""

    __tablename__ = "scholarship_evaluations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    application_id = Column(
        String(36), ForeignKey("scholarship_applications.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    config_version = Column(String(64), default="")
    status = Column(String(24), default="running", nullable=False)  # running/completed/failed
    blind_score = Column(Float, default=0.0)
    dimensions = Column(JSON, default=list)   # [{key,label,score,max_points,reason}]
    highlights = Column(JSON, default=list)
    risks = Column(JSON, default=list)
    error_message = Column(Text, default="")
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    completed_at = Column(DateTime)

    application = relationship("ScholarshipApplicationORM", back_populates="evaluations")


class ScholarshipReputationItemORM(Base):
    """舆情条目：申请人或推荐导师的正/负面舆情，人工确认后才计分。"""

    __tablename__ = "scholarship_reputation_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    application_id = Column(
        String(36), ForeignKey("scholarship_applications.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    subject = Column(String(128), default="")      # 舆情对象（申请人/导师姓名）
    subject_role = Column(String(16), default="applicant")  # applicant / advisor
    sentiment = Column(String(16), default="negative")      # positive / negative
    title = Column(Text, default="")
    url = Column(Text, default="")
    snippet = Column(Text, default="")
    concern = Column(Text, default="")             # 为什么需要人工判断
    review_status = Column(String(24), default="pending", index=True)  # pending/confirmed/dismissed
    adjustment = Column(Float, default=0.0)        # 确认后写入（负分/正分）
    reviewer = Column(String(128), default="")
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    reviewed_at = Column(DateTime)

    application = relationship("ScholarshipApplicationORM", back_populates="reputation_items")


# ---------------------------------------------------------------------------
# 画像澄清 Agent (grill)：用人需求澄清会话（按 owner 隔离）
# 单表承载一次澄清全过程：画像卡 / 提问大纲 / 对话历史 / 交付物。
# ---------------------------------------------------------------------------


class GrillSessionORM(Base):
    """一段画像澄清会话。

    ``profile`` 画像卡（required_fields/optional_fields/conflicts/converged），
    ``outline`` 提问大纲节点列表，``messages`` 对话历史 [{role, text, tools}]，
    ``deliverables`` finalize 后的画像+JD草稿+筛选标准。
    """

    __tablename__ = "grill_sessions"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    owner_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(200), default="未命名会话")
    profile = Column(JSON, default=dict)
    outline = Column(JSON, default=list)
    messages = Column(JSON, default=list)
    deliverables = Column(JSON, default=None)
    converged = Column(Boolean, default=False)
    running = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
