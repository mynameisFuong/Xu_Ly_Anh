import csv
import base64
import uuid
from io import BytesIO, StringIO
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.database import get_db
from backend.app.models import (
    AttendanceRecord,
    Class,
    ClassEnrollment,
    ClassSession,
    ConsentStatus,
    FaceTemplate,
    SessionStatus,
    Student,
    User,
    utc_now,
)
from backend.app.schemas import (
    AttendanceManualUpdate,
    AttendanceBoardRead,
    AttendanceBoardRow,
    AttendanceRead,
    AttendanceRequestCreate,
    AttendanceRequestRead,
    AttendanceStatsRead,
    ClassCreate,
    ClassRead,
    FaceImportItem,
    FaceImportResponse,
    FaceTemplateRead,
    FrameScanRequest,
    FrameScanResponse,
    RecognitionEventCreate,
    RecognitionEventRead,
    SessionCreate,
    SessionPolicyUpdate,
    SessionRead,
    StudentFaceSummary,
    StudentCreate,
    StudentRead,
    StudentUpdate,
    UserCreate,
    UserRead,
)
from backend.app.security import (
    get_current_user,
    hash_password,
    require_admin,
    require_teacher_or_admin,
    require_user_or_admin,
    verify_camera_token,
    verify_password,
)
from backend.app.services.attendance import (
    calculate_late_minutes,
    close_session,
    create_recognition_event,
    open_session,
    update_attendance_manually,
)
from backend.app.services.face_templates import build_default_recognizer, register_face_bytes, register_face_image

router = APIRouter()


def _attendance_evidence_url(attendance: AttendanceRecord | None) -> str | None:
    if attendance is None or attendance.evidence_image_path is None:
        return None
    return f"/attendance/{attendance.id}/evidence"


def _save_attendance_evidence(
    db: Session,
    *,
    attendance: AttendanceRecord | None,
    image_bytes: bytes,
) -> None:
    if attendance is None or attendance.evidence_image_path is not None:
        return

    storage_dir = get_settings().storage_dir / "attendance_evidence" / f"session-{attendance.session_id}"
    storage_dir.mkdir(parents=True, exist_ok=True)
    image_path = storage_dir / f"attendance-{attendance.id}-student-{attendance.student_id}.jpg"
    image_path.write_bytes(image_bytes)
    attendance.evidence_image_path = str(image_path)
    db.commit()
    db.refresh(attendance)


def _build_attendance_board(db: Session, class_session: ClassSession) -> AttendanceBoardRead:
    rows = db.execute(
        select(Student, AttendanceRecord)
        .join(ClassEnrollment, ClassEnrollment.student_id == Student.id)
        .outerjoin(
            AttendanceRecord,
            (AttendanceRecord.student_id == Student.id) & (AttendanceRecord.session_id == class_session.id),
        )
        .where(ClassEnrollment.class_id == class_session.class_id)
        .where(Student.deleted_at.is_(None))
        .order_by(Student.student_code)
    ).all()
    board_rows: list[AttendanceBoardRow] = []
    for student, attendance in rows:
        if attendance is None:
            board_rows.append(
                AttendanceBoardRow(
                    student_id=student.id,
                    student_code=student.student_code,
                    full_name=student.full_name,
                    class_label=student.class_label,
                    status="pending",
                    source=None,
                    recorded_at=None,
                    late_minutes=0,
                    alert="Chua diem danh",
                )
            )
            continue

        if attendance.status == "late":
            alert = f"Tre {attendance.late_minutes} phut"
        elif attendance.status == "present":
            alert = "Dung gio"
        elif attendance.status == "absent":
            alert = "Vang"
        else:
            alert = attendance.status
        board_rows.append(
            AttendanceBoardRow(
                student_id=student.id,
                student_code=student.student_code,
                full_name=student.full_name,
                class_label=student.class_label,
                status=attendance.status,
                source=attendance.source,
                recorded_at=attendance.recorded_at,
                late_minutes=attendance.late_minutes,
                alert=alert,
                evidence_image_url=_attendance_evidence_url(attendance),
            )
        )

    return AttendanceBoardRead(
        session_id=class_session.id,
        class_id=class_session.class_id,
        expected_start_time=class_session.expected_start_time,
        late_grace_minutes=class_session.late_grace_minutes,
        rows=board_rows,
    )


def _attendance_stats_from_board(board: AttendanceBoardRead) -> AttendanceStatsRead:
    total = len(board.rows)
    present_count = sum(1 for row in board.rows if row.status == "present")
    late_count = sum(1 for row in board.rows if row.status == "late")
    absent_count = sum(1 for row in board.rows if row.status == "absent")
    pending_count = sum(1 for row in board.rows if row.status == "pending")

    def rate(count: int) -> float:
        return round(count * 100 / total, 2) if total else 0.0

    return AttendanceStatsRead(
        session_id=board.session_id,
        class_id=board.class_id,
        total_students=total,
        present_count=present_count,
        late_count=late_count,
        absent_count=absent_count,
        pending_count=pending_count,
        present_rate=rate(present_count),
        late_rate=rate(late_count),
        absent_rate=rate(absent_count),
    )


def _attendance_request_read(db: Session, class_session: ClassSession) -> AttendanceRequestRead:
    class_ = db.get(Class, class_session.class_id)
    student_count = db.scalar(
        select(func.count(ClassEnrollment.id)).where(ClassEnrollment.class_id == class_session.class_id)
    )
    return AttendanceRequestRead(
        session_id=class_session.id,
        class_id=class_session.class_id,
        class_code=class_.code if class_ is not None else "",
        class_name=class_.name if class_ is not None else "",
        teacher_name=class_.teacher_display_name if class_ is not None else None,
        expected_start_time=class_session.expected_start_time,
        planned_end_time=class_session.planned_end_time,
        late_grace_minutes=class_session.late_grace_minutes,
        status=class_session.status,
        student_count=student_count or 0,
    )


@router.get("/demo", include_in_schema=False)
def demo_page() -> FileResponse:
    path = Path(__file__).resolve().parents[2] / "frontend" / "demo.html"
    return FileResponse(path)


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/auth/login")
def login(username: str, password: str, db: Session = Depends(get_db)) -> dict[str, int | str]:
    user = db.scalar(select(User).where(User.username == username))
    if user is None or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    return {"user_id": user.id, "role": user.role, "full_name": user.full_name}


@router.post("/users", response_model=UserRead, dependencies=[Depends(require_admin)])
def create_user(payload: UserCreate, db: Session = Depends(get_db)) -> User:
    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        role=payload.role,
        full_name=payload.full_name,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists") from exc
    db.refresh(user)
    return user


@router.post("/students", response_model=StudentRead, dependencies=[Depends(require_teacher_or_admin)])
def create_student(payload: StudentCreate, db: Session = Depends(get_db)) -> Student:
    student = Student(**payload.model_dump())
    db.add(student)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Student code already exists") from exc
    db.refresh(student)
    return student


@router.get("/students", response_model=list[StudentRead], dependencies=[Depends(require_teacher_or_admin)])
def list_students(db: Session = Depends(get_db)) -> list[Student]:
    return list(db.scalars(select(Student).where(Student.deleted_at.is_(None))).all())


@router.patch("/students/{student_id}", response_model=StudentRead)
def update_student(
    student_id: int,
    payload: StudentUpdate,
    _user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Student:
    student = db.get(Student, student_id)
    if student is None or student.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")

    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(student, field, value)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Student code already exists") from exc
    db.refresh(student)
    return student


@router.delete("/students/{student_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_student(
    student_id: int,
    _user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Response:
    student = db.get(Student, student_id)
    if student is None or student.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")

    student.deleted_at = utc_now()
    db.query(FaceTemplate).filter(FaceTemplate.student_id == student_id).update({"is_active": False})
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/admin/students/faces", response_model=list[StudentFaceSummary])
def list_students_with_faces(
    _user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[StudentFaceSummary]:
    students = db.scalars(select(Student).where(Student.deleted_at.is_(None)).order_by(Student.student_code)).all()
    summaries: list[StudentFaceSummary] = []
    for student in students:
        templates = db.scalars(
            select(FaceTemplate)
            .where(FaceTemplate.student_id == student.id, FaceTemplate.is_active.is_(True))
            .order_by(FaceTemplate.created_at.desc())
        ).all()
        latest = templates[0] if templates else None
        summaries.append(
            StudentFaceSummary(
                id=student.id,
                student_code=student.student_code,
                full_name=student.full_name,
                class_label=student.class_label,
                consent_status=student.consent_status,
                face_template_count=len(templates),
                latest_image_path=latest.image_path if latest is not None else None,
                latest_image_url=f"/admin/face-templates/{latest.id}/image" if latest is not None else None,
            )
        )
    return summaries


@router.get("/admin/face-templates/{template_id}/image")
def get_face_template_image(
    template_id: int,
    _user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> FileResponse:
    template = db.get(FaceTemplate, template_id)
    if template is None or template.image_path is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Face image not found")
    image_path = Path(template.image_path)
    if not image_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Face image file missing")
    return FileResponse(image_path)


@router.get("/classes", response_model=list[ClassRead], dependencies=[Depends(require_teacher_or_admin)])
def list_classes(db: Session = Depends(get_db)) -> list[Class]:
    return list(db.scalars(select(Class)).all())


@router.post("/classes", response_model=ClassRead, dependencies=[Depends(require_teacher_or_admin)])
def create_class(payload: ClassCreate, db: Session = Depends(get_db)) -> Class:
    class_ = Class(**payload.model_dump())
    db.add(class_)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Class code already exists") from exc
    db.refresh(class_)
    return class_


@router.post(
    "/classes/{class_id}/enrollments/{student_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_teacher_or_admin)],
)
def enroll_student(class_id: int, student_id: int, db: Session = Depends(get_db)) -> Response:
    if db.get(Class, class_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Class not found")
    if db.get(Student, student_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")

    db.add(ClassEnrollment(class_id=class_id, student_id=student_id))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/classes/{class_id}/sessions", response_model=SessionRead)
def open_class_session(
    class_id: int,
    payload: SessionCreate,
    user: User = Depends(require_teacher_or_admin),
    db: Session = Depends(get_db),
) -> ClassSession:
    if db.get(Class, class_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Class not found")
    return open_session(
        db,
        class_id=class_id,
        opened_by=user.id,
        start_time=payload.start_time,
        expected_start_time=payload.expected_start_time,
        planned_end_time=payload.planned_end_time,
        late_grace_minutes=payload.late_grace_minutes,
    )


@router.post("/attendance-requests", response_model=AttendanceRequestRead)
def create_attendance_request(
    payload: AttendanceRequestCreate,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AttendanceRequestRead:
    class_ = db.scalar(select(Class).where(Class.code == payload.class_code))
    if class_ is None:
        class_ = Class(
            code=payload.class_code,
            name=payload.class_name,
            teacher_id=user.id,
            teacher_display_name=payload.teacher_name,
        )
        db.add(class_)
        db.flush()
    else:
        class_.name = payload.class_name
        class_.teacher_display_name = payload.teacher_name

    for item in payload.students:
        student = db.scalar(select(Student).where(Student.student_code == item.student_code))
        if student is None:
            student = Student(
                student_code=item.student_code,
                full_name=item.full_name,
                class_label=item.class_label or payload.class_code,
                consent_status=ConsentStatus.GRANTED.value,
            )
            db.add(student)
            db.flush()
        else:
            student.full_name = item.full_name
            student.class_label = item.class_label or student.class_label
            if student.consent_status == "pending":
                student.consent_status = ConsentStatus.GRANTED.value

        enrollment = db.scalar(
            select(ClassEnrollment).where(
                ClassEnrollment.class_id == class_.id,
                ClassEnrollment.student_id == student.id,
            )
        )
        if enrollment is None:
            db.add(ClassEnrollment(class_id=class_.id, student_id=student.id))

    existing_open_session = db.scalar(
        select(ClassSession).where(
            ClassSession.class_id == class_.id,
            ClassSession.status == SessionStatus.OPEN.value,
        )
    )
    if existing_open_session is not None:
        existing_open_session.expected_start_time = payload.expected_start_time
        existing_open_session.planned_end_time = payload.planned_end_time
        existing_open_session.late_grace_minutes = payload.late_grace_minutes
        db.commit()
        db.refresh(existing_open_session)
        return _attendance_request_read(db, existing_open_session)

    db.commit()
    class_session = open_session(
        db,
        class_id=class_.id,
        opened_by=user.id,
        expected_start_time=payload.expected_start_time,
        planned_end_time=payload.planned_end_time,
        late_grace_minutes=payload.late_grace_minutes,
    )
    return _attendance_request_read(db, class_session)


@router.get("/attendance-requests/open", response_model=list[AttendanceRequestRead])
def list_open_attendance_requests(
    _user: User = Depends(require_user_or_admin),
    db: Session = Depends(get_db),
) -> list[AttendanceRequestRead]:
    sessions = db.scalars(
        select(ClassSession)
        .where(ClassSession.status == SessionStatus.OPEN.value)
        .order_by(ClassSession.start_time.desc())
    ).all()
    return [_attendance_request_read(db, item) for item in sessions]


@router.post("/sessions/{session_id}/close", response_model=SessionRead)
def close_class_session(
    session_id: int,
    user: User = Depends(require_teacher_or_admin),
    db: Session = Depends(get_db),
) -> ClassSession:
    return close_session(db, session_id=session_id, actor_user_id=user.id)


@router.put("/sessions/{session_id}/policy", response_model=SessionRead)
def update_session_policy(
    session_id: int,
    payload: SessionPolicyUpdate,
    _user: User = Depends(require_teacher_or_admin),
    db: Session = Depends(get_db),
) -> ClassSession:
    class_session = db.get(ClassSession, session_id)
    if class_session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    class_session.expected_start_time = payload.expected_start_time
    class_session.late_grace_minutes = payload.late_grace_minutes
    db.commit()
    db.refresh(class_session)
    return class_session


@router.post(
    "/sessions/{session_id}/recognition-events",
    response_model=RecognitionEventRead,
    dependencies=[Depends(verify_camera_token)],
)
def add_recognition_event(
    session_id: int,
    payload: RecognitionEventCreate,
    db: Session = Depends(get_db),
):
    event, _attendance = create_recognition_event(db, session_id=session_id, payload=payload)
    return event


@router.get("/sessions/{session_id}/attendance", response_model=list[AttendanceRead])
def list_attendance(
    session_id: int,
    _user: User = Depends(require_teacher_or_admin),
    db: Session = Depends(get_db),
) -> list[AttendanceRecord]:
    return list(db.scalars(select(AttendanceRecord).where(AttendanceRecord.session_id == session_id)).all())


@router.get("/sessions/{session_id}/attendance-board", response_model=AttendanceBoardRead)
def attendance_board(
    session_id: int,
    _user: User = Depends(require_user_or_admin),
    db: Session = Depends(get_db),
) -> AttendanceBoardRead:
    class_session = db.get(ClassSession, session_id)
    if class_session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return _build_attendance_board(db, class_session)


@router.get("/sessions/{session_id}/attendance-stats", response_model=AttendanceStatsRead)
def attendance_stats(
    session_id: int,
    _user: User = Depends(require_teacher_or_admin),
    db: Session = Depends(get_db),
) -> AttendanceStatsRead:
    class_session = db.get(ClassSession, session_id)
    if class_session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return _attendance_stats_from_board(_build_attendance_board(db, class_session))


@router.get("/attendance/{attendance_id}/evidence")
def get_attendance_evidence(
    attendance_id: int,
    _user: User = Depends(require_teacher_or_admin),
    db: Session = Depends(get_db),
) -> FileResponse:
    attendance = db.get(AttendanceRecord, attendance_id)
    if attendance is None or attendance.evidence_image_path is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attendance evidence not found")
    image_path = Path(attendance.evidence_image_path)
    if not image_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attendance evidence file missing")
    return FileResponse(image_path)


@router.post("/sessions/{session_id}/scan-frame", response_model=FrameScanResponse)
def scan_frame(
    session_id: int,
    payload: FrameScanRequest,
    _user: User = Depends(require_user_or_admin),
    db: Session = Depends(get_db),
) -> FrameScanResponse:
    class_session = db.get(ClassSession, session_id)
    if class_session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    recognizer = build_default_recognizer()
    image_base64 = payload.image_base64
    if "," in image_base64:
        image_base64 = image_base64.split(",", 1)[1]
    try:
        image_bytes = base64.b64decode(image_base64, validate=True)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid image data") from exc

    result = recognizer.extract_single_embedding(image_bytes)
    if not result.accepted:
        return FrameScanResponse(decision="unknown", message=result.reason or "Cannot extract face")

    try:
        import numpy as np
        from ai_pipeline.recognition import match_embedding
    except ModuleNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Camera recognition dependencies are not installed. Install requirements-camera.txt.",
        ) from exc

    template_rows = db.execute(
        select(FaceTemplate)
        .join(ClassEnrollment, ClassEnrollment.student_id == FaceTemplate.student_id)
        .where(
            ClassEnrollment.class_id == class_session.class_id,
            FaceTemplate.is_active.is_(True),
            FaceTemplate.model_version == recognizer.model_version,
        )
    ).scalars()
    templates: dict[int, list[np.ndarray]] = {}
    for template in template_rows:
        templates.setdefault(template.student_id, []).append(np.frombuffer(template.embedding, dtype=np.float32))

    if not templates:
        return FrameScanResponse(decision="unknown", message="No face templates registered for this class")

    settings = get_settings()
    match = match_embedding(
        result.embedding,
        templates,
        threshold=settings.attendance_threshold,
        margin=settings.attendance_margin,
    )
    if match.student_id is None:
        return FrameScanResponse(
            decision=match.decision,
            message="Face is not confident enough",
            candidate_score=match.score,
            second_score=match.second_score,
        )

    event_payload = RecognitionEventCreate(
        camera_id=payload.camera_id,
        student_id=match.student_id,
        candidate_score=match.score,
        second_score=match.second_score,
        decision=match.decision,
        model_version=recognizer.model_version,
        idempotency_key=payload.idempotency_key or str(uuid.uuid4()),
    )
    _event, attendance = create_recognition_event(db, session_id=session_id, payload=event_payload)
    _save_attendance_evidence(db, attendance=attendance, image_bytes=image_bytes)
    student = db.get(Student, match.student_id)
    message = "Dung gio"
    if attendance is not None and attendance.status == "late":
        message = f"Tre {attendance.late_minutes} phut"

    return FrameScanResponse(
        decision=match.decision,
        message=message,
        student_id=student.id if student is not None else match.student_id,
        student_code=student.student_code if student is not None else None,
        full_name=student.full_name if student is not None else None,
        class_label=student.class_label if student is not None else None,
        class_name=class_session.class_.name if class_session.class_ is not None else None,
        candidate_score=match.score,
        second_score=match.second_score,
        attendance=attendance,
    )


@router.put("/sessions/{session_id}/attendance/{student_id}", response_model=AttendanceRead)
def manual_attendance_update(
    session_id: int,
    student_id: int,
    payload: AttendanceManualUpdate,
    user: User = Depends(require_teacher_or_admin),
    db: Session = Depends(get_db),
) -> AttendanceRecord:
    return update_attendance_manually(
        db,
        session_id=session_id,
        student_id=student_id,
        actor_user_id=user.id,
        payload=payload,
    )


@router.post("/students/{student_id}/face-templates", response_model=FaceTemplateRead)
def register_face_template(
    student_id: int,
    file: UploadFile = File(...),
    _user: User = Depends(require_teacher_or_admin),
    db: Session = Depends(get_db),
) -> object:
    recognizer = build_default_recognizer()
    return register_face_image(db, student_id=student_id, file=file, recognizer=recognizer)


def _student_code_from_filename(filename: str) -> str | None:
    stem = Path(filename).stem.strip()
    if not stem:
        return None
    for separator in ("_", "-", " "):
        if separator in stem:
            stem = stem.split(separator, 1)[0]
            break
    return stem.strip() or None


@router.post("/admin/face-import", response_model=FaceImportResponse)
def import_student_faces(
    files: list[UploadFile] = File(...),
    class_id: int | None = None,
    _user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> FaceImportResponse:
    recognizer = build_default_recognizer()
    items: list[FaceImportItem] = []
    imported = 0

    for file in files:
        filename = file.filename or "unknown.jpg"
        student_code = _student_code_from_filename(filename)
        if student_code is None:
            items.append(FaceImportItem(filename=filename, status="failed", detail="Cannot parse student code"))
            continue

        student = db.scalar(select(Student).where(Student.student_code == student_code))
        if student is None:
            student = Student(
                student_code=student_code,
                full_name=student_code,
                class_label=None,
                consent_status=ConsentStatus.GRANTED.value,
            )
            db.add(student)
            db.flush()

        if class_id is not None:
            if db.get(Class, class_id) is None:
                db.rollback()
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Class not found")
            enrollment = db.scalar(
                select(ClassEnrollment).where(
                    ClassEnrollment.class_id == class_id,
                    ClassEnrollment.student_id == student.id,
                )
            )
            if enrollment is None:
                db.add(ClassEnrollment(class_id=class_id, student_id=student.id))

        image_bytes = file.file.read()
        try:
            register_face_bytes(
                db,
                student_id=student.id,
                image_bytes=image_bytes,
                filename=f"{uuid.uuid4()}-{filename}",
                recognizer=recognizer,
            )
        except HTTPException as exc:
            db.rollback()
            items.append(
                FaceImportItem(
                    filename=filename,
                    student_code=student_code,
                    status="failed",
                    detail=str(exc.detail),
                )
            )
            continue

        imported += 1
        items.append(
            FaceImportItem(
                filename=filename,
                student_code=student_code,
                status="imported",
                detail="OK",
            )
        )

    return FaceImportResponse(imported=imported, failed=len(items) - imported, items=items)


@router.get("/classes/{class_id}/face-templates", dependencies=[Depends(verify_camera_token)])
def list_class_face_templates(class_id: int, db: Session = Depends(get_db)) -> list[dict[str, object]]:
    rows = db.execute(
        select(FaceTemplate)
        .join(ClassEnrollment, ClassEnrollment.student_id == FaceTemplate.student_id)
        .where(
            ClassEnrollment.class_id == class_id,
            FaceTemplate.is_active.is_(True),
        )
    ).scalars()
    return [
        {
            "student_id": template.student_id,
            "model_name": template.model_name,
            "model_version": template.model_version,
            "embedding_dim": template.embedding_dim,
            "embedding_base64": base64.b64encode(template.embedding).decode("ascii"),
        }
        for template in rows
    ]


@router.get("/reports/attendance.csv")
def export_attendance_csv(
    session_id: int,
    _user: User = Depends(require_teacher_or_admin),
    db: Session = Depends(get_db),
) -> Response:
    rows = db.execute(
        select(
            Student.student_code,
            Student.full_name,
            AttendanceRecord.status,
            AttendanceRecord.source,
            AttendanceRecord.recorded_at,
        )
        .join(AttendanceRecord, AttendanceRecord.student_id == Student.id)
        .where(AttendanceRecord.session_id == session_id)
        .order_by(Student.student_code)
    ).all()
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["student_code", "full_name", "status", "source", "recorded_at"])
    writer.writerows(rows)
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="attendance-session-{session_id}.csv"'},
    )


@router.get("/reports/attendance.xlsx")
def export_attendance_excel(
    session_id: int,
    _user: User = Depends(require_teacher_or_admin),
    db: Session = Depends(get_db),
) -> Response:
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter
    except ModuleNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Excel export dependency is not installed. Install requirements.txt.",
        ) from exc

    class_session = db.get(ClassSession, session_id)
    if class_session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    class_ = db.get(Class, class_session.class_id)
    board = _build_attendance_board(db, class_session)
    stats = _attendance_stats_from_board(board)

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Attendance"

    title = f"Attendance report - {class_.code if class_ else ''}"
    sheet["A1"] = title
    sheet["A1"].font = Font(size=16, bold=True)
    sheet.merge_cells("A1:H1")

    metadata = [
        ("Class", f"{class_.code} - {class_.name}" if class_ else str(class_session.class_id)),
        ("Teacher", class_.teacher_display_name if class_ else ""),
        ("Expected start", class_session.expected_start_time.isoformat() if class_session.expected_start_time else ""),
        ("Late grace minutes", class_session.late_grace_minutes),
        ("Total students", stats.total_students),
        ("Present rate", f"{stats.present_rate}%"),
        ("Late rate", f"{stats.late_rate}%"),
        ("Absent rate", f"{stats.absent_rate}%"),
    ]
    for index, (label, value) in enumerate(metadata, start=3):
        sheet.cell(row=index, column=1, value=label).font = Font(bold=True)
        sheet.cell(row=index, column=2, value=value)

    summary_start = 3
    summary = [
        ("Present", stats.present_count),
        ("Late", stats.late_count),
        ("Absent", stats.absent_count),
        ("Pending", stats.pending_count),
    ]
    for offset, (label, value) in enumerate(summary):
        row = summary_start + offset
        sheet.cell(row=row, column=4, value=label).font = Font(bold=True)
        sheet.cell(row=row, column=5, value=value)

    header_row = 13
    headers = [
        "Student code",
        "Full name",
        "Class",
        "Recorded at",
        "Status",
        "Source",
        "Late minutes",
        "Evidence image",
    ]
    for column, header in enumerate(headers, start=1):
        cell = sheet.cell(row=header_row, column=column, value=header)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="2563EB")
        cell.alignment = Alignment(horizontal="center")

    for row_index, row in enumerate(board.rows, start=header_row + 1):
        values = [
            row.student_code,
            row.full_name,
            row.class_label or "",
            row.recorded_at.isoformat() if row.recorded_at else "",
            row.status,
            row.source or "",
            row.late_minutes,
            row.evidence_image_url or "",
        ]
        for column, value in enumerate(values, start=1):
            sheet.cell(row=row_index, column=column, value=value)

    for column in range(1, len(headers) + 1):
        column_letter = get_column_letter(column)
        max_length = max(
            len(str(sheet.cell(row=row, column=column).value or ""))
            for row in range(1, sheet.max_row + 1)
        )
        sheet.column_dimensions[column_letter].width = min(max(max_length + 2, 12), 42)
    sheet.freeze_panes = "A14"

    output = BytesIO()
    workbook.save(output)
    return Response(
        content=output.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="attendance-session-{session_id}.xlsx"'},
    )
