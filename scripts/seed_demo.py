"""Create clearly marked sample data without altering existing records or adding faces."""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.database import SessionLocal, create_all
from backend.app.models import (AttendanceRecord, AuditLog, Class, ClassEnrollment, ClassSession,
                                ConsentStatus, DeviceClassAccess, FaceTemplate, Student, User, UserRole)
from backend.app.security import hash_password


DEMO_STUDENTS = [
    ("DEMO001", "Nguyễn Minh An"), ("DEMO002", "Trần Ngọc Bình"),
    ("DEMO003", "Lê Hoàng Chi"), ("DEMO004", "Phạm Gia Duy"),
    ("DEMO005", "Võ Thanh Hà"), ("DEMO006", "Đỗ Anh Khoa"),
    ("DEMO007", "Bùi Khánh Linh"), ("DEMO008", "Đặng Quốc Nam"),
    ("DEMO009", "Ngô Bảo Ngọc"), ("DEMO010", "Dương Minh Phúc"),
    ("DEMO011", "Hồ Trúc Quỳnh"), ("DEMO012", "Trịnh Gia Tú"),
]
DEMO_CLASSES = [
    ("DEMO-IMG01", "[DEMO] Xử lý ảnh", range(0, 8), True),
    ("DEMO-CV02", "[DEMO] Thị giác máy tính", range(4, 12), True),
    ("DEMO-DB03", "[DEMO] Cơ sở dữ liệu", range(0, 6), False),
]


def _marker(db, entity_type, entity_id):
    return db.scalar(select(AuditLog).where(AuditLog.action == "demo.seed",
                                            AuditLog.entity_type == entity_type,
                                            AuditLog.entity_id == str(entity_id)))


def _mark(db, entity_type, entity_id):
    db.add(AuditLog(action="demo.seed", entity_type=entity_type, entity_id=str(entity_id),
                    after_json='{"note":"Du lieu gia lap, khong phai ket qua nhan dien"}'))


def seed_demo_data(db, *, now=None):
    """Idempotently add examples; never overwrite users, templates or attendance."""
    now = now or datetime.now(timezone.utc)
    accounts = {}
    for username, password, role, name in (("admin", "admin123", UserRole.ADMIN, "Demo Admin"),
                                           ("teacher", "teacher123", UserRole.TEACHER, "Demo Teacher"),
                                           ("device01", "device123", UserRole.USER, "Attendance Device 01")):
        account = db.scalar(select(User).where(User.username == username))
        if account is None:
            account = User(username=username, password_hash=hash_password(password), role=role.value, full_name=name)
            db.add(account)
            db.flush()
        accounts[username] = account

    students = {}
    for index, (code, name) in enumerate(DEMO_STUDENTS):
        student = db.scalar(select(Student).where(Student.student_code == code))
        if student is None:
            student = Student(student_code=code, full_name=name, class_label="[DEMO] D22",
                              consent_status=ConsentStatus.PENDING.value if index == 11 else ConsentStatus.GRANTED.value)
            db.add(student)
            db.flush()
            _mark(db, "demo_student", code)
        elif not _marker(db, "demo_student", code):
            # A non-demo record happens to use the same code: do not modify or enroll it.
            continue
        if student.deleted_at is None:
            students[index] = student

    for code, name, indexes, create_open in DEMO_CLASSES:
        class_ = db.scalar(select(Class).where(Class.code == code))
        if class_ is None:
            class_ = Class(code=code, name=name, teacher_id=accounts["teacher"].id,
                           teacher_display_name="Giảng viên demo", term="[DEMO] Học kỳ mẫu")
            db.add(class_)
            db.flush()
            _mark(db, "demo_class", code)
        elif not _marker(db, "demo_class", code):
            continue
        members = [students[index] for index in indexes if index in students]
        for student in members:
            if db.scalar(select(ClassEnrollment.id).where(ClassEnrollment.class_id == class_.id,
                                                           ClassEnrollment.student_id == student.id)) is None:
                db.add(ClassEnrollment(class_id=class_.id, student_id=student.id))
        if db.get(DeviceClassAccess, (accounts["device01"].id, class_.id)) is None:
            db.add(DeviceClassAccess(user_id=accounts["device01"].id, class_id=class_.id))

        if not _marker(db, "demo_history", code):
            start = datetime(2025, 5, 20, 0, 0, tzinfo=timezone.utc)
            history = ClassSession(class_id=class_.id, opened_by=accounts["teacher"].id,
                                   start_time=start, expected_start_time=start, planned_end_time=start + timedelta(hours=2),
                                   end_time=start + timedelta(hours=2), late_grace_minutes=5, status="closed")
            db.add(history)
            db.flush()
            for index, student in enumerate(members):
                status = ("present", "late", "absent")[index % 3]
                minutes = 12 if status == "late" else 0
                db.add(AttendanceRecord(session_id=history.id, student_id=student.id, status=status,
                                        source="manual", recorded_at=start + timedelta(minutes=minutes + 5 if minutes else 0),
                                        late_minutes=minutes, updated_by=accounts["teacher"].id))
            _mark(db, "demo_history", code)
        if create_open and not _marker(db, "demo_open", code):
            existing = db.scalar(select(ClassSession.id).where(ClassSession.class_id == class_.id,
                                                               ClassSession.status == "open"))
            if existing is None:
                expected = now - timedelta(minutes=30)
                current = ClassSession(class_id=class_.id, opened_by=accounts["teacher"].id,
                                       start_time=expected, expected_start_time=expected,
                                       planned_end_time=expected + timedelta(hours=2), late_grace_minutes=5, status="open")
                db.add(current)
                db.flush()
                for index, student in enumerate(members[:2]):
                    minutes = 12 if index == 1 else 0
                    db.add(AttendanceRecord(session_id=current.id, student_id=student.id,
                        status="late" if minutes else "present", source="manual",
                        recorded_at=expected + timedelta(minutes=minutes + 5 if minutes else 0),
                        late_minutes=minutes, updated_by=accounts["teacher"].id))
                _mark(db, "demo_open", code)
    db.commit()


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    create_all()
    with SessionLocal() as db:
        seed_demo_data(db)
        templates = db.scalar(select(FaceTemplate.id).limit(1))
    print("Đã kiểm tra và bổ sung dữ liệu giả lập [DEMO]. Mã trùng dữ liệu khác được bỏ qua.")
    print("Bản ghi điểm danh lịch sử là dữ liệu giả lập nhập thủ công; không tạo ảnh hoặc vector Face ID.")
    print("Tài khoản demo mới: admin/admin123, teacher/teacher123, device01/device123; tài khoản cũ giữ nguyên.")
    if templates is not None:
        print("Các mẫu Face ID sẵn có trong cơ sở dữ liệu vẫn được giữ nguyên.")


if __name__ == "__main__":
    main()
