from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from ai_pipeline.quality import assess_face_quality


@dataclass(frozen=True)
class EmbeddingResult:
    accepted: bool
    embedding: np.ndarray
    quality_score: float | None = None
    reason: str | None = None


@dataclass(frozen=True)
class MatchResult:
    student_id: int | None
    score: float
    second_score: float
    decision: str


class FaceRecognizer:
    """Small CPU-friendly wrapper.

    The MVP uses OpenCV Haar detection as an install-safe fallback. Replace
    `_extract_embedding_from_face` with OpenCV Zoo SFace or ArcFace ONNX when
    the model file is added.
    """

    model_name = "opencv-fallback-histogram"
    model_version = "0.1.0"

    def __init__(self, cascade_path: str | None = None) -> None:
        if cascade_path is None:
            cascade_path = str(Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml")
        self.detector = cv2.CascadeClassifier(cascade_path)
        if self.detector.empty():
            raise RuntimeError(f"Cannot load face detector: {cascade_path}")

    def extract_single_embedding(self, image_bytes: bytes) -> EmbeddingResult:
        image_array = np.frombuffer(image_bytes, dtype=np.uint8)
        frame = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
        if frame is None:
            return EmbeddingResult(False, np.empty(0, dtype=np.float32), reason="Cannot decode image")

        faces = self.detect_faces(frame)
        if len(faces) == 0:
            return EmbeddingResult(False, np.empty(0, dtype=np.float32), reason="No face detected")
        if len(faces) > 1:
            return EmbeddingResult(False, np.empty(0, dtype=np.float32), reason="Multiple faces detected")

        x, y, w, h = faces[0]
        face = frame[y : y + h, x : x + w]
        quality = assess_face_quality(face)
        if not quality.accepted:
            return EmbeddingResult(False, np.empty(0, dtype=np.float32), reason=quality.reason)

        embedding = self._extract_embedding_from_face(face)
        return EmbeddingResult(True, embedding, quality_score=quality.score)

    def detect_faces(self, frame_bgr: np.ndarray) -> list[tuple[int, int, int, int]]:
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        faces = self.detector.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(80, 80))
        return [(int(x), int(y), int(w), int(h)) for x, y, w, h in faces]

    def extract_embeddings_from_frame(self, frame_bgr: np.ndarray) -> list[tuple[tuple[int, int, int, int], np.ndarray]]:
        outputs: list[tuple[tuple[int, int, int, int], np.ndarray]] = []
        for box in self.detect_faces(frame_bgr):
            x, y, w, h = box
            face = frame_bgr[y : y + h, x : x + w]
            quality = assess_face_quality(face)
            if quality.accepted:
                outputs.append((box, self._extract_embedding_from_face(face)))
        return outputs

    def _extract_embedding_from_face(self, face_bgr: np.ndarray) -> np.ndarray:
        resized = cv2.resize(face_bgr, (64, 64))
        hsv = cv2.cvtColor(resized, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1], None, [16, 16], [0, 180, 0, 256]).flatten()
        norm = np.linalg.norm(hist)
        if norm == 0:
            return hist.astype(np.float32)
        return (hist / norm).astype(np.float32)


def cosine_similarity(left: np.ndarray, right: np.ndarray) -> float:
    denominator = float(np.linalg.norm(left) * np.linalg.norm(right))
    if denominator == 0:
        return 0.0
    return float(np.dot(left, right) / denominator)


def match_embedding(
    embedding: np.ndarray,
    templates: dict[int, list[np.ndarray]],
    *,
    threshold: float,
    margin: float,
) -> MatchResult:
    scores: list[tuple[int, float]] = []
    for student_id, student_embeddings in templates.items():
        best = max(cosine_similarity(embedding, item) for item in student_embeddings)
        scores.append((student_id, best))

    if not scores:
        return MatchResult(None, 0.0, 0.0, "unknown")

    scores.sort(key=lambda item: item[1], reverse=True)
    best_student_id, best_score = scores[0]
    second_score = scores[1][1] if len(scores) > 1 else 0.0
    if best_score >= threshold and best_score - second_score >= margin:
        return MatchResult(best_student_id, best_score, second_score, "recognized")
    return MatchResult(None, best_score, second_score, "low_confidence")
