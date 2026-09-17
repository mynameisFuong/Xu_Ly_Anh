import csv
import base64
import uuid
from io import StringIO
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.models import (
    AttendanceRecord,
    Class,
    ClassEnrollment,
    ClassSession,
    FaceTemplate,
    Student,
    User,
)
from backend.app.schemas import (
    AttendanceManualUpdate,
    AttendanceBoardRead,
    AttendanceBoardRow,
    AttendanceRead,
    ClassCreate,
    ClassRead,
    FaceTemplateRead,
    FrameScanRequest,
    FrameScanResponse,
    RecognitionEventCreate,
    RecognitionEventRead,
    SessionCreate,
    SessionPolicyUpdate,
    SessionRead,
    StudentCreate,
    StudentRead,
    UserCreate,
    UserRead,
)
from backend.app.security import (
    get_current_user,
    hash_password,
    require_admin,
    require_teacher_or_admin,
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
from backend.app.services.face_templates import build_default_recognizer, register_face_image

router = APIRouter()


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
        late_grace_minutes=payload.late_grace_minutes,
    )


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
    _user: User = Depends(require_teacher_or_admin),
    db: Session = Depends(get_db),
) -> AttendanceBoardRead:
    class_session = db.get(ClassSession, session_id)
    if class_session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    rows = db.execute(
        select(Student, AttendanceRecord)
        .join(ClassEnrollment, ClassEnrollment.student_id == Student.id)
        .outerjoin(
            AttendanceRecord,
            (AttendanceRecord.student_id == Student.id) & (AttendanceRecord.session_id == session_id),
        )
        .where(ClassEnrollment.class_id == class_session.class_id)
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
            )
        )

    return AttendanceBoardRead(
        session_id=class_session.id,
        class_id=class_session.class_id,
        expected_start_time=class_session.expected_start_time,
        late_grace_minutes=class_session.late_grace_minutes,
        rows=board_rows,
    )


@router.post("/sessions/{session_id}/scan-frame", response_model=FrameScanResponse)
def scan_frame(
    session_id: int,
    payload: FrameScanRequest,
    _user: User = Depends(require_teacher_or_admin),
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

    from backend.app.config import get_settings

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
