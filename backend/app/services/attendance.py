from datetime import datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.models import (
    AttendanceRecord,
    AttendanceSource,
    AttendanceStatus,
    ClassEnrollment,
    ClassSession,
    RecognitionDecision,
    RecognitionEvent,
    SessionStatus,
    Student,
    utc_now,
)
from backend.app.schemas import AttendanceManualUpdate, RecognitionEventCreate
from backend.app.services.audit import write_audit


def _get_open_session(db: Session, session_id: int) -> ClassSession:
    class_session = db.get(ClassSession, session_id)
    if class_session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    if class_session.status != SessionStatus.OPEN.value:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Session is not open")
    return class_session


def _ensure_comparable(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=utc_now().tzinfo)
    return value


def calculate_late_minutes(class_session: ClassSession, recorded_at: datetime) -> int:
    if class_session.expected_start_time is None:
        return 0
    expected = _ensure_comparable(class_session.expected_start_time) + timedelta(
        minutes=class_session.late_grace_minutes
    )
    actual = _ensure_comparable(recorded_at)
    if actual <= expected:
        return 0
    delta_seconds = (actual - expected).total_seconds()
    return int((delta_seconds + 59) // 60)


def create_recognition_event(
    db: Session,
    *,
    session_id: int,
    payload: RecognitionEventCreate,
) -> tuple[RecognitionEvent, AttendanceRecord | None]:
    class_session = _get_open_session(db, session_id)

    existing_event = db.scalar(
        select(RecognitionEvent).where(RecognitionEvent.idempotency_key == payload.idempotency_key)
    )
    if existing_event is not None:
        attendance = db.scalar(
            select(AttendanceRecord).where(AttendanceRecord.recognized_event_id == existing_event.id)
        )
        return existing_event, attendance

    event = RecognitionEvent(
        session_id=session_id,
        camera_id=payload.camera_id,
        student_id=payload.student_id,
        candidate_score=payload.candidate_score,
        second_score=payload.second_score,
        decision=payload.decision,
        frame_time=payload.frame_time or utc_now(),
        model_version=payload.model_version,
        idempotency_key=payload.idempotency_key,
    )
    db.add(event)
    db.flush()

    attendance = None
    if payload.decision == RecognitionDecision.RECOGNIZED.value and payload.student_id is not None:
        enrollment = db.scalar(
            select(ClassEnrollment).where(
                ClassEnrollment.class_id == class_session.class_id,
                ClassEnrollment.student_id == payload.student_id,
            )
        )
        if enrollment is None:
            event.decision = RecognitionDecision.LOW_CONFIDENCE.value
        else:
            attendance = _create_auto_attendance(db, event)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing_event = db.scalar(
            select(RecognitionEvent).where(RecognitionEvent.idempotency_key == payload.idempotency_key)
        )
        if existing_event is None:
            raise
        attendance = db.scalar(
            select(AttendanceRecord).where(
                AttendanceRecord.session_id == session_id,
                AttendanceRecord.student_id == existing_event.student_id,
            )
        )
        return existing_event, attendance

    db.refresh(event)
    if attendance is not None:
        db.refresh(attendance)
    return event, attendance


def _create_auto_attendance(db: Session, event: RecognitionEvent) -> AttendanceRecord:
    existing = db.scalar(
        select(AttendanceRecord).where(
            AttendanceRecord.session_id == event.session_id,
            AttendanceRecord.student_id == event.student_id,
        )
    )
    if existing is not None:
        return existing

    class_session = db.get(ClassSession, event.session_id)
    recorded_at = utc_now()
    late_minutes = calculate_late_minutes(class_session, recorded_at) if class_session is not None else 0
    attendance = AttendanceRecord(
        session_id=event.session_id,
        student_id=event.student_id,
        status=AttendanceStatus.LATE.value if late_minutes > 0 else AttendanceStatus.PRESENT.value,
        source=AttendanceSource.AUTO.value,
        recognized_event_id=event.id,
        recorded_at=recorded_at,
        late_minutes=late_minutes,
    )
    db.add(attendance)
    return attendance


def update_attendance_manually(
    db: Session,
    *,
    session_id: int,
    student_id: int,
    actor_user_id: int,
    payload: AttendanceManualUpdate,
) -> AttendanceRecord:
    class_session = db.get(ClassSession, session_id)
    if class_session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")

    enrollment = db.scalar(
        select(ClassEnrollment).where(
            ClassEnrollment.class_id == class_session.class_id,
            ClassEnrollment.student_id == student_id,
        )
    )
    if enrollment is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Student is not enrolled in this class")

    attendance = db.scalar(
        select(AttendanceRecord).where(
            AttendanceRecord.session_id == session_id,
            AttendanceRecord.student_id == student_id,
        )
    )
    before = None
    if attendance is None:
        attendance = AttendanceRecord(
            session_id=session_id,
            student_id=student_id,
            status=payload.status,
            source=AttendanceSource.MANUAL.value,
            recorded_at=utc_now(),
            late_minutes=0,
            updated_by=actor_user_id,
        )
        db.add(attendance)
    else:
        before = {
            "status": attendance.status,
            "source": attendance.source,
            "updated_by": attendance.updated_by,
        }
        attendance.status = payload.status
        attendance.source = AttendanceSource.MANUAL.value
        attendance.late_minutes = 0 if payload.status != AttendanceStatus.LATE.value else attendance.late_minutes
        attendance.updated_by = actor_user_id

    db.flush()
    write_audit(
        db,
        actor_user_id=actor_user_id,
        action="attendance.manual_update",
        entity_type="AttendanceRecord",
        entity_id=attendance.id,
        before=before,
        after={"status": attendance.status, "reason": payload.reason},
    )
    db.commit()
    db.refresh(attendance)
    return attendance


def close_session(db: Session, *, session_id: int, actor_user_id: int) -> ClassSession:
    class_session = _get_open_session(db, session_id)

    enrolled_student_ids = db.scalars(
        select(ClassEnrollment.student_id).where(ClassEnrollment.class_id == class_session.class_id)
    ).all()
    existing_student_ids = set(
        db.scalars(select(AttendanceRecord.student_id).where(AttendanceRecord.session_id == session_id)).all()
    )

    for student_id in enrolled_student_ids:
        if student_id not in existing_student_ids:
            db.add(
                AttendanceRecord(
                    session_id=session_id,
                    student_id=student_id,
                    status=AttendanceStatus.ABSENT.value,
                    source=AttendanceSource.MANUAL.value,
                    recorded_at=utc_now(),
                    late_minutes=0,
                    updated_by=actor_user_id,
                )
            )

    class_session.status = SessionStatus.CLOSED.value
    class_session.end_time = utc_now()
    write_audit(
        db,
        actor_user_id=actor_user_id,
        action="session.close",
        entity_type="ClassSession",
        entity_id=session_id,
        after={"closed_at": class_session.end_time.isoformat()},
    )
    db.commit()
    db.refresh(class_session)
    return class_session


def open_session(
    db: Session,
    *,
    class_id: int,
    opened_by: int,
    start_time: datetime | None = None,
    expected_start_time: datetime | None = None,
    late_grace_minutes: int = 0,
) -> ClassSession:
    existing_open = db.scalar(
        select(ClassSession).where(
            ClassSession.class_id == class_id,
            ClassSession.status == SessionStatus.OPEN.value,
        )
    )
    if existing_open is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Class already has an open session")

    class_session = ClassSession(
        class_id=class_id,
        opened_by=opened_by,
        start_time=start_time or utc_now(),
        expected_start_time=expected_start_time,
        late_grace_minutes=late_grace_minutes,
        status=SessionStatus.OPEN.value,
    )
    db.add(class_session)
    db.commit()
    db.refresh(class_session)
    return class_session
