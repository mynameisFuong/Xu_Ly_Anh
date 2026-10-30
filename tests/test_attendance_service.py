import base64

import numpy as np
import pytest
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


def test_idempotency_key_cannot_be_reused_for_a_different_student():
    from fastapi import HTTPException

    db = build_db()
    teacher, student, class_ = seed(db)
    session = open_session(db, class_id=class_.id, opened_by=teacher.id)
    payload = RecognitionEventCreate(student_id=student.id, candidate_score=0.9, decision="recognized",
                                     model_version="test", idempotency_key="bound-request")
    create_recognition_event(db, session_id=session.id, payload=payload)
    with pytest.raises(HTTPException) as error:
        create_recognition_event(db, session_id=session.id,
                                 payload=payload.model_copy(update={"student_id": student.id + 1}))
    assert error.value.status_code == 409
    assert len(db.scalars(select(RecognitionEvent)).all()) == 1


def test_scan_frame_returns_face_box_without_exposing_identity_for_unknown_face(monkeypatch):
    from backend.app.config import Settings
    monkeypatch.setattr("backend.app.api.get_settings", lambda: Settings(_env_file=None))
    db = build_db()
    teacher, _student, class_ = seed(db)
    session = open_session(db, class_id=class_.id, opened_by=teacher.id)

    class FakeRecognizer:
        model_version = "test-model"
        distance_metric = "euclidean"

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
    from backend.app.config import Settings
    monkeypatch.setattr("backend.app.api.get_settings", lambda: Settings(_env_file=None))
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


def test_scan_does_not_report_success_when_service_did_not_save_attendance(monkeypatch):
    from backend.app.config import Settings

    monkeypatch.setattr("backend.app.api.get_settings", lambda: Settings(_env_file=None))
    db = build_db()
    teacher, student, class_ = seed(db)
    session = open_session(db, class_id=class_.id, opened_by=teacher.id)
    add_pose_templates(db, student)
    recognizer = type("Recognizer", (), {"model_version": "test-model", "distance_metric": "euclidean",
                                        "extract_single_embedding": lambda *_: EmbeddingResult(True, np.zeros(128, np.float32))})()
    monkeypatch.setattr("backend.app.api.build_default_recognizer", lambda: recognizer)
    monkeypatch.setattr("backend.app.api.create_recognition_event", lambda *args, **kwargs: (None, None))
    response = scan_frame(session.id, FrameScanRequest(image_base64=base64.b64encode(b"frame").decode()), teacher, db)
    assert response.decision == "unknown" and response.attendance is None and response.student_id is None


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


@pytest.fixture
def api_context(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy.pool import StaticPool
    from backend.app.api import router, _camera_confirmations
    from backend.app.config import Settings
    from backend.app.database import get_db

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    teacher, student, class_ = seed(db)
    session = open_session(db, class_id=class_.id, opened_by=teacher.id)
    settings = Settings(_env_file=None, camera_api_token="test-camera-token")
    monkeypatch.setattr("backend.app.api.get_settings", lambda: settings)
    monkeypatch.setattr("backend.app.security.get_settings", lambda: settings)
    monkeypatch.setattr("backend.app.services.stream_recognition.get_settings", lambda: settings)
    monkeypatch.setattr("backend.app.api._save_attendance_evidence", lambda *_args, **_kwargs: None)

    from backend.app.security import issue_session
    credentials = issue_session(db, teacher)
    clock = [100.0]

    def tick():
        clock[0] += 0.6
        return clock[0]

    monkeypatch.setattr("backend.app.services.stream_recognition.monotonic", tick)

    class Recognizer:
        model_name = "test-engine"
        model_version = "test-model"
        distance_metric = "euclidean"
        supports_pose = True
        result = EmbeddingResult(True, np.zeros(128, np.float32), face_box=(10, 20, 90, 100))

        def extract_single_embedding(self, *_args, **_kwargs):
            return self.result

        def extract_frame_embeddings(self, *_args, **_kwargs):
            from ai_pipeline.recognition import FrameEmbeddingResult

            return FrameEmbeddingResult(tuple(getattr(self, "stream_faces", [self.result])), 640, 480)

    recognizer = Recognizer()
    monkeypatch.setattr("backend.app.api.build_default_recognizer", lambda: recognizer)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    _camera_confirmations.cache_clear()
    from backend.app.services.stream_recognition import stream_states
    stream_states.cache_clear()
    with TestClient(app) as client:
        client.headers["Authorization"] = f"Bearer {credentials['access_token']}"
        yield client, db, teacher, student, class_, session, settings, recognizer
    db.close()
    engine.dispose()
    _camera_confirmations.cache_clear()
    stream_states.cache_clear()


def add_pose_templates(db, student, version="test-model", poses=("front", "left", "right", "up", "down"), vector=None):
    for pose in poses:
        db.add(FaceTemplate(student_id=student.id, embedding=(np.zeros(128, np.float32) if vector is None else vector).tobytes(),
                            model_name="test-engine", model_version=version, embedding_dim=128,
                            pose_label=pose, is_active=True))
    db.commit()


def test_policy_offset_is_normalized_to_utc_and_lateness_is_unchanged_on_roundtrip(api_context):
    from datetime import datetime, timezone
    from backend.app.services.attendance import calculate_late_minutes
    client, db, _, _, _, session, _, _ = api_context
    url = f"/sessions/{session.id}/policy"
    response = client.put(url, json={"expected_start_time": "2026-10-31T07:00:00+07:00", "late_grace_minutes": 5})
    assert response.status_code == 200
    db.expire_all()
    stored = db.get(type(session), session.id)
    assert stored.expected_start_time.replace(tzinfo=timezone.utc) == datetime(2026, 10, 31, 0, tzinfo=timezone.utc)
    assert calculate_late_minutes(stored, datetime(2026, 10, 31, 0, 6, tzinfo=timezone.utc)) == 1
    open_session_response = client.get("/attendance-requests/open").json()[0]
    assert open_session_response["expected_start_time"].endswith("Z")
    response = client.put(url, json={"expected_start_time": open_session_response["expected_start_time"], "late_grace_minutes": 5})
    assert response.status_code == 200
    db.expire_all()
    assert db.get(type(session), session.id).expected_start_time.replace(tzinfo=timezone.utc) == datetime(2026, 10, 31, 0, tzinfo=timezone.utc)


def test_face_readiness_uses_enrolled_consented_students_and_current_model(api_context):
    client, db, _, student, _, session, _, _ = api_context
    url = f"/sessions/{session.id}/face-readiness"
    assert client.get(url).json() == {"ready": 0, "total": 1, "engine_ready": True}
    add_pose_templates(db, student, version="old-model")
    assert client.get(url).json()["ready"] == 0
    add_pose_templates(db, student)
    assert client.get(url).json()["ready"] == 1
    student.consent_status = ConsentStatus.REVOKED.value
    db.commit()
    assert client.get(url).json()["ready"] == 0


def test_faceid_requires_class_enrollment_even_when_student_has_all_five_poses(api_context):
    client, db, teacher, student, _, _, _, _ = api_context
    other_class = Class(code="OTHER", name="Other Class", teacher_id=teacher.id)
    db.add(other_class)
    db.commit()
    other_session = open_session(db, class_id=other_class.id, opened_by=teacher.id)
    add_pose_templates(db, student)
    assert client.get(f"/sessions/{other_session.id}/face-readiness").json() == {
        "ready": 0, "total": 0, "engine_ready": True,
    }
    summary = list_students_with_faces(teacher, db)[0].model_dump()
    assert summary["enrollment_complete"] is True
    assert summary["class_codes"] == ["C001"]
    assert client.post(f"/classes/{other_class.id}/enrollments/{student.id}").status_code == 204
    assert client.get(f"/sessions/{other_session.id}/face-readiness").json() == {
        "ready": 1, "total": 1, "engine_ready": True,
    }


def test_camera_routes_require_camera_token(api_context):
    client, _, _, _, _, session, _, _ = api_context
    assert client.get("/camera/pipeline").status_code == 422
    assert client.get("/camera/pipeline", headers={"X-Camera-Token": "invalid"}).status_code == 401
    headers = {"X-Camera-Token": "test-camera-token"}
    status = client.get("/camera/pipeline", headers=headers)
    assert status.status_code == 200 and status.json()["preprocessing_mode"] == "enforce"
    assert status.json()["preprocessing_version"] == "v3"
    body = {"image_base64": base64.b64encode(b"frame").decode()}
    assert client.post(f"/sessions/{session.id}/camera-scan-frame", json=body).status_code == 422
    assert client.get("/face-analysis/status", headers={"Authorization": ""}).status_code == 401


def test_legacy_camera_policy_does_not_require_backend_image_dependencies(api_context, monkeypatch):
    client, _, _, _, _, _, settings, _ = api_context
    settings.preprocessing_mode = "off"

    def unavailable():
        raise AssertionError("Legacy camera policy must not load the backend recognizer")

    monkeypatch.setattr("backend.app.api.build_default_recognizer", unavailable)
    response = client.get("/camera/pipeline", headers={"X-Camera-Token": "test-camera-token"})
    assert response.status_code == 200 and response.json()["preprocessing_mode"] == "off"


@pytest.mark.parametrize("reason", ["No face detected", "Multiple faces detected", "Image is blurry: blur score 1.0"])
def test_both_scan_routes_hide_identity_and_write_nothing_after_source_rejection(api_context, reason):
    client, db, teacher, _, _, session, settings, recognizer = api_context
    recognizer.result = EmbeddingResult(False, np.empty(0, np.float32), reason=reason, face_box=(10, 20, 90, 100))
    body = {"image_base64": base64.b64encode(b"frame").decode()}
    for route, headers in (("scan-frame", {"Authorization": client.headers["Authorization"]}),
                           ("camera-scan-frame", {"X-Camera-Token": "test-camera-token"})):
        response = client.post(f"/sessions/{session.id}/{route}", json=body, headers=headers)
        assert response.status_code == 200
        result = response.json()
        assert result["decision"] == "unknown" and result["face_box"] == [10, 20, 90, 100]
        assert result["student_id"] is None and result["full_name"] is None and result["attendance"] is None
    assert db.scalar(select(RecognitionEvent)) is None
    assert db.scalar(select(AttendanceRecord)) is None


def test_camera_dry_run_confirms_without_writes_and_real_scan_records_once(api_context):
    client, db, _, student, _, session, _, _ = api_context
    add_pose_templates(db, student)
    headers = {"X-Camera-Token": "test-camera-token"}
    url = f"/sessions/{session.id}/camera-scan-frame"
    body = {"image_base64": base64.b64encode(b"frame").decode(), "idempotency_key": "camera-test"}
    for index in range(3):
        result = client.post(url, params={"dry_run": "true", "stream_id": "one"}, headers=headers, json=body).json()
        assert result["decision"] == ("recognized" if index == 2 else "low_confidence")
    assert db.scalar(select(RecognitionEvent)) is None
    assert db.scalar(select(AttendanceRecord)) is None
    result = client.post(url, params={"stream_id": "one"}, headers=headers, json=body).json()
    assert result["decision"] == "recognized" and result["attendance"] is not None
    again = client.post(url, params={"stream_id": "one"}, headers=headers, json=body).json()
    assert again["already_recorded"] is True
    assert len(db.scalars(select(AttendanceRecord)).all()) == 1


def test_enrollment_rejection_does_not_capture_a_pose(api_context):
    client, db, teacher, student, _, _, settings, recognizer = api_context
    recognizer.result = EmbeddingResult(False, np.empty(0, np.float32), reason="Image is blurry: blur score 1.0")
    response = client.post(f"/students/{student.id}/face-enrollment/scan", headers={"Authorization": client.headers["Authorization"]},
                           json={"image_base64": base64.b64encode(b"frame").decode(), "target_pose": "front"})
    assert response.status_code == 200
    result = response.json()
    assert not result["accepted"] and result["captured_poses"] == [] and not result["completed"]
    assert db.scalar(select(FaceTemplate)) is None


def test_reenrollment_keeps_previous_templates_until_five_new_poses_are_saved(api_context, monkeypatch, tmp_path):
    from ai_pipeline.recognition import PoseResult
    from backend.app.models import FaceEnrollmentDraft
    from backend.app.config import Settings

    client, db, _, student, _, _, _, recognizer = api_context
    monkeypatch.setattr("backend.app.services.face_templates.get_settings", lambda: Settings(_env_file=None, storage_dir=tmp_path))
    monkeypatch.setattr("backend.app.services.face_templates.normalize_portrait_4x6", lambda image, _recognizer: image)
    add_pose_templates(db, student)
    old_ids = {item.id for item in db.scalars(select(FaceTemplate).where(FaceTemplate.is_active.is_(True))).all()}
    start_url = f"/students/{student.id}/face-enrollment/start"
    scan_url = f"/students/{student.id}/face-enrollment/scan"
    first_id = client.post(start_url).json()["enrollment_id"]
    new_id = client.post(start_url).json()["enrollment_id"]
    body = {"image_base64": base64.b64encode(b"fake-image").decode(), "target_pose": "front", "enrollment_id": first_id}
    assert client.post(scan_url, json=body).status_code == 409
    body["enrollment_id"] = new_id
    for index, pose in enumerate(("front", "left", "right", "up", "down")):
        recognizer.result = EmbeddingResult(True, np.full(128, index + 1, np.float32),
                                            pose=PoseResult(pose, 0, 0), face_box=(10, 20, 90, 100))
        body["target_pose"] = pose
        if index == 4:
            from backend.app import api
            original_register = api.register_face_bytes
            calls = []
            def fail_during_switch(*args, **kwargs):
                calls.append(True)
                if len(calls) == 2:
                    raise RuntimeError("simulated storage failure")
                return original_register(*args, **kwargs)
            monkeypatch.setattr(api, "register_face_bytes", fail_during_switch)
            with pytest.raises(RuntimeError, match="simulated storage failure"):
                client.post(scan_url, json=body)
            db.rollback()
            assert {item.id for item in db.scalars(select(FaceTemplate).where(FaceTemplate.is_active.is_(True))).all()} == old_ids
            monkeypatch.setattr(api, "register_face_bytes", original_register)
        response = client.post(scan_url, json=body)
        assert response.status_code == 200
        assert response.json()["captured_poses"] == ["front", "left", "right", "up", "down"][:index + 1]
        active = db.scalars(select(FaceTemplate).where(FaceTemplate.is_active.is_(True))).all()
        if index < 4:
            assert {item.id for item in active} == old_ids
        else:
            assert len(active) == 5 and not ({item.id for item in active} & old_ids)
            assert {item.pose_label for item in active} == {"front", "left", "right", "up", "down"}
    assert db.scalars(select(FaceEnrollmentDraft)).all() == []
    assert client.post(scan_url, json=body).status_code == 409


def test_cancelling_reenrollment_preserves_active_faces_and_discards_draft(api_context):
    from ai_pipeline.recognition import PoseResult
    from backend.app.models import FaceEnrollmentDraft

    client, db, _, student, _, _, _, recognizer = api_context
    add_pose_templates(db, student)
    old_ids = {item.id for item in db.scalars(select(FaceTemplate).where(FaceTemplate.is_active.is_(True))).all()}
    enrollment_id = client.post(f"/students/{student.id}/face-enrollment/start").json()["enrollment_id"]
    recognizer.result = EmbeddingResult(True, np.ones(128, np.float32), pose=PoseResult("front", 0, 0))
    body = {"image_base64": base64.b64encode(b"frame").decode(), "target_pose": "front", "enrollment_id": enrollment_id}
    assert client.post(f"/students/{student.id}/face-enrollment/scan", json=body).status_code == 200
    assert client.delete(f"/students/{student.id}/face-enrollment/draft", params={"enrollment_id": enrollment_id}).status_code == 204
    assert db.scalars(select(FaceEnrollmentDraft)).all() == []
    assert {item.id for item in db.scalars(select(FaceTemplate).where(FaceTemplate.is_active.is_(True))).all()} == old_ids
    assert client.post(f"/students/{student.id}/face-enrollment/scan", json=body).status_code == 409


def test_mixed_preprocessing_versions_cannot_complete_enrollment_or_reach_worker(api_context):
    from backend.app.api import _enrollment_progress, list_class_face_templates

    _, db, teacher, student, class_, _, _, _ = api_context
    add_pose_templates(db, student, "old", ("front", "left", "right", "up"))
    add_pose_templates(db, student, "new", ("down",))
    assert dashboard_summary(teacher, db).enrolled_students == 0
    assert not list_students_with_faces(teacher, db)[0].enrollment_complete
    assert _enrollment_progress(db, student.id, "new")[0] == ["down"]
    assert list_class_face_templates(class_.id, db) == []
    add_pose_templates(db, student, "old", ("down",))
    assert dashboard_summary(teacher, db).enrolled_students == 1
    assert {item["model_version"] for item in list_class_face_templates(class_.id, db)} == {"old"}


@pytest.mark.parametrize("legacy_fields", [{}, {"challenge_id": "obsolete", "step_token": "obsolete", "sequence": 0}])
def test_web_scan_records_without_challenge_pose_or_pad(api_context, legacy_fields):
    client, db, teacher, student, _, session, _, recognizer = api_context
    assert recognizer.result.pose is None and recognizer.result.diagnostics is None
    add_pose_templates(db, student)
    response = client.post(f"/sessions/{session.id}/scan-frame", headers={"Authorization": client.headers["Authorization"]},
                           json={"image_base64": base64.b64encode(b"frame").decode(), **legacy_fields})
    assert response.status_code == 200
    result = response.json()
    assert result["decision"] == "recognized" and result["attendance"] is not None
    assert "liveness" not in result
    again = client.post(f"/sessions/{session.id}/scan-frame", headers={"Authorization": client.headers["Authorization"]},
                        json={"image_base64": base64.b64encode(b"frame").decode()}).json()
    assert again["already_recorded"] is True
    assert len(db.scalars(select(RecognitionEvent)).all()) == 1


def test_retired_challenge_and_schema_are_not_exposed(api_context):
    client, _, teacher, _, _, session, _, _ = api_context
    response = client.post(f"/sessions/{session.id}/liveness-challenge", headers={"Authorization": client.headers["Authorization"]})
    assert response.status_code == 404
    schema = client.get("/openapi.json").json()
    assert "WebLivenessState" not in schema["components"]["schemas"]
    fields = schema["components"]["schemas"]["FrameScanRequest"]["properties"]
    assert not {"challenge_id", "step_token", "sequence"} & fields.keys()
    response = client.get("/face-analysis/status", headers={"Authorization": client.headers["Authorization"]})
    assert response.status_code == 200
    assert not any("liveness" in key for key in response.json())


def test_consent_revocation_still_prevents_web_attendance(api_context):
    client, db, teacher, student, _, session, _, _ = api_context
    add_pose_templates(db, student)
    student.consent_status = ConsentStatus.REVOKED.value
    db.commit()
    response = client.post(f"/sessions/{session.id}/scan-frame", headers={"Authorization": client.headers["Authorization"]},
                           json={"image_base64": base64.b64encode(b"frame").decode()})
    assert response.json()["decision"] == "unknown"
    assert db.scalar(select(AttendanceRecord)) is None


def test_camera_events_still_require_a_valid_token_after_guard_removal(api_context):
    client, db, _, student, _, session, _, _ = api_context
    body = {"student_id": student.id, "decision": "recognized", "model_version": "test-model",
            "idempotency_key": "trusted-event", "candidate_score": 0.99}
    url = f"/sessions/{session.id}/recognition-events"
    assert client.post(url, json=body, headers={"X-Camera-Token": "invalid"}).status_code == 401
    assert db.scalar(select(RecognitionEvent)) is None
    assert client.post(url, json=body, headers={"X-Camera-Token": "test-camera-token"}).status_code == 200
    assert db.scalar(select(AttendanceRecord)) is not None


def post_stream(context, frame_id, *, stream_id="stream-one", camera=False, dry_run=False):
    client, _, teacher, _, _, session, _, _ = context
    return client.post(f"/sessions/{session.id}/{'camera-scan-stream' if camera else 'scan-stream'}",
                       params={"dry_run": str(dry_run).lower()} if camera else {},
                       headers={"X-Camera-Token": "test-camera-token"} if camera else {"Authorization": client.headers["Authorization"]},
                       json={"image_base64": base64.b64encode(f"frame-{frame_id}".encode()).decode(), "stream_id": stream_id,
                             "frame_id": frame_id, "camera_id": "group-camera"})


def add_stream_student(context, number):
    _, db, _, _, class_, _, _, _ = context
    student = Student(student_code=f"GROUP{number}", full_name=f"Group Student {number}",
                      consent_status=ConsentStatus.GRANTED.value)
    db.add(student)
    db.commit()
    db.refresh(student)
    db.add(ClassEnrollment(class_id=class_.id, student_id=student.id))
    db.commit()
    vector = np.full(128, 0.2 * number, np.float32)
    add_pose_templates(db, student, vector=vector)
    return student, vector


def test_stream_records_people_independently_and_keeps_processing_departures_and_new_arrivals(api_context):
    _, db, _, first, _, _, _, recognizer = api_context
    add_pose_templates(db, first)
    second, second_vector = add_stream_student(api_context, 1)
    third, third_vector = add_stream_student(api_context, 2)
    face_a = EmbeddingResult(True, np.zeros(128, np.float32), face_box=(20, 30, 100, 120))
    face_b = EmbeddingResult(True, second_vector, face_box=(180, 30, 100, 120))
    face_c = EmbeddingResult(True, third_vector, face_box=(340, 30, 100, 120))
    recognizer.stream_faces = [face_a, face_b]
    for frame_id in (0, 1):
        result = post_stream(api_context, frame_id).json()
        assert all(face["decision"] == "pending" and face["full_name"] is None for face in result["faces"])
    recognizer.stream_faces = [face_a, EmbeddingResult(False, np.empty(0, np.float32),
                                                      reason="Image is blurry: blur score 1.0", face_box=face_b.face_box)]
    result = post_stream(api_context, 2).json()
    assert result["faces"][0]["student_id"] == first.id and result["faces"][0]["attendance"] is not None
    assert result["faces"][1]["decision"] == "unknown" and result["faces"][1]["confirmation_hits"] == 0
    assert len(db.scalars(select(AttendanceRecord)).all()) == 1
    recognizer.stream_faces = [face_b, face_c]
    for frame_id in (3, 4, 5):
        result = post_stream(api_context, frame_id).json()
    assert {face["student_id"] for face in result["faces"]} == {second.id, third.id}
    assert all(face["decision"] == "recognized" and face["attendance"] for face in result["faces"])
    for frame_id in (6, 7, 8):
        again = post_stream(api_context, frame_id).json()
        assert all(face["already_recorded"] for face in again["faces"])
    assert len(db.scalars(select(AttendanceRecord)).all()) == 3
    assert len(db.scalars(select(RecognitionEvent)).all()) == 3


def test_stream_duplicate_identity_in_same_frame_cannot_confirm_or_write_twice(api_context):
    _, db, _, student, _, _, _, recognizer = api_context
    add_pose_templates(db, student)
    recognizer.stream_faces = [EmbeddingResult(True, np.zeros(128, np.float32), face_box=box)
                               for box in ((20, 30, 100, 120), (180, 30, 100, 120))]
    for frame_id in range(5):
        result = post_stream(api_context, frame_id).json()
        assert all(face["full_name"] is None and face["confirmation_hits"] == 0 for face in result["faces"])
    assert db.scalar(select(AttendanceRecord)) is None
    assert db.scalar(select(RecognitionEvent)) is None


def test_stream_repeated_frames_are_rejected_and_clients_do_not_share_votes(api_context):
    _, db, _, student, _, _, _, _ = api_context
    add_pose_templates(db, student)
    assert post_stream(api_context, 0).json()["faces"][0]["confirmation_hits"] == 1
    assert post_stream(api_context, 0).status_code == 409
    assert post_stream(api_context, 0, stream_id="different-client").json()["faces"][0]["confirmation_hits"] == 1
    assert post_stream(api_context, 1).json()["faces"][0]["confirmation_hits"] == 2
    assert post_stream(api_context, 2).json()["faces"][0]["attendance"] is not None
    assert len(db.scalars(select(AttendanceRecord)).all()) == 1


def test_stream_empty_frame_removes_votes_and_new_person_cannot_inherit_them(api_context):
    _, db, _, first, _, _, _, recognizer = api_context
    add_pose_templates(db, first)
    post_stream(api_context, 0)
    post_stream(api_context, 1)
    recognizer.stream_faces = []
    assert post_stream(api_context, 2).json()["faces"] == []
    second, vector = add_stream_student(api_context, 1)
    recognizer.stream_faces = [EmbeddingResult(True, vector, face_box=recognizer.result.face_box)]
    result = post_stream(api_context, 3).json()
    assert result["faces"][0]["confirmation_hits"] == 1 and result["faces"][0]["full_name"] is None
    post_stream(api_context, 4)
    result = post_stream(api_context, 5).json()
    assert result["faces"][0]["student_id"] == second.id
    assert db.scalar(select(AttendanceRecord)).student_id == second.id


def test_camera_stream_dry_run_is_isolated_and_camera_token_is_required(api_context):
    client, db, _, student, _, session, _, _ = api_context
    add_pose_templates(db, student)
    body = {"image_base64": "ZnJhbWU=", "stream_id": "unauthorized", "frame_id": 0}
    assert client.post(f"/sessions/{session.id}/camera-scan-stream", json=body).status_code == 422
    assert client.post(f"/sessions/{session.id}/camera-scan-stream", json=body,
                       headers={"X-Camera-Token": "wrong"}).status_code == 401
    for frame_id in range(3):
        result = post_stream(api_context, frame_id, camera=True, dry_run=True).json()
    assert result["faces"][0]["decision"] == "recognized" and result["faces"][0]["attendance"] is None
    assert db.scalar(select(AttendanceRecord)) is None
    assert post_stream(api_context, 0, camera=True).json()["faces"][0]["confirmation_hits"] == 1
    post_stream(api_context, 1, camera=True)
    result = post_stream(api_context, 2, camera=True).json()
    assert result["faces"][0]["attendance"] is not None


def test_stream_rechecks_consent_before_confirming_and_respects_closed_session(api_context):
    client, db, teacher, student, _, session, _, _ = api_context
    add_pose_templates(db, student)
    post_stream(api_context, 0)
    post_stream(api_context, 1)
    student.consent_status = ConsentStatus.REVOKED.value
    db.commit()
    result = post_stream(api_context, 2).json()
    assert result["faces"][0]["full_name"] is None and result["faces"][0]["attendance"] is None
    assert db.scalar(select(AttendanceRecord)) is None
    session.status = "closed"
    db.commit()
    assert post_stream(api_context, 3).status_code == 409


def test_same_image_with_new_sequence_cannot_add_votes(api_context):
    client, db, _, student, _, session, _, _ = api_context
    add_pose_templates(db, student)
    body = {"image_base64": "ZnJvemVuLWZyYW1l", "stream_id": "frozen", "frame_id": 0}
    assert client.post(f"/sessions/{session.id}/scan-stream", json=body).json()["faces"][0]["confirmation_hits"] == 1
    body["frame_id"] = 1
    assert client.post(f"/sessions/{session.id}/scan-stream", json=body).status_code == 409
    assert db.scalar(select(AttendanceRecord)) is None


def test_rapid_distinct_frames_do_not_confirm_and_timings_are_reported(api_context, monkeypatch):
    _, db, _, student, _, _, _, _ = api_context
    add_pose_templates(db, student)
    monkeypatch.setattr("backend.app.services.stream_recognition.monotonic", lambda: 100.0)
    for index in range(4):
        response = post_stream(api_context, index)
        assert response.status_code == 200
        result = response.json()
        assert result["faces"][0]["confirmation_hits"] == 1
        assert set(result["timings_ms"]) == {"inference", "gallery", "matching"}
    assert db.scalar(select(AttendanceRecord)) is None


def test_histogram_fallback_cannot_mark_attendance(api_context):
    _, db, _, _, _, _, _, recognizer = api_context
    recognizer.distance_metric = "cosine"
    assert post_stream(api_context, 0).status_code == 503
    assert db.scalar(select(AttendanceRecord)) is None
