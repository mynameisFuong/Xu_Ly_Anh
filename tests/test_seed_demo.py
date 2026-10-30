from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import sys

from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker

from backend.app.database import Base
from backend.app.models import AttendanceRecord, Class, ClassEnrollment, ClassSession, FaceEnrollmentDraft, FaceTemplate, Student, User
from scripts.seed_demo import seed_demo_data


def test_demo_seed_is_repeatable_and_never_creates_biometrics():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as db:
        now = datetime(2026, 10, 31, 0, tzinfo=timezone.utc)
        seed_demo_data(db, now=now)
        counts = {model.__name__: db.scalar(select(func.count()).select_from(model)) for model in
                  (User, Class, Student, ClassEnrollment, ClassSession, AttendanceRecord, FaceTemplate, FaceEnrollmentDraft)}
        assert counts == {"User": 3, "Class": 3, "Student": 12, "ClassEnrollment": 22,
                          "ClassSession": 5, "AttendanceRecord": 26, "FaceTemplate": 0, "FaceEnrollmentDraft": 0}
        assert len(db.scalars(select(ClassSession).where(ClassSession.status == "open")).all()) == 2
        assert all(row.source == "manual" and row.evidence_image_path is None and row.recognized_event_id is None
                   for row in db.scalars(select(AttendanceRecord)))
        record = db.scalar(select(AttendanceRecord))
        record.status = "excused"
        db.commit()
        seed_demo_data(db, now=now)
        assert {model.__name__: db.scalar(select(func.count()).select_from(model)) for model in
                (User, Class, Student, ClassEnrollment, ClassSession, AttendanceRecord, FaceTemplate, FaceEnrollmentDraft)} == counts
        assert db.get(AttendanceRecord, record.id).status == "excused"
    engine.dispose()


def test_demo_seed_preserves_existing_accounts_and_skips_colliding_personal_records():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as db:
        admin = User(username="admin", password_hash="existing-hash", role="admin", full_name="Existing")
        teacher = User(username="teacher", password_hash="existing-hash", role="teacher", full_name="Existing")
        person = Student(student_code="DEMO001", full_name="Existing student", consent_status="revoked")
        db.add_all([admin, teacher, person])
        db.flush()
        class_ = Class(code="DEMO-IMG01", name="Existing class", teacher_id=teacher.id)
        db.add(class_)
        db.commit()
        seed_demo_data(db)
        assert db.get(User, admin.id).password_hash == "existing-hash"
        assert db.get(Student, person.id).full_name == "Existing student"
        assert db.get(Class, class_.id).name == "Existing class"
        assert db.scalar(select(func.count()).select_from(ClassEnrollment).where(ClassEnrollment.class_id == class_.id)) == 0
        assert db.scalar(select(func.count()).select_from(ClassEnrollment).where(ClassEnrollment.student_id == person.id)) == 0
    engine.dispose()


def test_cli_seeds_existing_env_and_moves_metadata_between_databases(tmp_path):
    root = Path(__file__).resolve().parents[1]
    env = {**os.environ, "DATABASE_URL": "sqlite:///" + (tmp_path / "source.db").as_posix(),
           "STORAGE_DIR": str(tmp_path), "PYTHONIOENCODING": "cp1258"}
    def run(*args):
        return subprocess.run([sys.executable, "-B", *args], cwd=root, env=env,
                              capture_output=True, encoding="utf-8", check=True)
    run("scripts/seed_demo.py")
    run("scripts/seed_demo.py")
    output = tmp_path / "metadata.json"
    run("scripts/transfer_metadata.py", "export", str(output))
    env["DATABASE_URL"] = "sqlite:///" + (tmp_path / "target.db").as_posix()
    run("scripts/seed_demo.py")
    result = run("scripts/transfer_metadata.py", "import", str(output))
    assert "skipped_open_sessions" in result.stdout
