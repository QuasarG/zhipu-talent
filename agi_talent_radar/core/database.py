from __future__ import annotations

import json
import os
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import JSON, Column, DateTime, Float, ForeignKey, Integer, String, Text, create_engine, func
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

from agi_talent_radar.core.models import CandidateEvaluation, CandidateResume, ImportClassification


load_dotenv()

Base = declarative_base()


class CandidateORM(Base):
    __tablename__ = "candidates"

    id = Column(String(32), primary_key=True)
    name = Column(String(128), default="")
    target_role = Column(String(256), default="")
    stage = Column(String(128), default="")
    raw_text = Column(Text, default="")
    import_category = Column(String(128), default="")
    import_confidence = Column(Float, default=0.0)
    education = Column(Text, default="")
    directions = Column(Text, default="")
    projects = Column(Text, default="")
    publications = Column(Text, default="")
    skills = Column(Text, default="")
    screening_tags = Column(Text, default="")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    evaluations = relationship("EvaluationORM", back_populates="candidate", cascade="all, delete-orphan")


class EvaluationORM(Base):
    __tablename__ = "evaluations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    candidate_id = Column(String(32), ForeignKey("candidates.id"), nullable=False)
    overall_score = Column(Integer, default=0)
    level = Column(String(8), default="")
    tier = Column(String(64), default="")
    one_liner = Column(Text, default="")
    core_strengths = Column(JSON, default=list)
    potential_risks = Column(JSON, default=list)
    interview_questions = Column(JSON, default=list)
    cultivation_direction = Column(JSON, default=list)
    dimension_scores = Column(JSON, default=list)
    evidence = Column(JSON, default=list)
    critic_flags = Column(JSON, default=list)
    evaluation_mode = Column(String(64), default="deepseek_ai_only")
    created_at = Column(DateTime, server_default=func.now())

    candidate = relationship("CandidateORM", back_populates="evaluations")


def _database_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    if url:
        return url
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "3306")
    user = os.getenv("DB_USER", "root")
    password = os.getenv("DB_PASSWORD", "")
    name = os.getenv("DB_NAME", "talent_radar")
    return f"mysql+pymysql://{user}:{password}@{host}:{port}/{name}"


def get_engine():
    return create_engine(_database_url(), pool_pre_ping=True)


def get_session():
    engine = get_engine()
    Session = sessionmaker(bind=engine)
    return Session()


def init_db() -> None:
    engine = get_engine()
    Base.metadata.create_all(engine)


def _json_list(value: list[Any]) -> str:
    return json.dumps(value, ensure_ascii=False)


def save_candidate(session, resume: CandidateResume, classification: ImportClassification | None = None) -> CandidateORM:
    existing = session.query(CandidateORM).filter_by(id=resume.id).first()
    if existing:
        candidate = existing
    else:
        candidate = CandidateORM(id=resume.id)
        session.add(candidate)

    candidate.name = resume.name or candidate.name
    candidate.target_role = resume.target_role or candidate.target_role
    candidate.stage = resume.stage or candidate.stage
    candidate.raw_text = resume.raw_text or candidate.raw_text
    candidate.education = _json_list(resume.education)
    candidate.directions = _json_list(resume.directions)
    candidate.projects = _json_list([project.model_dump() for project in resume.projects])
    candidate.publications = _json_list(resume.publications)
    candidate.skills = _json_list(resume.skills)
    candidate.screening_tags = _json_list(resume.screening_tags)

    if classification:
        candidate.import_category = classification.category
        candidate.import_confidence = classification.confidence

    session.commit()
    return candidate


def save_evaluation(session, evaluation: CandidateEvaluation) -> EvaluationORM:
    existing = (
        session.query(EvaluationORM)
        .filter_by(candidate_id=evaluation.id)
        .order_by(EvaluationORM.created_at.desc())
        .first()
    )
    if existing:
        ev = existing
    else:
        ev = EvaluationORM(candidate_id=evaluation.id)
        session.add(ev)

    ev.overall_score = evaluation.overall_score
    ev.level = evaluation.level
    ev.tier = evaluation.tier
    ev.one_liner = evaluation.one_liner
    ev.core_strengths = evaluation.core_strengths
    ev.potential_risks = evaluation.potential_risks
    ev.interview_questions = evaluation.interview_questions
    ev.cultivation_direction = evaluation.cultivation_direction
    ev.dimension_scores = [score.model_dump() for score in evaluation.dimension_scores]
    ev.evidence = [item.model_dump() for item in evaluation.evidence]
    ev.critic_flags = evaluation.critic_flags

    session.commit()
    return ev


def list_candidates(session):
    return session.query(CandidateORM).order_by(CandidateORM.created_at.desc()).all()


def get_candidate_with_latest_evaluation(session, candidate_id: str):
    candidate = session.query(CandidateORM).filter_by(id=candidate_id).first()
    if not candidate:
        return None, None
    latest_evaluation = (
        session.query(EvaluationORM)
        .filter_by(candidate_id=candidate_id)
        .order_by(EvaluationORM.created_at.desc())
        .first()
    )
    return candidate, latest_evaluation
