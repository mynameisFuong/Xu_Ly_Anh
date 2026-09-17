from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy import inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.app.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_all() -> None:
    from backend.app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _apply_sqlite_light_migrations()


def _apply_sqlite_light_migrations() -> None:
    if engine.url.get_backend_name() != "sqlite":
        return

    inspector = inspect(engine)
    if not inspector.has_table("class_sessions"):
        return

    session_columns = {column["name"] for column in inspector.get_columns("class_sessions")}
    attendance_columns = {column["name"] for column in inspector.get_columns("attendance_records")}
    statements: list[str] = []
    if "expected_start_time" not in session_columns:
        statements.append("ALTER TABLE class_sessions ADD COLUMN expected_start_time DATETIME")
    if "late_grace_minutes" not in session_columns:
        statements.append("ALTER TABLE class_sessions ADD COLUMN late_grace_minutes INTEGER NOT NULL DEFAULT 0")
    if "late_minutes" not in attendance_columns:
        statements.append("ALTER TABLE attendance_records ADD COLUMN late_minutes INTEGER NOT NULL DEFAULT 0")

    if not statements:
        return

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
