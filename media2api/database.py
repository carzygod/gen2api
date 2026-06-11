from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings


connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    settings.ensure_dirs()
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    ensure_schema_columns()


def ensure_schema_columns() -> None:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    attempt_missing_text = []
    attempt_missing_timestamp = []
    if "media_job_attempts" in tables:
        columns = {column["name"] for column in inspector.get_columns("media_job_attempts")}
        if "request_snapshot_json" not in columns:
            attempt_missing_text.append("request_snapshot_json")
        if "raw_response_json" not in columns:
            attempt_missing_text.append("raw_response_json")
        if "started_at" not in columns:
            attempt_missing_timestamp.append("started_at")
        if "finished_at" not in columns:
            attempt_missing_timestamp.append("finished_at")

    account_missing_text = []
    account_missing_timestamp = []
    if "account_resources" in tables:
        columns = {column["name"] for column in inspector.get_columns("account_resources")}
        if "last_error_code" not in columns:
            account_missing_text.append(("last_error_code", "VARCHAR(64) NOT NULL DEFAULT ''"))
        if "last_error_message" not in columns:
            account_missing_text.append(("last_error_message", "TEXT NOT NULL DEFAULT ''"))
        if "resource_type" not in columns:
            account_missing_text.append(("resource_type", "VARCHAR(64) NOT NULL DEFAULT ''"))
        if "resource_profile_json" not in columns:
            account_missing_text.append(("resource_profile_json", "TEXT NOT NULL DEFAULT '{}'"))
        if "last_failed_at" not in columns:
            account_missing_timestamp.append("last_failed_at")

    request_audit_missing_text = []
    if "request_audit_logs" in tables:
        columns = {column["name"] for column in inspector.get_columns("request_audit_logs")}
        for column, definition in [
            ("attempt_id", "VARCHAR(64) NOT NULL DEFAULT ''"),
            ("provider_id", "VARCHAR(64) NOT NULL DEFAULT ''"),
            ("account_id", "VARCHAR(64) NOT NULL DEFAULT ''"),
            ("logical_model", "VARCHAR(64) NOT NULL DEFAULT ''"),
            ("provider_model", "VARCHAR(120) NOT NULL DEFAULT ''"),
            ("provider_task_id", "VARCHAR(120) NOT NULL DEFAULT ''"),
            ("standard_error_code", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ]:
            if column not in columns:
                request_audit_missing_text.append((column, definition))

    if attempt_missing_text or attempt_missing_timestamp or account_missing_text or account_missing_timestamp or request_audit_missing_text:
        with engine.begin() as conn:
            for column in attempt_missing_text:
                conn.execute(text(f"ALTER TABLE media_job_attempts ADD COLUMN {column} TEXT NOT NULL DEFAULT '{{}}'"))
            for column in attempt_missing_timestamp:
                conn.execute(text(f"ALTER TABLE media_job_attempts ADD COLUMN {column} TIMESTAMP"))
            for column, definition in account_missing_text:
                conn.execute(text(f"ALTER TABLE account_resources ADD COLUMN {column} {definition}"))
            for column in account_missing_timestamp:
                conn.execute(text(f"ALTER TABLE account_resources ADD COLUMN {column} TIMESTAMP"))
            for column, definition in request_audit_missing_text:
                conn.execute(text(f"ALTER TABLE request_audit_logs ADD COLUMN {column} {definition}"))
    normalize_account_subscription_source_auth_methods(tables)


def normalize_account_subscription_source_auth_methods(tables: set[str]) -> None:
    if "account_subscription_sources" not in tables:
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE account_subscription_sources
                SET auth_method = CASE
                    WHEN provider_id IN (
                        'openai_image',
                        'openai_web_session',
                        'gemini_web_session',
                        'grok',
                        'qwen_ai_web_session',
                        'qianwen_web_session',
                        'jimeng_web_session',
                        'doubao_web_session',
                        'kling_web_session',
                        'luma_web_session',
                        'midjourney',
                        'midjourney_discord_session'
                    ) THEN 'cookie_secret'
                    ELSE 'agent_provider_credential'
                END
                WHERE auth_method IS NULL
                   OR auth_method = ''
                   OR auth_method NOT IN ('cookie_secret', 'agent_provider_credential')
                """
            )
        )


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope():
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
