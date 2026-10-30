from datetime import timedelta
import hashlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.api import router
from backend.app.database import Base, get_db
from backend.app.models import AuthSession, Class, ClassEnrollment, ClassSession, Student, User, utc_now
from backend.app.security import hash_password, issue_session, token_digest


@pytest.fixture
def auth_context():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as db:
        teacher = User(username="teacher", password_hash=hashlib.sha256(b"teacher123").hexdigest(),
                       role="teacher", full_name="Teacher")
        other = User(username="other", password_hash=hash_password("other123"), role="teacher", full_name="Other")
        db.add_all([teacher, other])
        db.flush()
        class_ = Class(code="OWN", name="Own", teacher_id=other.id)
        db.add(class_)
        db.flush()
        session = ClassSession(class_id=class_.id, opened_by=other.id)
        db.add(session)
        db.commit()
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_db] = lambda: db
        with TestClient(app) as client:
            yield client, db, teacher, session
    engine.dispose()


def login(client):
    result = client.post("/auth/login-json", json={"username": "teacher", "password": "teacher123"})
    assert result.status_code == 200
    return {"Authorization": f"Bearer {result.json()['access_token']}"}


def test_header_impersonation_is_rejected_and_login_upgrades_legacy_password(auth_context):
    client, db, teacher, _ = auth_context
    assert client.get("/classes", headers={"X-User-Id": str(teacher.id)}).status_code == 401
    headers = login(client)
    assert teacher.password_hash.startswith("pbkdf2_sha256$")
    assert client.get("/classes", headers=headers).status_code == 200
    stored = db.scalar(select(AuthSession))
    assert stored.token_hash == token_digest(headers["Authorization"].split()[1])
    assert stored.token_hash not in headers["Authorization"]


def test_logout_expiry_invalid_token_and_inactive_account(auth_context):
    client, db, teacher, _ = auth_context
    headers = login(client)
    assert client.post("/auth/logout", headers=headers).status_code == 204
    assert client.get("/classes", headers=headers).status_code == 401
    headers = login(client)
    session = db.scalar(select(AuthSession))
    session.expires_at = utc_now() - timedelta(seconds=1)
    db.commit()
    assert client.get("/classes", headers=headers).status_code == 401
    assert client.get("/classes", headers={"Authorization": "Bearer invalid"}).status_code == 401
    headers = login(client)
    teacher.is_active = False
    db.commit()
    assert client.get("/classes", headers=headers).status_code == 401
    assert client.post("/auth/login-json", json={"username": "teacher", "password": "teacher123"}).status_code == 401


def test_teacher_cannot_read_scan_or_export_another_class(auth_context):
    client, _, _, session = auth_context
    headers = login(client)
    assert client.get("/classes", headers=headers).json() == []
    assert client.get("/attendance-requests/open", headers=headers).json() == []
    assert client.get(f"/sessions/{session.id}", headers=headers).status_code == 403
    assert client.get(f"/sessions/{session.id}/attendance-board", headers=headers).status_code == 403
    assert client.get(f"/reports/attendance.csv?session_id={session.id}", headers=headers).status_code == 403
    response = client.post(f"/sessions/{session.id}/scan-stream", headers=headers,
                           json={"image_base64": "ZnJhbWU=", "frame_id": 0, "stream_id": "a"})
    assert response.status_code == 403


def test_device_grant_and_revocation_take_effect_without_relogin(auth_context):
    client, db, _, session = auth_context
    admin = User(username="admin", password_hash=hash_password("admin123"), role="admin", full_name="Admin")
    device = User(username="device", password_hash=hash_password("device123"), role="user", full_name="Device")
    db.add_all([admin, device])
    db.commit()
    admin_headers = {"Authorization": f"Bearer {issue_session(db, admin)['access_token']}"}
    device_headers = {"Authorization": f"Bearer {issue_session(db, device)['access_token']}"}
    board = f"/sessions/{session.id}/attendance-board"
    grant = f"/classes/{session.class_id}/devices/{device.id}"
    assert client.get(board, headers=device_headers).status_code == 403
    assert client.put(grant, headers=admin_headers).status_code == 204
    assert client.put(grant, headers=admin_headers).status_code == 204
    assert client.get(board, headers=device_headers).status_code == 200
    assert len(client.get("/attendance-requests/open", headers=device_headers).json()) == 1
    assert client.delete(grant, headers=admin_headers).status_code == 204
    assert client.get(board, headers=device_headers).status_code == 403
    assert client.get("/attendance-requests/open", headers=device_headers).json() == []


def test_extra_query_parameters_cannot_bypass_student_class_scope(auth_context):
    client, db, teacher, foreign_session = auth_context
    own_class = Class(code="TEACHER", name="Teacher", teacher_id=teacher.id)
    foreign_student = Student(student_code="FOREIGN", full_name="Foreign", consent_status="granted")
    db.add_all([own_class, foreign_student])
    db.flush()
    own_session = ClassSession(class_id=own_class.id, opened_by=teacher.id)
    db.add_all([own_session, ClassEnrollment(class_id=foreign_session.class_id, student_id=foreign_student.id)])
    db.commit()
    headers = login(client)
    path = f"/students/{foreign_student.id}/face-enrollment/scan?class_id={own_class.id}&session_id={own_session.id}"
    assert client.post(path, headers=headers, json={"image_base64": "ZnJhbWU=", "target_pose": "front"}).status_code == 403
