"""Export/import class and attendance metadata without passwords or biometric data."""

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.database import SessionLocal, create_all
from backend.app.models import AttendanceRecord, AuditLog, Class, ClassEnrollment, ClassSession, Student, User


def _time(value):
    if value is None:
        return None
    return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)).isoformat()


def _parse_time(value):
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def export_metadata(db):
    students = db.scalars(select(Student).where(Student.deleted_at.is_(None))).all()
    student_by_id = {student.id: student for student in students}
    classes = db.scalars(select(Class)).all()
    class_by_id = {class_.id: class_ for class_ in classes}
    sessions = db.scalars(select(ClassSession)).all()
    session_by_id = {session.id: session for session in sessions}
    return {
        "format": "face-attendance-metadata-v1",
        "description": "Metadata only; no face images, embeddings, passwords, session tokens, or evidence files.",
        "students": [{"code": s.student_code, "name": s.full_name, "class_label": s.class_label,
                      "consent_status": s.consent_status} for s in students],
        "classes": [{"code": c.code, "name": c.name, "teacher_username": c.teacher.username,
                     "teacher_display_name": c.teacher_display_name, "term": c.term} for c in classes],
        "enrollments": [{"class_code": class_by_id[e.class_id].code, "student_code": student_by_id[e.student_id].student_code}
                        for e in db.scalars(select(ClassEnrollment))
                        if e.class_id in class_by_id and e.student_id in student_by_id],
        "sessions": [{"source_id": s.id, "class_code": class_by_id[s.class_id].code,
                      "start_time": _time(s.start_time), "expected_start_time": _time(s.expected_start_time),
                      "planned_end_time": _time(s.planned_end_time), "end_time": _time(s.end_time),
                      "late_grace_minutes": s.late_grace_minutes, "status": s.status}
                     for s in sessions if s.class_id in class_by_id],
        "attendance": [{"session_source_id": a.session_id, "student_code": student_by_id[a.student_id].student_code,
                        "status": a.status, "source": a.source, "recorded_at": _time(a.recorded_at),
                        "late_minutes": a.late_minutes}
                       for a in db.scalars(select(AttendanceRecord))
                       if a.session_id in session_by_id and a.student_id in student_by_id],
    }


def import_metadata(db, data, *, fallback_teacher="teacher"):
    if data.get("format") != "face-attendance-metadata-v1":
        raise ValueError("Unsupported metadata format")
    teacher = db.scalar(select(User).where(User.username == fallback_teacher, User.role.in_(("teacher", "admin")),
                                           User.is_active.is_(True)))
    if teacher is None:
        raise ValueError("Fallback teacher account not found; run seed_demo first or supply --teacher")
    students, classes, sessions = {}, {}, {}
    for item in data["students"]:
        student = db.scalar(select(Student).where(Student.student_code == item["code"]))
        if student is None:
            student = Student(student_code=item["code"], full_name=item["name"],
                              class_label=item.get("class_label"), consent_status=item["consent_status"])
            db.add(student)
            db.flush()
        if student.deleted_at is None:
            students[item["code"]] = student
    for item in data["classes"]:
        class_ = db.scalar(select(Class).where(Class.code == item["code"]))
        if class_ is None:
            owner = db.scalar(select(User).where(User.username == item["teacher_username"],
                                                 User.role.in_(("teacher", "admin")), User.is_active.is_(True))) or teacher
            class_ = Class(code=item["code"], name=item["name"], teacher_id=owner.id,
                           teacher_display_name=item.get("teacher_display_name"), term=item.get("term"))
            db.add(class_)
            db.flush()
        classes[item["code"]] = class_
    for item in data["enrollments"]:
        class_, student = classes.get(item["class_code"]), students.get(item["student_code"])
        if class_ is None or student is None:
            continue
        if db.scalar(select(ClassEnrollment.id).where(ClassEnrollment.class_id == class_.id,
                                                       ClassEnrollment.student_id == student.id)) is None:
            db.add(ClassEnrollment(class_id=class_.id, student_id=student.id))
            db.flush()
    skipped_open = 0
    for item in data["sessions"]:
        class_ = classes[item["class_code"]]
        identity = json.dumps([item["class_code"], item["source_id"], item["start_time"]], separators=(",", ":"))
        key = hashlib.sha256(identity.encode()).hexdigest()
        marker = db.scalar(select(AuditLog).where(AuditLog.action == "portable.import",
                                                   AuditLog.entity_type == "session", AuditLog.entity_id == key))
        if marker:
            sessions[item["source_id"]] = db.get(ClassSession, json.loads(marker.after_json)["session_id"])
            continue
        if item["status"] == "open" and db.scalar(select(ClassSession.id).where(
                ClassSession.class_id == class_.id, ClassSession.status == "open")) is not None:
            skipped_open += 1
            continue
        session = ClassSession(class_id=class_.id, opened_by=teacher.id, start_time=_parse_time(item["start_time"]),
                               expected_start_time=_parse_time(item.get("expected_start_time")),
                               planned_end_time=_parse_time(item.get("planned_end_time")), end_time=_parse_time(item.get("end_time")),
                               late_grace_minutes=item["late_grace_minutes"], status=item["status"])
        db.add(session)
        db.flush()
        db.add(AuditLog(action="portable.import", entity_type="session", entity_id=key,
                        after_json=json.dumps({"session_id": session.id})))
        db.flush()
        sessions[item["source_id"]] = session
    for item in data["attendance"]:
        session, student = sessions.get(item["session_source_id"]), students.get(item["student_code"])
        if session is None or student is None:
            continue
        if db.scalar(select(AttendanceRecord.id).where(AttendanceRecord.session_id == session.id,
                                                       AttendanceRecord.student_id == student.id)) is None:
            db.add(AttendanceRecord(session_id=session.id, student_id=student.id, status=item["status"],
                                    source=item["source"], recorded_at=_parse_time(item["recorded_at"]),
                                    late_minutes=item["late_minutes"], recognized_event_id=None, evidence_image_path=None))
            db.flush()
    db.commit()
    return {"students": len(students), "classes": len(classes), "sessions": len(sessions), "skipped_open_sessions": skipped_open}


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("export", "import"))
    parser.add_argument("path", type=Path, help="JSON file to write/read")
    parser.add_argument("--teacher", default="teacher", help="Existing fallback teacher username when importing")
    args = parser.parse_args()
    if args.action == "import":
        create_all()
    with SessionLocal() as db:
        if args.action == "export":
            if args.path.exists():
                parser.error("Output already exists; choose a new path to avoid overwriting data")
            args.path.parent.mkdir(parents=True, exist_ok=True)
            args.path.write_text(json.dumps(export_metadata(db), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"Exported metadata to {args.path}; no biometric data, passwords or tokens.")
        else:
            result = import_metadata(db, json.loads(args.path.read_text(encoding="utf-8")), fallback_teacher=args.teacher)
            print(f"Imported: {result}. Existing records are not overwritten.")


if __name__ == "__main__":
    main()
