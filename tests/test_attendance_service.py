import base64

import numpy as np
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.app.database import Base
from backend.app.models import (
    AttendanceRecord,
    Class,
    ClassEnrollment,
    ConsentStatus,
    FaceTemplate,
    RecognitionEvent,
    Student,
    User,
    UserRole,
)
from backend.app.schemas import AttendanceManualUpdate, FrameScanRequest, RecognitionEventCreate, StudentUpdate
from backend.app.api import (
    _attendance_stats_from_board,
    _attendance_request_read,
    _build_attendance_board,
    dashboard_summary,
    delete_student,
    list_sessions,
    list_students_with_faces,
    scan_frame,
    update_student,
)
from backend.app.security import hash_password
from backend.app.services.attendance import (
    close_session,
    create_recognition_event,
    open_session,
    update_attendance_manually,
)
from ai_pipeline.recognition import EmbeddingResult


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


def test_scan_frame_returns_face_box_without_exposing_identity_for_unknown_face(monkeypatch):
    db = build_db()
    teacher, _student, class_ = seed(db)
    session = open_session(db, class_id=class_.id, opened_by=teacher.id)

    class FakeRecognizer:
        model_version = "test-model"

        def extract_single_embedding(self, _image_bytes):
            return EmbeddingResult(True, np.zeros(128, dtype=np.float32), face_box=(10, 20, 70, 80))

    monkeypatch.setattr("backend.app.api.build_default_recognizer", FakeRecognizer)
    payload = FrameScanRequest(image_base64=base64.b64encode(b"frame").decode())
    response = scan_frame(session.id, payload, teacher, db)
    assert response.decision == "unknown"
    assert response.face_box == (10, 20, 70, 80)
    assert response.full_name is None
    assert response.student_code is None


def test_face_scan_records_each_student_once_per_session(monkeypatch):
    db = build_db()
    teacher, student, class_ = seed(db)
    session = open_session(db, class_id=class_.id, opened_by=teacher.id)
    embedding = np.zeros(128, dtype=np.float32)
    for pose in ("front", "left", "right", "up", "down"):
        db.add(FaceTemplate(
            student_id=student.id,
            embedding=embedding.tobytes(),
            model_name="test",
            model_version="test-model",
            embedding_dim=128,
            pose_label=pose,
            is_active=True,
        ))
    db.commit()

    class FakeRecognizer:
        model_version = "test-model"
        distance_metric = "euclidean"

        def extract_single_embedding(self, _image_bytes):
            return EmbeddingResult(True, embedding, face_box=(10, 20, 70, 80))

    monkeypatch.setattr("backend.app.api.build_default_recognizer", FakeRecognizer)
    monkeypatch.setattr("backend.app.api._save_attendance_evidence", lambda *_args, **_kwargs: None)
    image = base64.b64encode(b"frame").decode()
    first = scan_frame(session.id, FrameScanRequest(image_base64=image, idempotency_key="first"), teacher, db)
    second = scan_frame(session.id, FrameScanRequest(image_base64=image, idempotency_key="second"), teacher, db)

    assert first.decision == second.decision == "recognized"
    assert first.already_recorded is False
    assert second.already_recorded is True
    assert second.student_code == student.student_code
    assert first.attendance.id == second.attendance.id
    assert len(db.scalars(select(AttendanceRecord)).all()) == 1
    assert len(db.scalars(select(RecognitionEvent)).all()) == 1


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


def test_attendance_stats_are_calculated_from_class_roster():
    db = build_db()
    teacher, student, class_ = seed(db)
    late_student = Student(student_code="SV002", full_name="Student 2", consent_status=ConsentStatus.GRANTED.value)
    absent_student = Student(student_code="SV003", full_name="Student 3", consent_status=ConsentStatus.GRANTED.value)
    db.add_all([late_student, absent_student])
    db.flush()
    db.add_all(
        [
            ClassEnrollment(class_id=class_.id, student_id=late_student.id),
            ClassEnrollment(class_id=class_.id, student_id=absent_student.id),
        ]
    )
    db.commit()

    session = open_session(db, class_id=class_.id, opened_by=teacher.id)
    update_attendance_manually(
        db,
        session_id=session.id,
        student_id=student.id,
        actor_user_id=teacher.id,
        payload=AttendanceManualUpdate(status="present", reason="Arrived"),
    )
    update_attendance_manually(
        db,
        session_id=session.id,
        student_id=late_student.id,
        actor_user_id=teacher.id,
        payload=AttendanceManualUpdate(status="late", reason="Arrived late"),
    )
    close_session(db, session_id=session.id, actor_user_id=teacher.id)

    board = _build_attendance_board(db, session)
    stats = _attendance_stats_from_board(board)

    assert stats.total_students == 3
    assert stats.present_count == 1
    assert stats.late_count == 1
    assert stats.absent_count == 1
    assert stats.present_rate == 33.33
    assert stats.late_rate == 33.33
    assert stats.absent_rate == 33.33


def test_admin_can_update_and_soft_delete_student():
    db = build_db()
    teacher, student, _class = seed(db)
    template = FaceTemplate(
        student_id=student.id,
        embedding=b"1234",
        model_name="test",
        model_version="test",
        embedding_dim=1,
        is_active=True,
    )
    db.add(template)
    db.commit()

    updated = update_student(
        student.id,
        StudentUpdate(student_code="SV001A", full_name="Updated Student", class_label="KTPM", consent_status="granted"),
        teacher,
        db,
    )
    assert updated.student_code == "SV001A"
    assert updated.full_name == "Updated Student"
    assert updated.class_label == "KTPM"

    delete_student(student.id, teacher, db)
    db.refresh(student)
    db.refresh(template)

    assert student.deleted_at is not None
    assert template.is_active is False


def test_dashboard_and_session_history_reflect_operational_data():
    db = build_db()
    teacher, student, class_ = seed(db)
    session = open_session(db, class_id=class_.id, opened_by=teacher.id)
    update_attendance_manually(
        db,
        session_id=session.id,
        student_id=student.id,
        actor_user_id=teacher.id,
        payload=AttendanceManualUpdate(status="present", reason="Demo check-in"),
    )

    summary = dashboard_summary(teacher, db)
    history = list_sessions(20, teacher, db)

    assert summary.total_students == 1
    assert summary.active_classes == 1
    assert summary.open_sessions == 1
    assert len(history) == 1
    assert history[0].class_code == "C001"
    assert history[0].attendance_rate == 100.0
    assert _attendance_request_read(db, session).student_count == 1


def test_faceid_status_requires_all_five_distinct_poses():
    db = build_db()
    teacher, student, _class = seed(db)
    for pose in ("front", "left", "right", "up"):
        db.add(FaceTemplate(
            student_id=student.id,
            embedding=b"test",
            model_name="test",
            model_version="test",
            embedding_dim=1,
            pose_label=pose,
            is_active=True,
        ))
    db.commit()
    assert dashboard_summary(teacher, db).enrolled_students == 0
    assert list_students_with_faces(teacher, db)[0].enrollment_complete is False

    db.add(FaceTemplate(
        student_id=student.id,
        embedding=b"test",
        model_name="test",
        model_version="test",
        embedding_dim=1,
        pose_label="down",
        is_active=True,
    ))
    db.commit()
    assert dashboard_summary(teacher, db).enrolled_students == 1
    assert list_students_with_faces(teacher, db)[0].enrollment_complete is True
