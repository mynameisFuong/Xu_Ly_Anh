from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from ai_pipeline.quality import assess_face_quality

ENROLLMENT_POSES = ("front", "left", "right", "up", "down")


@dataclass(frozen=True)
class PoseResult:
    label: str
    yaw: float
    pitch: float


@dataclass(frozen=True)
class EmbeddingResult:
    accepted: bool
    embedding: np.ndarray
    quality_score: float | None = None
    reason: str | None = None
    pose: PoseResult | None = None


@dataclass(frozen=True)
class MatchResult:
    student_id: int | None
    score: float
    second_score: float
    decision: str


def classify_pose(yaw: float, pitch: float) -> str:
    """Map head angles to the five guided enrollment poses."""
    if yaw <= -18:
        return "left"
    if yaw >= 18:
        return "right"
    if pitch <= -12:
        return "up"
    if pitch >= 12:
        return "down"
    return "front"


def _center(points: list[tuple[int, int]]) -> tuple[float, float]:
    values = np.asarray(points, dtype=np.float64)
    return float(values[:, 0].mean()), float(values[:, 1].mean())


def estimate_head_pose(landmarks: dict[str, list[tuple[int, int]]], image_shape) -> PoseResult:
    """Estimate yaw/pitch from dlib's 68 landmarks with OpenCV solvePnP."""
    nose = landmarks["nose_tip"][2]
    chin = landmarks["chin"][8]
    left_eye = landmarks["left_eye"][0]
    right_eye = landmarks["right_eye"][3]
    left_mouth = landmarks["top_lip"][0]
    right_mouth = landmarks["top_lip"][6]
    image_points = np.asarray(
        [nose, chin, left_eye, right_eye, left_mouth, right_mouth], dtype=np.float64
    )
    model_points = np.asarray(
        [
            (0.0, 0.0, 0.0),
            (0.0, -330.0, -65.0),
            (-225.0, 170.0, -135.0),
            (225.0, 170.0, -135.0),
            (-150.0, -150.0, -125.0),
            (150.0, -150.0, -125.0),
        ],
        dtype=np.float64,
    )
    height, width = image_shape[:2]
    focal = float(width)
    camera = np.asarray(
        [[focal, 0, width / 2], [0, focal, height / 2], [0, 0, 1]], dtype=np.float64
    )
    ok, rotation, _translation = cv2.solvePnP(
        model_points, image_points, camera, np.zeros((4, 1)), flags=cv2.SOLVEPNP_ITERATIVE
    )
    if not ok:
        return PoseResult("front", 0.0, 0.0)
    rotation_matrix, _ = cv2.Rodrigues(rotation)
    angles, *_ = cv2.RQDecomp3x3(rotation_matrix)
    pitch, yaw, _roll = (float(value) for value in angles)
    # solvePnP may express the same orientation with a ~180° X rotation.
    # Fold it back to the human head-pose range used by the enrollment UI.
    if pitch < -90:
        pitch += 180
    elif pitch > 90:
        pitch -= 180
    return PoseResult(classify_pose(yaw, pitch), round(yaw, 1), round(pitch, 1))


class FaceRecognizer:
    """Open-source face engine with a no-download OpenCV fallback.

    `face_recognition`/dlib is preferred and produces 128-D embeddings plus
    68 landmarks for multi-angle enrollment. The histogram engine only keeps
    legacy demos running and cannot be used for guided Face ID enrollment.
    """

    def __init__(self, cascade_path: str | None = None) -> None:
        try:
            import face_recognition as face_recognition_lib
        except (ImportError, RuntimeError):
            face_recognition_lib = None
        self._face_recognition = face_recognition_lib
        if face_recognition_lib is not None:
            self.model_name = "ageitgey-face-recognition-dlib-resnet"
            self.model_version = "dlib-resnet-v1-128d"
            self.distance_metric = "euclidean"
            self.supports_pose = True
            self.detector = None
            return

        if cascade_path is None:
            cascade_path = str(Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml")
        self.detector = cv2.CascadeClassifier(cascade_path)
        if self.detector.empty():
            raise RuntimeError(f"Cannot load face detector: {cascade_path}")
        self.model_name = "opencv-fallback-histogram"
        self.model_version = "0.1.0"
        self.distance_metric = "cosine"
        self.supports_pose = False

    def extract_single_embedding(self, image_bytes: bytes, *, num_jitters: int = 1) -> EmbeddingResult:
        image_array = np.frombuffer(image_bytes, dtype=np.uint8)
        frame = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
        if frame is None:
            return EmbeddingResult(False, np.empty(0, dtype=np.float32), reason="Cannot decode image")
        if self._face_recognition is not None:
            return self._extract_dlib(frame, num_jitters=num_jitters)
        return self._extract_fallback(frame)

    def _extract_dlib(self, frame: np.ndarray, *, num_jitters: int) -> EmbeddingResult:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        locations = self._face_recognition.face_locations(rgb, number_of_times_to_upsample=1, model="hog")
        if not locations:
            return EmbeddingResult(False, np.empty(0, dtype=np.float32), reason="No face detected")
        if len(locations) > 1:
            return EmbeddingResult(False, np.empty(0, dtype=np.float32), reason="Multiple faces detected")
        top, right, bottom, left = locations[0]
        quality = assess_face_quality(frame[top:bottom, left:right])
        landmarks = self._face_recognition.face_landmarks(rgb, locations, model="large")
        pose = estimate_head_pose(landmarks[0], frame.shape) if landmarks else None
        if not quality.accepted:
            return EmbeddingResult(
                False, np.empty(0, dtype=np.float32), quality_score=quality.score, reason=quality.reason, pose=pose
            )
        encodings = self._face_recognition.face_encodings(
            rgb, locations, num_jitters=max(1, num_jitters), model="large"
        )
        if not encodings:
            return EmbeddingResult(False, np.empty(0, dtype=np.float32), reason="Cannot encode face", pose=pose)
        return EmbeddingResult(True, encodings[0].astype(np.float32), quality.score, pose=pose)

    def _extract_fallback(self, frame: np.ndarray) -> EmbeddingResult:
        faces = self.detect_faces(frame)
        if not faces:
            return EmbeddingResult(False, np.empty(0, dtype=np.float32), reason="No face detected")
        if len(faces) > 1:
            return EmbeddingResult(False, np.empty(0, dtype=np.float32), reason="Multiple faces detected")
        x, y, w, h = faces[0]
        face = frame[y : y + h, x : x + w]
        quality = assess_face_quality(face)
        if not quality.accepted:
            return EmbeddingResult(False, np.empty(0, dtype=np.float32), reason=quality.reason)
        return EmbeddingResult(True, self._fallback_embedding(face), quality.score)

    def detect_faces(self, frame_bgr: np.ndarray) -> list[tuple[int, int, int, int]]:
        if self._face_recognition is not None:
            rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            locations = self._face_recognition.face_locations(rgb, model="hog")
            return [(left, top, right - left, bottom - top) for top, right, bottom, left in locations]
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        faces = self.detector.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(80, 80))
        return [(int(x), int(y), int(w), int(h)) for x, y, w, h in faces]

    def extract_embeddings_from_frame(self, frame_bgr: np.ndarray):
        ok, encoded = cv2.imencode(".jpg", frame_bgr)
        if not ok:
            return []
        result = self.extract_single_embedding(encoded.tobytes())
        faces = self.detect_faces(frame_bgr)
        return [(faces[0], result.embedding)] if result.accepted and len(faces) == 1 else []

    @staticmethod
    def _fallback_embedding(face_bgr: np.ndarray) -> np.ndarray:
        resized = cv2.resize(face_bgr, (64, 64))
        hsv = cv2.cvtColor(resized, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1], None, [16, 16], [0, 180, 0, 256]).flatten()
        norm = np.linalg.norm(hist)
        return (hist / norm if norm else hist).astype(np.float32)


def cosine_similarity(left: np.ndarray, right: np.ndarray) -> float:
    denominator = float(np.linalg.norm(left) * np.linalg.norm(right))
    return float(np.dot(left, right) / denominator) if denominator else 0.0


def match_embedding(
    embedding: np.ndarray,
    templates: dict[int, list[np.ndarray]],
    *,
    threshold: float,
    margin: float,
    metric: str = "cosine",
) -> MatchResult:
    if not templates:
        return MatchResult(None, 0.0, 0.0, "unknown")
    if metric == "euclidean":
        distances = [
            (student_id, min(float(np.linalg.norm(embedding - item)) for item in items))
            for student_id, items in templates.items()
        ]
        distances.sort(key=lambda item: item[1])
        best_id, best_distance = distances[0]
        second_distance = distances[1][1] if len(distances) > 1 else 1.0
        score, second_score = max(0.0, 1.0 - best_distance), max(0.0, 1.0 - second_distance)
        if best_distance <= threshold and second_distance - best_distance >= margin:
            return MatchResult(best_id, score, second_score, "recognized")
        return MatchResult(None, score, second_score, "low_confidence")

    scores = [
        (student_id, max(cosine_similarity(embedding, item) for item in items))
        for student_id, items in templates.items()
    ]
    scores.sort(key=lambda item: item[1], reverse=True)
    best_id, best_score = scores[0]
    second_score = scores[1][1] if len(scores) > 1 else 0.0
    if best_score >= threshold and best_score - second_score >= margin:
        return MatchResult(best_id, best_score, second_score, "recognized")
    return MatchResult(None, best_score, second_score, "low_confidence")
