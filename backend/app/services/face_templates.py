from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.models import ConsentStatus, FaceTemplate, Student

PORTRAIT_WIDTH = 400
PORTRAIT_HEIGHT = 600


def embedding_to_bytes(embedding) -> bytes:
    return embedding.astype("float32").tobytes()


def normalize_portrait_4x6(image_bytes: bytes, recognizer) -> bytes:
    import cv2
    import numpy as np

    image_array = np.frombuffer(image_bytes, dtype=np.uint8)
    frame = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
    if frame is None:
        return image_bytes

    image_height, image_width = frame.shape[:2]
    target_ratio = PORTRAIT_WIDTH / PORTRAIT_HEIGHT
    faces = recognizer.detect_faces(frame)

    if faces:
        x, y, w, h = max(faces, key=lambda box: box[2] * box[3])
        center_x = x + w / 2
        center_y = y + h / 2
        crop_h = max(h * 2.2, image_height * 0.35)
        crop_w = crop_h * target_ratio
    else:
        center_x = image_width / 2
        center_y = image_height / 2
        crop_w = image_width
        crop_h = crop_w / target_ratio
        if crop_h > image_height:
            crop_h = image_height
            crop_w = crop_h * target_ratio

    crop_w = min(crop_w, image_width)
    crop_h = min(crop_h, image_height)
    left = int(max(0, min(center_x - crop_w / 2, image_width - crop_w)))
    top = int(max(0, min(center_y - crop_h / 2, image_height - crop_h)))
    right = int(min(image_width, left + crop_w))
    bottom = int(min(image_height, top + crop_h))
    crop = frame[top:bottom, left:right]
    if crop.size == 0:
        crop = frame

    portrait = cv2.resize(crop, (PORTRAIT_WIDTH, PORTRAIT_HEIGHT), interpolation=cv2.INTER_AREA)
    ok, encoded = cv2.imencode(".jpg", portrait, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
    return encoded.tobytes() if ok else image_bytes


def register_face_image(
    db: Session,
    *,
    student_id: int,
    file: UploadFile,
    recognizer,
) -> FaceTemplate:
    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")
    if student.consent_status != ConsentStatus.GRANTED.value:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Student consent is not granted")

    image_bytes = file.file.read()
    return register_face_bytes(
        db,
        student_id=student_id,
        image_bytes=image_bytes,
        filename=file.filename or "face.jpg",
        recognizer=recognizer,
    )


def register_face_bytes(
    db: Session,
    *,
    student_id: int,
    image_bytes: bytes,
    filename: str,
    recognizer,
) -> FaceTemplate:
    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")
    if student.consent_status != ConsentStatus.GRANTED.value:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Student consent is not granted")

    result = recognizer.extract_single_embedding(image_bytes)
    if not result.accepted:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result.reason)

    storage_dir = get_settings().storage_dir / "enrollment_images" / str(student_id)
    storage_dir.mkdir(parents=True, exist_ok=True)
    safe_stem = Path(filename or "face.jpg").stem
    safe_name = f"{safe_stem}.jpg"
    image_path = storage_dir / safe_name
    image_path.write_bytes(normalize_portrait_4x6(image_bytes, recognizer))

    template = FaceTemplate(
        student_id=student_id,
        embedding=embedding_to_bytes(result.embedding),
        model_name=recognizer.model_name,
        model_version=recognizer.model_version,
        embedding_dim=int(result.embedding.shape[0]),
        image_path=str(image_path),
        quality_score=result.quality_score,
        is_active=True,
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


def build_default_recognizer():
    try:
        from ai_pipeline.recognition import FaceRecognizer
    except ModuleNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Face recognition dependencies are not installed. Install requirements-camera.txt.",
        ) from exc
    return FaceRecognizer()
