import json
from datetime import datetime, timezone

import numpy as np
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker

from backend.app.database import Base
from backend.app.models import AttendanceRecord, Class, ClassEnrollment, ClassSession, FaceTemplate, Student, User
from scripts.seed_demo import seed_demo_data
from scripts.transfer_metadata import export_metadata, import_metadata


def test_transfer_excludes_biometrics_and_credentials_and_is_repeatable():
    source_engine, target_engine = create_engine("sqlite:///:memory:"), create_engine("sqlite:///:memory:")
    Base.metadata.create_all(source_engine)
    Base.metadata.create_all(target_engine)
    with sessionmaker(bind=source_engine, expire_on_commit=False)() as source, sessionmaker(bind=target_engine, expire_on_commit=False)() as target:
        seed_demo_data(source, now=datetime(2026, 10, 31, tzinfo=timezone.utc))
        student = source.scalar(select(Student))
        source.add(FaceTemplate(student_id=student.id, embedding=np.ones(128, np.float32).tobytes(),
                                embedding_dim=128, model_name="model", model_version="v1", image_path="private-face.jpg"))
        source.scalar(select(AttendanceRecord)).evidence_image_path = "private-evidence.jpg"
        source.commit()
        metadata = export_metadata(source)
        encoded = json.dumps(metadata)
        assert "private-face.jpg" not in encoded and "private-evidence.jpg" not in encoded
        assert "embedding" not in json.dumps(metadata["students"])
        assert "password_hash" not in encoded and "token_hash" not in encoded
        target.add(User(username="teacher", password_hash="local-hash", role="teacher", full_name="Teacher"))
        target.commit()
        assert import_metadata(target, metadata)["skipped_open_sessions"] == 0
        counts = {model: target.scalar(select(func.count()).select_from(model)) for model in
                  (Class, Student, ClassEnrollment, ClassSession, AttendanceRecord, FaceTemplate)}
        assert counts == {Class: 3, Student: 12, ClassEnrollment: 22, ClassSession: 5,
                          AttendanceRecord: 26, FaceTemplate: 0}
        assert all(a.evidence_image_path is None and a.recognized_event_id is None
                   for a in target.scalars(select(AttendanceRecord)))
        import_metadata(target, metadata)
        assert {model: target.scalar(select(func.count()).select_from(model)) for model in counts} == counts
        assert target.scalar(select(User).where(User.username == "teacher")).password_hash == "local-hash"
    source_engine.dispose()
    target_engine.dispose()


def test_import_preserves_existing_records_and_skips_conflicting_open_session():
    source_engine, target_engine = create_engine("sqlite:///:memory:"), create_engine("sqlite:///:memory:")
    Base.metadata.create_all(source_engine)
    Base.metadata.create_all(target_engine)
    with sessionmaker(bind=source_engine, expire_on_commit=False)() as source, sessionmaker(bind=target_engine, expire_on_commit=False)() as target:
        seed_demo_data(source)
        seed_demo_data(target)
        student = target.scalar(select(Student).where(Student.student_code == "DEMO001"))
        student.full_name = "Tên đã sửa trên máy đích"
        target.commit()
        result = import_metadata(target, export_metadata(source))
        assert result["skipped_open_sessions"] == 2
        assert target.get(Student, student.id).full_name == "Tên đã sửa trên máy đích"
    source_engine.dispose()
    target_engine.dispose()
