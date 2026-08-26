from __future__ import annotations

import json
from typing import Any

from sqlalchemy import inspect, select, text
from sqlalchemy.orm import sessionmaker

from agi_talent_radar.core.db.orm import (
    Base,
    EvaluationORM,
    InterviewAssessmentPairLockORM,
    InterviewAssessmentRunORM,
    SchemaVersionORM,
)
from agi_talent_radar.core.db.repository import _replace_evaluation_details


LATEST_SCHEMA_VERSION = 23
LEGACY_EVALUATION_COLUMNS = {
    "dimension_scores",
    "evidence",
    "track_assignments",
    "track_evaluations",
}

# 阶段 1：candidates / evaluations 需要 ALTER TABLE ADD 的新列。
# 这里是 (列名, 列类型, 默认值表达式或 NULL/默认值) 三元组。
CANDIDATES_NEW_COLUMNS = (
    ("person_id", "VARCHAR(36)", None),
    ("engagement_status", "VARCHAR(32)", "'newly_admitted'"),
    ("current_resume_version_id", "VARCHAR(36)", None),
    ("admitted_at", "DATETIME", None),
)
EVALUATIONS_NEW_COLUMNS = (
    ("resume_submission_id", "VARCHAR(36)", None),
    # EvaluationORM.candidate_id 本已存在；不重复添加。
)

# 阶段 2：persons 表新增稳定标识 / 冲突标记列。
PERSONS_NEW_COLUMNS = (
    ("identifiers", "JSON", None),
    ("identity_conflict", "BOOLEAN", "0"),
)

# 阶段 6：external_facts 表新增版本化字段。
EXTERNAL_FACTS_NEW_COLUMNS = (
    ("identity_key", "VARCHAR(128)", "''"),
    ("dedupe_key", "VARCHAR(64)", "''"),
    ("verification_status", "VARCHAR(16)", "'pending'"),
    ("valid_from", "DATETIME", None),
    ("supersedes_id", "INTEGER", None),
    ("superseded_at", "DATETIME", None),
    ("query_context", "JSON", None),
    ("raw_payload_hash", "VARCHAR(64)", "''"),
)


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
    if current_version < 7:
        _migrate_phase_one_columns(engine)
        _record_version(
            engine,
            7,
            "phase 1: split Person/ResumeSubmission/Candidate; add resume_submissions / "
            "candidate_sources / engagement_status_history / identity_suggestions / merge_audit",
        )
    if current_version < 8:
        _migrate_phase_two_columns(engine)
        _record_version(
            engine,
            8,
            "phase 2: add stable identifiers and identity_conflict to persons for "
            "deterministic intake identity resolution",
        )
    if current_version < 9:
        # 阶段 3 新表（publication_claims / publication_verifications）
        # 由 Base.metadata.create_all 自动创建，无需 ALTER。
        _record_version(
            engine,
            9,
            "phase 3: split publication claims (self-stated) from verifications "
            "(external facts); both can be retried independently",
        )
    if current_version < 10:
        _migrate_phase_six_columns(engine)
        _record_version(
            engine,
            10,
            "phase 6: versioned external facts (identity_key / dedupe_key / "
            "verification_status / supersedes chain)",
        )
    if current_version < 11:
        _migrate_academic_report_column(engine)
        _record_version(
            engine,
            11,
            "add candidates.academic_report JSON + academic_check_status + "
            "academic_check_at for decoupled async paper verification",
        )
    if current_version < 12:
        _migrate_person_schools(engine)
        _record_version(
            engine,
            12,
            "phase 12: structured person education (persons.schools JSON), "
            "org = highest degree school, backfilled from candidates.education",
        )
    if current_version < 13:
        _migrate_supplementary_info_column(engine)
        _record_version(
            engine,
            13,
            "phase 13: candidates.supplementary_info for HR-provided extra info injected into evaluation",
        )
    if current_version < 14:
        _migrate_users_and_conversation_owner(engine)
        _record_version(
            engine,
            14,
            "phase 14: add users table + conversations.owner_id; seed 8 accounts; "
            "clear legacy conversations (chat isolation)",
        )
    if current_version < 15:
        _migrate_talent_groups(engine)
        _record_version(
            engine,
            15,
            "phase 15: add talent_groups table + persons.group_id (manual grouping)",
        )
    if current_version < 16:
        # 奖学金初筛四张新表由 Base.metadata.create_all 自动创建，无需 ALTER。
        _record_version(
            engine,
            16,
            "phase 16: Z.AI Scholarship screening tables (applications / materials / "
            "evaluations / reputation_items)",
        )
    if current_version < 17:
        # evaluations 加 publication_score / safety_net_score 两列
        # create_all 可能已建列,先检查再 ALTER
        existing = {c["name"] for c in inspect(engine).get_columns("evaluations")}
        new_cols = []
        if "publication_score" not in existing:
            new_cols.append("publication_score FLOAT DEFAULT 0.0")
        if "safety_net_score" not in existing:
            new_cols.append("safety_net_score FLOAT DEFAULT 0.0")
        if new_cols:
            _add_columns(engine, "evaluations", new_cols)
        _record_version(
            engine,
            17,
            "phase 17: evaluation publication_score + safety_net_score (bonus columns)",
        )
    if current_version < 18:
        # grill 画像澄清模块：grill_sessions 新表由 create_all 自动创建，无需 ALTER。
        _record_version(
            engine,
            18,
            "phase 18: grill 画像澄清模块 (grill_sessions 表)",
        )
    if current_version < 19:
        # 只读分享令牌：share_tokens 新表由 create_all 自动创建，无需 ALTER。
        _record_version(
            engine,
            19,
            "phase 19: talent profile read-only share tokens (share_tokens 表)",
        )
    if current_version < 20:
        existing = {c["name"] for c in inspect(engine).get_columns("evaluations")}
        definitions = (
            ("interview_decision", "VARCHAR(16) DEFAULT ''"),
            ("best_fit_jd_id", "VARCHAR(36) DEFAULT ''"),
            ("best_fit_jd_title", "VARCHAR(200) DEFAULT ''"),
            ("decision_summary", "TEXT"),
            ("job_fit_assessments", "JSON"),
        )
        _add_columns(
            engine,
            "evaluations",
            [definition for name, definition in definitions if name not in existing],
        )
        _record_version(
            engine,
            20,
            "phase 20: per-JD interview admission assessments and best-fit decision",
        )
    if current_version < 21:
        _migrate_interview_assessment_foundation(engine)
        _record_version(
            engine,
            21,
            "phase 21: JD assessment cards and independent candidate-JD admission workflow",
        )
    if current_version < 22:
        _migrate_interview_assessment_controls(engine)
        _record_version(
            engine,
            22,
            "phase 22: persistent JD card trace",
        )
    if current_version < 23:
        _backfill_interview_assessment_pair_locks(engine)
        _record_version(
            engine,
            23,
            "phase 23: cross-user candidate-JD assessment run locks",
        )
    _ensure_indexes(engine)


def _migrate_interview_assessment_foundation(engine) -> None:
    """为已有 JD 表补岗位卡字段；三张准入新表由 create_all 建立。"""
    existing = {column["name"] for column in inspect(engine).get_columns("jd_entries")}
    definitions = (
        ("supplements", "JSON"),
        ("assessment_card", "JSON"),
        ("card_status", "VARCHAR(16) NOT NULL DEFAULT 'generating'"),
        ("card_error", "TEXT"),
        ("archived", "BOOLEAN NOT NULL DEFAULT 0"),
    )
    _add_columns(
        engine,
        "jd_entries",
        [f"{name} {definition}" for name, definition in definitions if name not in existing],
    )


def _migrate_interview_assessment_controls(engine) -> None:
    jd_columns = {column["name"] for column in inspect(engine).get_columns("jd_entries")}
    _add_columns(
        engine,
        "jd_entries",
        [
            f"{name} {definition}"
            for name, definition in (
                ("card_run_trace", "JSON"),
                ("card_model_usage", "JSON"),
            )
            if name not in jd_columns
        ],
    )


def _backfill_interview_assessment_pair_locks(engine) -> None:
    """为升级时仍在运行的配对补锁；重复的历史脏运行保留最早一条。"""
    Session = sessionmaker(bind=engine)
    with Session() as session:
        runs = (
            session.query(InterviewAssessmentRunORM)
            .filter(InterviewAssessmentRunORM.status.in_(("queued", "running")))
            .order_by(InterviewAssessmentRunORM.created_at, InterviewAssessmentRunORM.id)
            .all()
        )
        for run in runs:
            key = (run.candidate_id, run.jd_id)
            if session.get(InterviewAssessmentPairLockORM, key) is None:
                session.add(
                    InterviewAssessmentPairLockORM(
                        candidate_id=run.candidate_id,
                        jd_id=run.jd_id,
                        run_id=run.id,
                    )
                )
        session.commit()


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
            ("publication_score", "FLOAT DEFAULT 0.0"),
            ("safety_net_score", "FLOAT DEFAULT 0.0"),
            ("interview_decision", "VARCHAR(16) DEFAULT ''"),
            ("best_fit_jd_id", "VARCHAR(36) DEFAULT ''"),
            ("best_fit_jd_title", "VARCHAR(200) DEFAULT ''"),
            ("decision_summary", "TEXT"),
            ("job_fit_assessments", "JSON"),
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
        existing_columns = {column["name"] for column in inspect(engine).get_columns(table.name)}
        for index in table.indexes:
            # 跳过依赖尚未迁移的新列的索引，等迁移后再创建。
            if not _index_columns_exist(index, existing_columns):
                continue
            index.create(bind=engine, checkfirst=True)


def _index_columns_exist(index, existing_columns: set[str]) -> bool:
    for column in index.columns:
        if column.name not in existing_columns:
            return False
    return True


def _migrate_phase_one_columns(engine) -> None:
    """阶段 1 老库升级：candidates / evaluations ALTER TABLE ADD COLUMN。

    新库靠 Base.metadata.create_all 自动带列，本函数只对老库生效。
    """
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "candidates" in tables:
        candidates_columns = {column["name"] for column in inspector.get_columns("candidates")}
        additions = []
        for name, column_type, default in CANDIDATES_NEW_COLUMNS:
            if name in candidates_columns:
                continue
            default_clause = f" DEFAULT {default}" if default is not None else ""
            additions.append(f"{name} {column_type}{default_clause}")
        _add_columns(engine, "candidates", additions)
    if "evaluations" in tables:
        evaluations_columns = {column["name"] for column in inspector.get_columns("evaluations")}
        additions = []
        for name, column_type, default in EVALUATIONS_NEW_COLUMNS:
            if name in evaluations_columns:
                continue
            default_clause = f" DEFAULT {default}" if default is not None else ""
            additions.append(f"{name} {column_type}{default_clause}")
        _add_columns(engine, "evaluations", additions)


def _migrate_phase_two_columns(engine) -> None:
    """阶段 2 老库升级：persons 加 identifiers / identity_conflict 列。"""
    inspector = inspect(engine)
    if "persons" not in inspect(engine).get_table_names():
        return
    persons_columns = {column["name"] for column in inspector.get_columns("persons")}
    additions = []
    for name, column_type, default in PERSONS_NEW_COLUMNS:
        if name in persons_columns:
            continue
        default_clause = f" DEFAULT {default}" if default is not None else ""
        additions.append(f"{name} {column_type}{default_clause}")
    _add_columns(engine, "persons", additions)


def _migrate_phase_six_columns(engine) -> None:
    """阶段 6 老库升级：external_facts 加版本字段。"""
    inspector = inspect(engine)
    if "external_facts" not in inspect(engine).get_table_names():
        return
    facts_columns = {column["name"] for column in inspector.get_columns("external_facts")}
    additions = []
    for name, column_type, default in EXTERNAL_FACTS_NEW_COLUMNS:
        if name in facts_columns:
            continue
        default_clause = f" DEFAULT {default}" if default is not None else ""
        additions.append(f"{name} {column_type}{default_clause}")
    _add_columns(engine, "external_facts", additions)


def _migrate_supplementary_info_column(engine) -> None:
    """阶段 13：candidates 加 supplementary_info（HR 补充信息，评估时注入）。"""
    inspector = inspect(engine)
    if "candidates" not in inspector.get_table_names():
        return
    candidate_columns = {column["name"] for column in inspector.get_columns("candidates")}
    if "supplementary_info" not in candidate_columns:
        # MySQL 不允许 TEXT 列带 DEFAULT；NULL 由读取侧 getattr(...) or "" 兼容
        _add_columns(engine, "candidates", ["supplementary_info TEXT"])


def _migrate_person_schools(engine) -> None:
    """阶段 12：persons 加 schools JSON 列，并从候选人教育经历回填学校和最高学历 org。"""
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "persons" not in tables:
        return
    persons_columns = {column["name"] for column in inspector.get_columns("persons")}
    if "schools" not in persons_columns:
        _add_columns(engine, "persons", ["schools JSON"])
    if "candidates" not in tables:
        return
    candidates_columns = {column["name"] for column in inspector.get_columns("candidates")}
    if not {"id", "person_id", "education"} <= candidates_columns:
        return  # 老到连 education 都没有的库：跳过回填，只加列
    from agi_talent_radar.core.db.orm import PersonORM
    from agi_talent_radar.core.education import highest_school, parse_education_entries

    # 老库 candidates 列可能不全，用裸 SQL 只取需要的三列，避开 ORM 全列查询
    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT id, person_id, education FROM candidates WHERE person_id IS NOT NULL")
        ).mappings().all()
    if not rows:
        return
    Session = sessionmaker(bind=engine)
    with Session() as session:
        for raw in rows:
            person = session.get(PersonORM, raw["person_id"])
            if person is None or person.schools:
                continue
            entries = parse_education_entries(_json_list(raw["education"]))
            if not entries:
                continue
            person.schools = [entry.to_dict() for entry in entries]
            top = highest_school(entries)
            if top:
                person.org = top
        session.commit()


def _migrate_academic_report_column(engine) -> None:
    """导入阶段论文核验：candidates 加 academic_report JSON 列。"""
    inspector = inspect(engine)
    if "candidates" not in inspector.get_table_names():
        return
    candidate_columns = {column["name"] for column in inspector.get_columns("candidates")}
    if "academic_report" not in candidate_columns:
        _add_columns(engine, "candidates", ["academic_report JSON"])
    additions = []
    if "academic_check_status" not in candidate_columns:
        additions.append("academic_check_status VARCHAR(16) DEFAULT 'none'")
    if "academic_check_at" not in candidate_columns:
        additions.append("academic_check_at DATETIME")
    if additions:
        _add_columns(engine, "candidates", additions)


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


# 种子账号：username → display_name；密码统一 talent2026（迁移时注入）
_SEED_USERS = {
    "heyun": "何芸",
    "gaomin": "高敏",
    "huangmeiling": "黄美玲",
    "pushiyao": "蒲诗瑶",
    "zhangyimei": "张意梅",
    "pengguanqiao": "彭冠乔",
    "sunzhibo": "孙智博",
    "guozexin": "郭泽新",
    "panyufei": "潘俞非",
}
_SEED_PASSWORD = "talent2026"


def _migrate_talent_groups(engine) -> None:
    """阶段 15：talent_groups 表由 create_all 自动建；persons 加 group_id 列。"""
    inspector = inspect(engine)
    if "persons" not in inspector.get_table_names():
        return
    persons_columns = {c["name"] for c in inspector.get_columns("persons")}
    if "group_id" not in persons_columns:
        _add_columns(engine, "persons", ["group_id VARCHAR(36)"])


def _migrate_users_and_conversation_owner(engine) -> None:
    """阶段 14：建 users 表（create_all 自动）+ 清空老会话 + conversations 加 owner_id + 插种子用户。

    owner_id NOT NULL：清空老会话后加列，避免 NULL 归属歧义。
    种子用户幂等：已存在的 username 跳过。
    """
    from agi_talent_radar.core.db.orm import UserORM
    from werkzeug.security import generate_password_hash

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())

    # conversations 表存在时：清空老会话（级联删 messages），再加 owner_id 列
    if "conversations" in tables:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM conversations"))
        conv_cols = {c["name"] for c in inspector.get_columns("conversations")}
        if "owner_id" not in conv_cols:
            _add_columns(engine, "conversations", ["owner_id VARCHAR(36) NOT NULL DEFAULT ''"])
            # SQLite ALTER 加 NOT NULL 需要默认值；加完后清空默认（MySQL/SQLite 兼容写法）
            with engine.begin() as connection:
                connection.execute(text("UPDATE conversations SET owner_id = '' WHERE owner_id IS NULL"))

    # 种子用户：幂等插入
    Session = sessionmaker(bind=engine)
    with Session() as session:
        for username, display_name in _SEED_USERS.items():
            exists = session.query(UserORM.id).filter_by(username=username).first()
            if exists:
                continue
            session.add(
                UserORM(
                    username=username,
                    display_name=display_name,
                    password_hash=generate_password_hash(_SEED_PASSWORD),
                    is_active=True,
                )
            )
        session.commit()
