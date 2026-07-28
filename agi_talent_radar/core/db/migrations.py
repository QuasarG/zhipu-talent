from __future__ import annotations

import json
from typing import Any

from sqlalchemy import inspect, select, text
from sqlalchemy.orm import sessionmaker

from agi_talent_radar.core.db.orm import Base, EvaluationORM, SchemaVersionORM
from agi_talent_radar.core.db.repository import _replace_evaluation_details


LATEST_SCHEMA_VERSION = 6
LEGACY_EVALUATION_COLUMNS = {
    "dimension_scores",
    "evidence",
    "track_assignments",
    "track_evaluations",
}


def ensure_schema(engine) -> None:
    _ensure_legacy_parent_columns(engine)
    Base.metadata.create_all(engine)
    current_version = _current_version(engine)
    if current_version < 2 or _has_legacy_evaluation_columns(engine):
        _migrate_evaluation_details(engine)
        _record_version(engine, 2, "normalize multi-track evaluation details")
    if current_version < 3:
        _record_version(engine, 3, "add structured internship and work experiences")
    if current_version < 4:
        _record_version(engine, 4, "add person master record and platform foundation tables")
    if current_version < 5:
        _record_version(engine, 5, "store stage-aware direction recommendations")
    if current_version < 6:
        _record_version(engine, 6, "store academic verification report with evaluations")
    _ensure_indexes(engine)


def _ensure_legacy_parent_columns(engine) -> None:
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    if "candidates" in table_names:
        candidate_columns = {column["name"] for column in inspector.get_columns("candidates")}
        additions = []
        if "source_format" not in candidate_columns:
            additions.append("source_format VARCHAR(32)")
        if "document_analysis" not in candidate_columns:
            additions.append("document_analysis TEXT")
        if "experiences" not in candidate_columns:
            additions.append("experiences TEXT")
        _add_columns(engine, "candidates", additions)

    if "evaluations" in table_names:
        evaluation_columns = {column["name"] for column in inspector.get_columns("evaluations")}
        additions = []
        for name, column_type in (
            ("decision_method", "TEXT"),
            ("normalized_education", "JSON"),
            ("screening_tags", "JSON"),
            ("common_score", "FLOAT"),
            ("document_score", "FLOAT"),
            ("routing_confidence", "FLOAT"),
            ("status", "VARCHAR(24) NOT NULL DEFAULT 'completed'"),
            ("error_message", "TEXT"),
            ("completed_at", "DATETIME"),
            ("person_id", "VARCHAR(36)"),
            ("config_version", "VARCHAR(64)"),
            ("recommended_tracks", "JSON"),
            ("stage_profile", "VARCHAR(64)"),
            ("academic_report", "JSON"),
        ):
            if name not in evaluation_columns:
                additions.append(f"{name} {column_type}")
        _add_columns(engine, "evaluations", additions)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE evaluations SET status = 'completed' "
                    "WHERE status IS NULL OR status = ''"
                )
            )
            connection.execute(
                text(
                    "UPDATE evaluations SET completed_at = created_at "
                    "WHERE status = 'completed' AND completed_at IS NULL"
                )
            )


def _migrate_evaluation_details(engine) -> None:
    inspector = inspect(engine)
    if "evaluations" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("evaluations")}
    legacy_columns = LEGACY_EVALUATION_COLUMNS & columns
    if not legacy_columns:
        return

    select_columns = ["id"] + sorted(legacy_columns)
    with engine.connect() as connection:
        rows = connection.execute(text(f"SELECT {', '.join(select_columns)} FROM evaluations")).mappings().all()

    if rows:
        Session = sessionmaker(bind=engine)
        with Session() as session:
            for raw in rows:
                evaluation = session.get(EvaluationORM, raw["id"])
                if evaluation is None:
                    continue
                payload = {
                    "dimension_scores": _json_list(raw.get("dimension_scores")),
                    "evidence": _json_list(raw.get("evidence")),
                    "track_assignments": _json_list(raw.get("track_assignments")),
                    "track_evaluations": _json_list(raw.get("track_evaluations")),
                }
                _replace_evaluation_details(session, evaluation, payload)
            session.commit()

    with engine.begin() as connection:
        for column_name in sorted(legacy_columns):
            connection.execute(text(f"ALTER TABLE evaluations DROP COLUMN {column_name}"))


def _current_version(engine) -> int:
    inspector = inspect(engine)
    if "schema_versions" not in inspector.get_table_names():
        return 0
    with engine.connect() as connection:
        version = connection.scalar(select(SchemaVersionORM.version).order_by(SchemaVersionORM.version.desc()).limit(1))
    return int(version or 0)


def _has_legacy_evaluation_columns(engine) -> bool:
    inspector = inspect(engine)
    if "evaluations" not in inspector.get_table_names():
        return False
    columns = {column["name"] for column in inspector.get_columns("evaluations")}
    return bool(LEGACY_EVALUATION_COLUMNS & columns)


def _record_version(engine, version: int, description: str) -> None:
    Session = sessionmaker(bind=engine)
    with Session() as session:
        existing = session.get(SchemaVersionORM, version)
        if existing is None:
            session.add(SchemaVersionORM(version=version, description=description))
            session.commit()


def _add_columns(engine, table_name: str, definitions: list[str]) -> None:
    if not definitions:
        return
    with engine.begin() as connection:
        for definition in definitions:
            connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {definition}"))


def _ensure_indexes(engine) -> None:
    table_names = set(inspect(engine).get_table_names())
    for table in Base.metadata.sorted_tables:
        if table.name not in table_names:
            continue
        for index in table.indexes:
            index.create(bind=engine, checkfirst=True)


def _json_list(value: Any) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []
