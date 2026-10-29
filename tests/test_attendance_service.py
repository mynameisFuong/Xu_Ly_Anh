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
    monkeypatch.setattr("backend.app.api.get_settings", lambda: Settings(_env_file=None, web_liveness_required=False))
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
    from backend.app.config import Settings
    monkeypatch.setattr("backend.app.api.get_settings", lambda: Settings(_env_file=None, web_liveness_required=False))
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

    monkeypatch.setattr("backend.app.api.get_settings", lambda: Settings(_env_file=None, web_liveness_required=False))
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
    from backend.app.api import router, _camera_confirmations, _web_liveness_store
    from backend.app.config import Settings
    from backend.app.database import get_db

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    teacher, student, class_ = seed(db)
    session = open_session(db, class_id=class_.id, opened_by=teacher.id)
    settings = Settings(_env_file=None, camera_api_token="test-camera-token", web_liveness_required=False)
    monkeypatch.setattr("backend.app.api.get_settings", lambda: settings)
    monkeypatch.setattr("backend.app.security.get_settings", lambda: settings)
    monkeypatch.setattr("backend.app.api._save_attendance_evidence", lambda *_args, **_kwargs: None)

    class Recognizer:
        model_name = "test-engine"
        model_version = "test-model"
        distance_metric = "euclidean"
        supports_pose = True
        result = EmbeddingResult(True, np.zeros(128, np.float32), face_box=(10, 20, 90, 100))

        def extract_single_embedding(self, *_args, **_kwargs):
            return self.result

    recognizer = Recognizer()
    monkeypatch.setattr("backend.app.api.build_default_recognizer", lambda: recognizer)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    _camera_confirmations.cache_clear()
    _web_liveness_store.cache_clear()
    with TestClient(app) as client:
        yield client, db, teacher, student, class_, session, settings, recognizer
    db.close()
    engine.dispose()
    _camera_confirmations.cache_clear()
    _web_liveness_store.cache_clear()


@pytest.fixture
def web_context(api_context, monkeypatch):
    from types import SimpleNamespace
    from ai_pipeline.analysis import AnalysisDiagnostics
    from ai_pipeline.liveness import LivenessResult
    from ai_pipeline.recognition import PoseResult
    from backend.app.services.web_liveness import WebLivenessStore

    client, db, teacher, student, _, session, settings, recognizer = api_context
    settings.web_liveness_required = True
    settings.liveness_mode = "enforce"
    recognizer._analysis = SimpleNamespace(liveness=SimpleNamespace(ready=True, approved=True))
    recognizer.result = EmbeddingResult(True, np.zeros(128, np.float32),
                                       pose=PoseResult("front", 0, 0), face_box=(10, 20, 90, 100),
                                       diagnostics=AnalysisDiagnostics(liveness=LivenessResult("live", 0.99)))
    now = [100.0]
    store = WebLivenessStore(settings, clock=lambda: now[0], choose=lambda: ["left", "up", "right"])
    monkeypatch.setattr("backend.app.api._web_liveness_store", lambda: store)
    add_pose_templates(db, student)
    yield api_context, now, store


def test_web_missing_challenge_cannot_record_even_with_client_liveness_claim(web_context):
    context, _, _ = web_context
    client, db, teacher, _, _, session, _, _ = context
    response = client.post(f"/sessions/{session.id}/scan-frame", headers={"X-User-Id": str(teacher.id)},
                           json={"image_base64": base64.b64encode(b"frame").decode(),
                                 "camera_id": "trusted-camera", "liveness": {"status": "live"}})
    assert response.status_code == 200 and response.json()["liveness"]["status"] == "required"
    assert response.json()["student_id"] is None
    assert db.scalar(select(AttendanceRecord)) is None and db.scalar(select(RecognitionEvent)) is None


def test_web_full_challenge_only_records_on_last_step_and_cannot_be_reused(web_context):
    from dataclasses import replace
    from ai_pipeline.recognition import PoseResult

    context, now, _ = web_context
    client, db, teacher, _, _, session, _, recognizer = context
    headers = {"X-User-Id": str(teacher.id)}
    start_url = f"/sessions/{session.id}/liveness-challenge"
    url = f"/sessions/{session.id}/scan-frame"
    assert client.post(start_url).status_code == 422
    state = client.post(start_url, headers=headers).json()
    index = 0
    for yaw, pitch in ((0, 0), (-22, 0), (0, 0), (0, -16), (0, 0), (22, 0), (0, 0)):
        recognizer.result = replace(recognizer.result, pose=PoseResult("front", yaw, pitch))
        for _ in range(2):
            now[0] += 0.7
            index += 1
            body = {"image_base64": base64.b64encode(f"frame-{index}".encode()).decode(),
                    **{key: state[key] for key in ("challenge_id", "step_token", "sequence")}}
            response = client.post(url, headers=headers, json=body)
            assert response.status_code == 200
            result = response.json()
            if index < 14:
                assert result["decision"] == "unknown" and result["student_id"] is None
                assert db.scalar(select(AttendanceRecord)) is None
                state = result["liveness"]
    assert result["liveness"]["status"] == "passed" and result["attendance"] is not None
    assert len(db.scalars(select(AttendanceRecord)).all()) == 1
    replay = client.post(url, headers=headers, json=body).json()
    assert replay["decision"] == "unknown" and replay["student_id"] is None
    assert len(db.scalars(select(RecognitionEvent)).all()) == 1


@pytest.mark.parametrize("attack", ["spoof", "missing-pad", "nonce", "consent"])
def test_web_rejections_do_not_write_anything(web_context, attack):
    from dataclasses import replace

    context, now, store = web_context
    client, db, teacher, student, _, session, _, recognizer = context
    headers = {"X-User-Id": str(teacher.id)}
    state = client.post(f"/sessions/{session.id}/liveness-challenge", headers=headers).json()
    if attack == "spoof":
        recognizer.result = EmbeddingResult(False, np.empty(0, np.float32), reason="Liveness spoof suspected")
    elif attack == "missing-pad":
        recognizer.result = replace(recognizer.result, diagnostics=None)
    elif attack == "nonce":
        state["step_token"] = "forged"
    elif attack == "consent":
        student.consent_status = ConsentStatus.REVOKED.value
        db.commit()
    body = {"image_base64": base64.b64encode(b"frame").decode(),
            **{key: state[key] for key in ("challenge_id", "step_token", "sequence")}}
    now[0] += 0.7
    result = client.post(f"/sessions/{session.id}/scan-frame", headers=headers, json=body).json()
    assert result["decision"] == "unknown" and result["student_id"] is None
    assert db.scalar(select(AttendanceRecord)) is None and db.scalar(select(RecognitionEvent)) is None
    assert not store.valid(state["challenge_id"], ("user", teacher.id, session.id))


def test_web_challenge_refuses_unavailable_passive_guard(web_context):
    context, _, _ = web_context
    client, _, teacher, _, _, session, settings, _ = context
    settings.liveness_mode = "off"
    response = client.post(f"/sessions/{session.id}/liveness-challenge", headers={"X-User-Id": str(teacher.id)})
    assert response.status_code == 503


def test_web_completes_with_isolated_face_misses_without_recording_failed_frames(web_context):
    from dataclasses import replace
    from ai_pipeline.recognition import PoseResult

    context, now, store = web_context
    client, db, teacher, _, _, session, _, recognizer = context
    headers = {"X-User-Id": str(teacher.id)}
    url = f"/sessions/{session.id}/scan-frame"
    state = client.post(f"/sessions/{session.id}/liveness-challenge", headers=headers).json()
    challenge_id = state["challenge_id"]
    valid_frame = recognizer.result
    counter = 0
    for step, (yaw, pitch) in enumerate(((0, 0), (-22, 0), (0, 0), (0, -16), (0, 0), (22, 0), (0, 0))):
        # Một frame đúng, một frame mất mặt, rồi đủ hai frame đúng liên tiếp.
        for missing in (False, True, False, False):
            counter += 1
            now[0] += 0.7
            recognizer.result = (EmbeddingResult(False, np.empty(0, np.float32), reason="No face detected")
                                 if missing else replace(valid_frame, pose=PoseResult("front", yaw, pitch)))
            body = {"image_base64": base64.b64encode(f"frame-{counter}".encode()).decode(),
                    **{key: state[key] for key in ("challenge_id", "step_token", "sequence")}}
            response = client.post(url, headers=headers, json=body)
            assert response.status_code == 200
            result = response.json()
            if counter < 28:
                state = result["liveness"]
                assert state["status"] == "pending" and state["challenge_id"] == challenge_id
                assert result["student_id"] is None and result["attendance"] is None
                assert db.scalar(select(AttendanceRecord)) is None and db.scalar(select(RecognitionEvent)) is None
                if missing:
                    assert state["step"] == step
    assert result["liveness"]["status"] == "passed" and result["attendance"] is not None
    assert len(db.scalars(select(AttendanceRecord)).all()) == 1
    assert not store.valid(challenge_id, ("user", teacher.id, session.id))


def test_web_multiple_faces_cancels_instead_of_using_transient_recovery(web_context):
    context, now, store = web_context
    client, db, teacher, _, _, session, _, recognizer = context
    headers = {"X-User-Id": str(teacher.id)}
    state = client.post(f"/sessions/{session.id}/liveness-challenge", headers=headers).json()
    recognizer.result = EmbeddingResult(False, np.empty(0, np.float32), reason="Multiple faces detected")
    now[0] += 0.7
    body = {"image_base64": base64.b64encode(b"multiple-faces").decode(),
            **{key: state[key] for key in ("challenge_id", "step_token", "sequence")}}
    result = client.post(f"/sessions/{session.id}/scan-frame", headers=headers, json=body).json()
    assert result["liveness"]["status"] == "failed" and result["student_id"] is None
    assert not store.valid(state["challenge_id"], ("user", teacher.id, session.id))
    assert db.scalar(select(AttendanceRecord)) is None


def add_pose_templates(db, student, version="test-model", poses=("front", "left", "right", "up", "down")):
    for pose in poses:
        db.add(FaceTemplate(student_id=student.id, embedding=np.zeros(128, np.float32).tobytes(),
                            model_name="test-engine", model_version=version, embedding_dim=128,
                            pose_label=pose, is_active=True))
    db.commit()


def test_camera_routes_require_camera_token(api_context):
    client, _, _, _, _, session, _, _ = api_context
    assert client.get("/camera/pipeline").status_code == 422
    assert client.get("/camera/pipeline", headers={"X-Camera-Token": "invalid"}).status_code == 401
    headers = {"X-Camera-Token": "test-camera-token"}
    status = client.get("/camera/pipeline", headers=headers)
    assert status.status_code == 200 and status.json()["liveness_mode"] == "off"
    body = {"image_base64": base64.b64encode(b"frame").decode()}
    assert client.post(f"/sessions/{session.id}/camera-scan-frame", json=body).status_code == 422
    assert client.get("/face-analysis/status").status_code == 422


def test_enforced_backend_blocks_unverified_events_before_writing(api_context):
    client, db, _, student, _, session, settings, _ = api_context
    settings.liveness_mode = "enforce"
    response = client.post(f"/sessions/{session.id}/recognition-events", headers={"X-Camera-Token": "test-camera-token"},
                           json={"student_id": student.id, "decision": "recognized", "model_version": "test-model",
                                 "idempotency_key": "unverified", "candidate_score": 0.99})
    assert response.status_code == 409
    assert db.scalar(select(RecognitionEvent)) is None
    assert db.scalar(select(AttendanceRecord)) is None


def test_legacy_camera_policy_does_not_require_backend_image_dependencies(api_context, monkeypatch):
    client, *_ = api_context

    def unavailable():
        raise AssertionError("Legacy camera policy must not load the backend recognizer")

    monkeypatch.setattr("backend.app.api.build_default_recognizer", unavailable)
    response = client.get("/camera/pipeline", headers={"X-Camera-Token": "test-camera-token"})
    assert response.status_code == 200 and response.json()["liveness_mode"] == "off"


@pytest.mark.parametrize("reason", ["Liveness spoof suspected", "Liveness uncertain", "Liveness unavailable"])
def test_both_scan_routes_hide_identity_and_write_nothing_after_pad_rejection(api_context, reason):
    client, db, teacher, _, _, session, settings, recognizer = api_context
    settings.liveness_mode = "enforce"
    recognizer.result = EmbeddingResult(False, np.empty(0, np.float32), reason=reason, face_box=(10, 20, 90, 100))
    body = {"image_base64": base64.b64encode(b"frame").decode()}
    for route, headers in (("scan-frame", {"X-User-Id": str(teacher.id)}),
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
    settings.liveness_mode = "enforce"
    recognizer.result = EmbeddingResult(False, np.empty(0, np.float32), reason="Liveness spoof suspected")
    response = client.post(f"/students/{student.id}/face-enrollment/scan", headers={"X-User-Id": str(teacher.id)},
                           json={"image_base64": base64.b64encode(b"frame").decode(), "target_pose": "front"})
    assert response.status_code == 200
    result = response.json()
    assert not result["accepted"] and result["captured_poses"] == [] and not result["completed"]
    assert db.scalar(select(FaceTemplate)) is None


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
