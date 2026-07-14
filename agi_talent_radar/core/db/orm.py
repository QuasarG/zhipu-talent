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
    projects = Column(Text, default="")
    publications = Column(Text, default="")
    skills = Column(Text, default="")
    screening_tags = Column(Text, default="")
    source_format = Column(String(32), default="text")
    document_analysis = Column(Text, default="")
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    evaluations = relationship("EvaluationORM", back_populates="candidate", cascade="all, delete-orphan")


class EvaluationORM(Base):
    __tablename__ = "evaluations"
    __table_args__ = (
        Index("ix_evaluations_candidate_created", "candidate_id", "created_at"),
        Index("ix_evaluations_status", "status"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    candidate_id = Column(String(32), ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False)
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
