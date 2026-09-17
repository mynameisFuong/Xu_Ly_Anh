from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.app.database import Base
from backend.app.models import (
    AttendanceRecord,
    Class,
    ClassEnrollment,
    ConsentStatus,
    Student,
    User,
    UserRole,
)
from backend.app.schemas import AttendanceManualUpdate, RecognitionEventCreate
from backend.app.security import hash_password
from backend.app.services.attendance import (
    close_session,
    create_recognition_event,
    open_session,
    update_attendance_manually,
)


def build_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return session_factory()


def seed(db):
    teacher = User(
        username="teacher",
        password_hash=hash_password("secret"),
        role=UserRole.TEACHER.value,
        full_name="Teacher",
    )
    student = Student(
        student_code="SV001",
        full_name="Student 1",
        consent_status=ConsentStatus.GRANTED.value,
    )
    class_ = Class(code="C001", name="Class 1", teacher=teacher)
    db.add_all([teacher, student, class_])
    db.flush()
    db.add(ClassEnrollment(class_id=class_.id, student_id=student.id))
    db.commit()
    return teacher, student, class_


def test_recognition_event_creates_only_one_attendance_record_for_duplicate_requests():
    db = build_db()
    teacher, student, class_ = seed(db)
    session = open_session(db, class_id=class_.id, opened_by=teacher.id)

    payload = RecognitionEventCreate(
        camera_id="camera-0",
        student_id=student.id,
        candidate_score=0.88,
        second_score=0.2,
        decision="recognized",
        model_version="test-model",
        idempotency_key="same-key",
    )

    _event_1, attendance_1 = create_recognition_event(db, session_id=session.id, payload=payload)
    _event_2, attendance_2 = create_recognition_event(db, session_id=session.id, payload=payload)

    records = db.scalars(select(AttendanceRecord)).all()
    assert len(records) == 1
    assert attendance_1.id == attendance_2.id
    assert records[0].student_id == student.id


def test_manual_update_overwrites_status_and_writes_single_record():
    db = build_db()
    teacher, student, class_ = seed(db)
    session = open_session(db, class_id=class_.id, opened_by=teacher.id)

    first = update_attendance_manually(
        db,
        session_id=session.id,
        student_id=student.id,
        actor_user_id=teacher.id,
        payload=AttendanceManualUpdate(status="present", reason="Arrived with card"),
    )
    second = update_attendance_manually(
        db,
        session_id=session.id,
        student_id=student.id,
        actor_user_id=teacher.id,
        payload=AttendanceManualUpdate(status="late", reason="Correct late status"),
    )

    records = db.scalars(select(AttendanceRecord)).all()
    assert len(records) == 1
    assert first.id == second.id
    assert second.status == "late"
    assert second.source == "manual"


def test_close_session_marks_missing_enrolled_students_absent():
    db = build_db()
    teacher, _student, class_ = seed(db)
    missing = Student(student_code="SV002", full_name="Student 2", consent_status=ConsentStatus.GRANTED.value)
    db.add(missing)
    db.flush()
    db.add(ClassEnrollment(class_id=class_.id, student_id=missing.id))
    db.commit()

    session = open_session(db, class_id=class_.id, opened_by=teacher.id)
    closed = close_session(db, session_id=session.id, actor_user_id=teacher.id)

    records = db.scalars(select(AttendanceRecord).where(AttendanceRecord.session_id == session.id)).all()
    assert closed.status == "closed"
    assert len(records) == 2
    assert {record.status for record in records} == {"absent"}
