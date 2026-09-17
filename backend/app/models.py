from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class UserRole(str, Enum):
    ADMIN = "admin"
    TEACHER = "teacher"
    USER = "user"


class ConsentStatus(str, Enum):
    PENDING = "pending"
    GRANTED = "granted"
    REVOKED = "revoked"


class SessionStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"


class RecognitionDecision(str, Enum):
    RECOGNIZED = "recognized"
    UNKNOWN = "unknown"
    LOW_CONFIDENCE = "low_confidence"


class AttendanceStatus(str, Enum):
    PRESENT = "present"
    LATE = "late"
    ABSENT = "absent"
    EXCUSED = "excused"
    MANUAL_REVIEW = "manual_review"


class AttendanceSource(str, Enum):
    AUTO = "auto"
    MANUAL = "manual"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default=UserRole.TEACHER.value)
    full_name: Mapped[str] = mapped_column(String(160))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    classes: Mapped[list["Class"]] = relationship(back_populates="teacher")


class Student(Base):
    __tablename__ = "students"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(160))
    class_label: Mapped[str | None] = mapped_column(String(80), nullable=True)
    consent_status: Mapped[str] = mapped_column(String(20), default=ConsentStatus.PENDING.value)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    enrollments: Mapped[list["ClassEnrollment"]] = relationship(back_populates="student")
    face_templates: Mapped[list["FaceTemplate"]] = relationship(back_populates="student")


class Class(Base):
    __tablename__ = "classes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    teacher_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    teacher_display_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    term: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    teacher: Mapped[User] = relationship(back_populates="classes")
    enrollments: Mapped[list["ClassEnrollment"]] = relationship(back_populates="class_")
    sessions: Mapped[list["ClassSession"]] = relationship(back_populates="class_")


class ClassEnrollment(Base):
    __tablename__ = "class_enrollments"
    __table_args__ = (UniqueConstraint("class_id", "student_id", name="uq_class_student"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id"))
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    class_: Mapped[Class] = relationship(back_populates="enrollments")
    student: Mapped[Student] = relationship(back_populates="enrollments")


class ClassSession(Base):
    __tablename__ = "class_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id"), index=True)
    opened_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    expected_start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    planned_end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    late_grace_minutes: Mapped[int] = mapped_column(Integer, default=0)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=SessionStatus.OPEN.value)

    class_: Mapped[Class] = relationship(back_populates="sessions")
    recognition_events: Mapped[list["RecognitionEvent"]] = relationship(back_populates="session")
    attendance_records: Mapped[list["AttendanceRecord"]] = relationship(back_populates="session")


class FaceTemplate(Base):
    __tablename__ = "face_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), index=True)
    embedding: Mapped[bytes] = mapped_column(LargeBinary)
    model_name: Mapped[str] = mapped_column(String(80))
    model_version: Mapped[str] = mapped_column(String(80))
    embedding_dim: Mapped[int] = mapped_column(Integer)
    image_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    student: Mapped[Student] = relationship(back_populates="face_templates")


class RecognitionEvent(Base):
    __tablename__ = "recognition_events"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_recognition_idempotency"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("class_sessions.id"), index=True)
    camera_id: Mapped[str] = mapped_column(String(80))
    student_id: Mapped[int | None] = mapped_column(ForeignKey("students.id"), nullable=True)
    candidate_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    second_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    decision: Mapped[str] = mapped_column(String(30))
    frame_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    model_version: Mapped[str] = mapped_column(String(80))
    idempotency_key: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    session: Mapped[ClassSession] = relationship(back_populates="recognition_events")
    student: Mapped[Student | None] = relationship()


class AttendanceRecord(Base):
    __tablename__ = "attendance_records"
    __table_args__ = (UniqueConstraint("session_id", "student_id", name="uq_attendance_session_student"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("class_sessions.id"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), index=True)
    status: Mapped[str] = mapped_column(String(30))
    source: Mapped[str] = mapped_column(String(20))
    recognized_event_id: Mapped[int | None] = mapped_column(ForeignKey("recognition_events.id"), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    late_minutes: Mapped[int] = mapped_column(Integer, default=0)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    session: Mapped[ClassSession] = relationship(back_populates="attendance_records")
    student: Mapped[Student] = relationship()
    recognized_event: Mapped[RecognitionEvent | None] = relationship()


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(80))
    entity_type: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[str] = mapped_column(String(80))
    before_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    after_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
