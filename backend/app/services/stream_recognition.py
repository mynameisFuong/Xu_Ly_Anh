"""Continuous multi-face attendance using fresh, independently confirmed matches."""

import base64
from collections import Counter
from functools import lru_cache
from hashlib import sha256
import logging
import json
from time import monotonic, perf_counter

import numpy as np
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from ai_pipeline.recognition import ENROLLMENT_POSES, match_embedding
from ai_pipeline.streaming import FaceObservation, StaleFrameError, StreamBusyError, StreamStateStore
from backend.app.config import get_settings
from backend.app.models import AttendanceRecord, ClassEnrollment, ClassSession, ConsentStatus, FaceTemplate, Student
from backend.app.schemas import RecognitionEventCreate, StreamFaceResult, StreamScanResponse
from backend.app.services.attendance import create_recognition_event

logger = logging.getLogger(__name__)


@lru_cache(maxsize=4)
def stream_states(min_hits, window_seconds):
    return StreamStateStore(min_hits, window_seconds)


def _gallery(db, class_id, model_version, dimension):
    completed = (select(FaceTemplate.student_id)
                 .where(FaceTemplate.is_active.is_(True), FaceTemplate.model_version == model_version,
                        FaceTemplate.pose_label.in_(ENROLLMENT_POSES))
                 .group_by(FaceTemplate.student_id)
                 .having(func.count(func.distinct(FaceTemplate.pose_label)) >= len(ENROLLMENT_POSES)))
    rows = db.execute(select(FaceTemplate, Student)
                      .join(Student, Student.id == FaceTemplate.student_id)
                      .join(ClassEnrollment, ClassEnrollment.student_id == Student.id)
                      .where(ClassEnrollment.class_id == class_id, Student.deleted_at.is_(None),
                             Student.consent_status == ConsentStatus.GRANTED.value,
                             FaceTemplate.is_active.is_(True), FaceTemplate.model_version == model_version,
                             FaceTemplate.student_id.in_(completed)))
    templates, students = {}, {}
    for template, student in rows:
        if template.embedding_dim != dimension or len(template.embedding) != dimension * 4:
            continue
        vector = np.frombuffer(template.embedding, np.float32)
        if np.isfinite(vector).all():
            templates.setdefault(student.id, []).append(vector)
            students[student.id] = student
    return templates, students


def _attendance(db, *, session_id, student_id):
    return db.scalar(select(AttendanceRecord).where(AttendanceRecord.session_id == session_id,
                                                   AttendanceRecord.student_id == student_id))


def _record(db, *, session_id, student_id, camera_id, recognizer, match):
    attendance = _attendance(db, session_id=session_id, student_id=student_id)
    if attendance is not None:
        return attendance, True
    identity = json.dumps([session_id, student_id, camera_id, recognizer.model_version], separators=(",", ":"))
    payload = RecognitionEventCreate(camera_id=camera_id, student_id=student_id, decision="recognized",
                                     model_version=recognizer.model_version, candidate_score=match.score,
                                     second_score=match.second_score,
                                     idempotency_key="stream-" + sha256(identity.encode()).hexdigest())
    try:
        _event, attendance = create_recognition_event(db, session_id=session_id, payload=payload)
        return attendance, False
    except IntegrityError:
        # A parallel stream/camera may have committed the unique attendance first.
        db.rollback()
        attendance = _attendance(db, session_id=session_id, student_id=student_id)
        if attendance is None:
            raise
        return attendance, True


def scan_stream_frame(db, *, session_id, payload, owner, recognizer, save_evidence,
                      localize_reason, dry_run=False):
    started = perf_counter()
    settings = get_settings()
    class_session = db.get(ClassSession, session_id)
    if class_session is None:
        raise HTTPException(404, "Session not found")
    if class_session.status != "open":
        raise HTTPException(409, "Session is not open")
    try:
        image_bytes = base64.b64decode(payload.image_base64.split(",", 1)[-1], validate=True)
    except ValueError as exc:
        raise HTTPException(400, "Invalid image data") from exc
    store = stream_states(settings.attendance_min_hits, settings.stream_confirmation_window_seconds)
    key = (session_id, owner, payload.camera_id, payload.stream_id, recognizer.model_version, dry_run)
    try:
        with store.checkout(key, payload.frame_id) as state:
            batch = recognizer.extract_frame_embeddings(
                image_bytes, max_faces=settings.stream_max_faces_per_frame,
                offset=payload.frame_id * settings.stream_max_faces_per_frame,
            )
            if batch.reason == "Cannot decode image":
                state.tracker.clear()
                raise HTTPException(400, "Cannot decode image")
            dimensions = (batch.width, batch.height)
            if state.dimensions != dimensions:
                state.tracker.clear()
                state.dimensions = dimensions
            faces = [face for face in batch.faces if face.face_box is not None]
            dimension = 128 if recognizer.distance_metric == "euclidean" else 256
            templates, students = _gallery(db, class_session.class_id, recognizer.model_version, dimension) if faces else ({}, {})
            matches = []
            for face in faces:
                valid = face.accepted and face.embedding.shape == (dimension,) and np.isfinite(face.embedding).all()
                matches.append(match_embedding(
                    face.embedding, templates,
                    threshold=settings.face_distance_threshold if dimension == 128 else settings.attendance_threshold,
                    margin=settings.face_distance_margin if dimension == 128 else settings.attendance_margin,
                    metric=recognizer.distance_metric,
                ) if valid and templates else None)
            counts = Counter(match.student_id for match in matches if match is not None and match.student_id is not None)
            observations = [FaceObservation(face.face_box, match.student_id if match else None,
                                             processed=face.reason != "Waiting for face processing")
                            for face, match in zip(faces, matches)]
            confirmations = state.tracker.update(observations, frame_id=payload.frame_id, now=monotonic())
            results = []
            for face, match, confirmation in zip(faces, matches, confirmations):
                base = dict(face_box=face.face_box, track_id=confirmation.track_id,
                            confirmation_hits=confirmation.hits, confirmation_required=settings.attendance_min_hits,
                            candidate_score=match.score if match else None, second_score=match.second_score if match else None)
                if face.reason == "Waiting for face processing":
                    results.append(StreamFaceResult(decision="pending", message="Đang chờ xử lý khuôn mặt", **base))
                elif not face.accepted:
                    results.append(StreamFaceResult(decision="unknown", message=localize_reason(face.reason), **base))
                elif not templates:
                    results.append(StreamFaceResult(decision="unknown", message="Chưa có mẫu Face ID hợp lệ trong lớp. Vui lòng đăng ký đủ 5 góc trước khi điểm danh", **base))
                elif match is None or match.student_id is None:
                    results.append(StreamFaceResult(decision="low_confidence", message="Chưa nhận diện được, vui lòng nhìn rõ camera", **base))
                elif counts[match.student_id] > 1:
                    results.append(StreamFaceResult(decision="low_confidence", message="Kết quả trùng danh tính; vui lòng nhìn rõ camera", **base))
                elif not confirmation.confirmed:
                    results.append(StreamFaceResult(decision="pending",
                                                    message=f"Đang xác nhận {confirmation.hits}/{settings.attendance_min_hits}", **base))
                else:
                    student = students[match.student_id]
                    identity = dict(student_id=student.id, student_code=student.student_code, full_name=student.full_name,
                                    class_label=student.class_label, class_name=class_session.class_.name if class_session.class_ else None)
                    if dry_run:
                        results.append(StreamFaceResult(decision="recognized", message="Chạy thử: không ghi điểm danh", **identity, **base))
                        continue
                    attendance, already = _record(db, session_id=session_id, student_id=student.id,
                                                   camera_id=payload.camera_id, recognizer=recognizer, match=match)
                    if attendance is None:
                        results.append(StreamFaceResult(decision="unknown", message="Chưa lưu được điểm danh, đang thử lại", **base))
                        continue
                    if not already:
                        try:
                            save_evidence(db, attendance=attendance, image_bytes=image_bytes)
                        except OSError:
                            logger.warning("Could not save stream attendance evidence", exc_info=True)
                    needs_review = attendance.status not in {"present", "late"}
                    message = ("Đã có kết quả điều chỉnh; vui lòng liên hệ giảng viên" if needs_review else
                               "Đã điểm danh trong buổi này" if already else
                               f"Trễ {attendance.late_minutes} phút" if attendance.status == "late" else "Đúng giờ")
                    results.append(StreamFaceResult(decision="review" if needs_review else "recognized", message=message,
                                                    attendance=attendance, already_recorded=already, **identity, **base))
            recognized = sum(item.decision == "recognized" and item.attendance is not None for item in results)
            message = (f"{len(results)} khuôn mặt · {recognized} đã điểm danh · {len(results) - recognized} đang chờ"
                       if results else "Đang quét liên tục, chờ khuôn mặt vào khung hình")
            reasons = [item.message for item in results if item.decision in {"unknown", "review"}]
            if reasons:
                message += " · " + reasons[0]
            return StreamScanResponse(frame_id=payload.frame_id, frame_width=batch.width, frame_height=batch.height,
                                      faces=results, message=message, processing_ms=round((perf_counter() - started) * 1000, 1))
    except StaleFrameError as exc:
        raise HTTPException(409, str(exc)) from exc
    except StreamBusyError as exc:
        raise HTTPException(429, str(exc)) from exc
