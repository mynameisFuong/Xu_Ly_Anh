import sys
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.database import SessionLocal, create_all
from backend.app.models import Class, ClassEnrollment, ConsentStatus, Student, User, UserRole
from backend.app.security import hash_password


def main() -> None:
    create_all()
    db = SessionLocal()
    try:
        admin = db.scalar(select(User).where(User.username == "admin"))
        if admin is None:
            admin = User(
                username="admin",
                password_hash=hash_password("admin123"),
                role=UserRole.ADMIN.value,
                full_name="Demo Admin",
            )
            db.add(admin)
            db.flush()

        teacher = db.scalar(select(User).where(User.username == "teacher"))
        if teacher is None:
            teacher = User(
                username="teacher",
                password_hash=hash_password("teacher123"),
                role=UserRole.TEACHER.value,
                full_name="Demo Teacher",
            )
            db.add(teacher)
            db.flush()

        class_ = db.scalar(select(Class).where(Class.code == "IMG101"))
        if class_ is None:
            class_ = Class(code="IMG101", name="Xu Ly Anh", teacher_id=teacher.id, term="2026A")
            db.add(class_)
            db.flush()

        for index in range(1, 6):
            code = f"SV{index:03d}"
            student = db.scalar(select(Student).where(Student.student_code == code))
            if student is None:
                student = Student(
                    student_code=code,
                    full_name=f"Sinh Vien {index}",
                    class_label="KTPM",
                    consent_status=ConsentStatus.GRANTED.value,
                )
                db.add(student)
                db.flush()
            exists = db.scalar(
                select(ClassEnrollment).where(
                    ClassEnrollment.class_id == class_.id,
                    ClassEnrollment.student_id == student.id,
                )
            )
            if exists is None:
                db.add(ClassEnrollment(class_id=class_.id, student_id=student.id))

        db.commit()
        print("Seeded demo data.")
        print("Admin: username=admin password=admin123 header X-User-Id=1")
        print("Teacher: username=teacher password=teacher123")
    finally:
        db.close()


if __name__ == "__main__":
    main()
