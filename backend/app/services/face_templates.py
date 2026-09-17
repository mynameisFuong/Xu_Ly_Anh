from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.models import ConsentStatus, FaceTemplate, Student


def embedding_to_bytes(embedding) -> bytes:
    return embedding.astype("float32").tobytes()


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
    result = recognizer.extract_single_embedding(image_bytes)
    if not result.accepted:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result.reason)

    storage_dir = get_settings().storage_dir / "enrollment_images" / str(student_id)
    storage_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(file.filename or "face.jpg").name
    image_path = storage_dir / safe_name
    image_path.write_bytes(image_bytes)

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
