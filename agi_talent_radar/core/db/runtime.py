from __future__ import annotations

import os
import re
from threading import Lock

from dotenv import load_dotenv
from sqlalchemy import URL, create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import sessionmaker

from agi_talent_radar.core.db.migrations import ensure_schema


load_dotenv()

_ENGINES: dict[str, Engine] = {}
_ENGINE_LOCK = Lock()


def get_engine() -> Engine:
    url = _database_url()
    cache_key = url.render_as_string(hide_password=False) if isinstance(url, URL) else url
    with _ENGINE_LOCK:
        engine = _ENGINES.get(cache_key)
        if engine is None:
            engine = create_engine(url, pool_pre_ping=True)
            ensure_schema(engine)
            _ENGINES[cache_key] = engine
    return engine


def get_session():
    Session = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return Session()


def init_db() -> None:
    create_database()
    ensure_schema(get_engine())


def create_database() -> None:
    url = make_url(_database_url())
    if not url.drivername.startswith("mysql") or not url.database:
        return
    if not re.fullmatch(r"[A-Za-z0-9_]+", url.database):
        raise ValueError("DB_NAME 只能包含字母、数字和下划线。")
    root_engine = create_engine(url.set(database=None), isolation_level="AUTOCOMMIT")
    try:
        with root_engine.connect() as connection:
            connection.execute(
                text(
                    f"CREATE DATABASE IF NOT EXISTS `{url.database}` "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
            )
    finally:
        root_engine.dispose()


def reset_engine_cache() -> None:
    with _ENGINE_LOCK:
        for engine in _ENGINES.values():
            engine.dispose()
        _ENGINES.clear()


def _database_url() -> str | URL:
    configured = os.getenv("DATABASE_URL", "").strip()
    if configured:
        return configured
    return URL.create(
        "mysql+pymysql",
        username=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASSWORD", ""),
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "3306")),
        database=os.getenv("DB_NAME", "talent_radar"),
    )
