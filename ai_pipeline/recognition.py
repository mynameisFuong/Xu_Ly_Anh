from dataclasses import dataclass
from pathlib import Path
from contextlib import nullcontext
from threading import RLock
from typing import TYPE_CHECKING

import cv2
import numpy as np

from ai_pipeline.quality import assess_face_quality
from ai_pipeline.preprocessing import decode_bgr_image

if TYPE_CHECKING:
    from ai_pipeline.analysis import AnalysisDiagnostics

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
    face_box: tuple[int, int, int, int] | None = None
    diagnostics: "AnalysisDiagnostics | None" = None


@dataclass(frozen=True)
class FrameEmbeddingResult:
    faces: tuple[EmbeddingResult, ...]
    width: int
    height: int
    reason: str | None = None


@dataclass(frozen=True)
class MatchResult:
    student_id: int | None
    score: float
    second_score: float
    decision: str


def classify_pose(yaw: float, pitch: float, *, pitch_threshold: float = 12) -> str:
    """Map head angles to the five guided enrollment poses."""
    if yaw <= -18:
        return "left"
    if yaw >= 18:
        return "right"
    if pitch <= -pitch_threshold:
        return "up"
    if pitch >= pitch_threshold:
        return "down"
    return "front"


def classify_enrollment_pose(pose: PoseResult, target_pose: str, neutral_pitch: float | None) -> str:
    """Use the accepted front frame as the vertical reference for later poses."""
    if neutral_pitch is None or target_pose == "front":
        return pose.label
    relative_pitch = pose.pitch - max(-12.0, min(12.0, neutral_pitch))
    return classify_pose(pose.yaw, relative_pitch, pitch_threshold=8)


def _center(points: list[tuple[int, int]]) -> tuple[float, float]:
    values = np.asarray(points, dtype=np.float64)
    return float(values[:, 0].mean()), float(values[:, 1].mean())


def estimate_head_pose(landmarks: dict[str, list[tuple[int, int]]], image_shape) -> PoseResult | None:
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
    if not np.isfinite(image_points).all():
        return None
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
        return None
    rotation_matrix, _ = cv2.Rodrigues(rotation)
    angles, *_ = cv2.RQDecomp3x3(rotation_matrix)
    pitch, yaw, _roll = (float(value) for value in angles)
    if not np.isfinite([pitch, yaw, _roll]).all():
        return None
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

    def __init__(self, cascade_path: str | None = None, *, preprocessing=None, detection=None) -> None:
        self._lock = RLock()
        self._face_detector = None
        self._analysis = None
        if preprocessing is not None:
            from ai_pipeline.analysis import FaceAnalysis
            from ai_pipeline.preprocessing import PreprocessingOptions

            options = preprocessing or PreprocessingOptions()
            if options.mode != "off":
                self._analysis = FaceAnalysis(self, preprocessing=options)
        try:
            import face_recognition as face_recognition_lib
        except (ImportError, RuntimeError):
            face_recognition_lib = None
        self._face_recognition = face_recognition_lib
        if face_recognition_lib is not None:
            if detection is not None and detection.backend in {"hybrid", "yunet"}:
                from ai_pipeline.detection import HybridFaceDetector

                self._face_detector = HybridFaceDetector(detection)
            self.model_name = "ageitgey-face-recognition-dlib-resnet"
            self.model_version = "dlib-resnet-v1-128d"
            self.distance_metric = "euclidean"
            self.supports_pose = True
            self.detector = None
            if preprocessing is not None and preprocessing.mode == "enforce":
                self.model_version += ":" + preprocessing.profile
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
        if preprocessing is not None and preprocessing.mode == "enforce":
            self.model_version += ":" + preprocessing.profile

    def extract_single_embedding(self, image_bytes: bytes, *, num_jitters: int = 1) -> EmbeddingResult:
        frame = decode_bgr_image(image_bytes)
        if frame is None:
            return EmbeddingResult(False, np.empty(0, dtype=np.float32), reason="Cannot decode image")
        with getattr(self, "_lock", nullcontext()):
            if getattr(self, "_analysis", None) is not None:
                return self._analysis.analyze(frame, num_jitters=num_jitters)
            if self._face_recognition is not None:
                return self._extract_dlib(frame, num_jitters=num_jitters)
            return self._extract_fallback(frame)

    def extract_frame_embeddings(self, image_bytes: bytes, *, max_faces: int = 8,
                                 offset: int = 0, num_jitters: int = 1) -> FrameEmbeddingResult:
        """Attendance-only batch API; enrollment still rejects multiple faces."""
        if max_faces < 1:
            raise ValueError("max_faces must be positive")
        frame = decode_bgr_image(image_bytes)
        if frame is None:
            return FrameEmbeddingResult((), 0, 0, "Cannot decode image")
        with getattr(self, "_lock", nullcontext()):
            analysis = getattr(self, "_analysis", None)
            faces = (analysis.analyze_many(frame, max_faces=max_faces, offset=offset, num_jitters=num_jitters)
                     if analysis is not None else self._extract_many(frame, None, max_faces=max_faces,
                                                                   offset=offset, num_jitters=num_jitters))
        return FrameEmbeddingResult(tuple(faces), frame.shape[1], frame.shape[0], None if faces else "No face detected")

    def _extract_many(self, frame, options, *, max_faces, offset, num_jitters):
        from ai_pipeline.preprocessing import orient_image, source_box
        from ai_pipeline.detection import box_iou

        analysis = getattr(self, "_analysis", None)
        if options is not None:
            prepared, boxes, attempts, elapsed = analysis._detect_frame(frame, options)
        else:
            prepared, attempts, elapsed = orient_image(frame), 1, 0
            boxes = self.detect_faces(frame)
        # Hybrid detectors may overlap. Never count the same physical box twice.
        unique = []
        for box in sorted(boxes, key=lambda value: (-value[2] * value[3], value[0], value[1])):
            if not any(box_iou(box, existing) >= 0.6 for existing in unique):
                unique.append(box)
        unique.sort(key=lambda box: (box[0], box[1], box[2], box[3]))
        selected = {(offset + index) % len(unique) for index in range(min(max_faces, len(unique)))} if unique else set()
        results = []
        shared_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB) if options is None and self._face_recognition is not None else None
        for index, box in enumerate(unique):
            native_box = source_box(prepared, box, frame.shape)
            if native_box is None:
                continue
            if index not in selected:
                results.append(EmbeddingResult(False, np.empty(0, np.float32), reason="Waiting for face processing",
                                               face_box=native_box))
                continue
            try:
                if options is not None:
                    result = analysis._process(frame, options, num_jitters=num_jitters,
                                               detection=(prepared, [box], attempts, elapsed), include_pose=False)
                elif self._face_recognition is not None:
                    x, y, w, h = box
                    result = self._extract_dlib(frame, num_jitters=num_jitters, locations=[(y, x + w, y + h, x)],
                                                include_pose=False, rgb=shared_rgb)
                else:
                    result = self._extract_fallback(frame, boxes=[box])
            except (ValueError, RuntimeError, cv2.error, np.linalg.LinAlgError):
                result = EmbeddingResult(False, np.empty(0, np.float32), reason="Cannot encode face", face_box=native_box)
            results.append(result)
        return results

    def _extract_dlib(self, frame: np.ndarray, *, num_jitters: int, locations=None, include_pose=True, rgb=None) -> EmbeddingResult:
        if rgb is None:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        if locations is None:
            locations = self._face_recognition.face_locations(rgb, number_of_times_to_upsample=1, model="hog")
        if not locations:
            return EmbeddingResult(False, np.empty(0, dtype=np.float32), reason="No face detected")
        if len(locations) > 1:
            return EmbeddingResult(False, np.empty(0, dtype=np.float32), reason="Multiple faces detected")
        top, right, bottom, left = locations[0]
        height, width = frame.shape[:2]
        left, top, right, bottom = max(0, left), max(0, top), min(width, right), min(height, bottom)
        face_box = (left, top, right - left, bottom - top)
        locations = [(top, right, bottom, left)]
        quality = assess_face_quality(frame[top:bottom, left:right])
        landmarks = self._face_recognition.face_landmarks(rgb, locations, model="large") if include_pose else []
        pose = estimate_head_pose(landmarks[0], frame.shape) if landmarks else None
        if not quality.accepted:
            return EmbeddingResult(
                False, np.empty(0, dtype=np.float32), quality_score=quality.score,
                reason=quality.reason, pose=pose, face_box=face_box
            )
        encodings = self._face_recognition.face_encodings(
            rgb, locations, num_jitters=max(1, num_jitters), model="large"
        )
        if not encodings:
            return EmbeddingResult(
                False, np.empty(0, dtype=np.float32), reason="Cannot encode face",
                pose=pose, face_box=face_box
            )
        return EmbeddingResult(True, encodings[0].astype(np.float32), quality.score, pose=pose, face_box=face_box)

    def _extract_fallback(self, frame: np.ndarray, *, boxes=None) -> EmbeddingResult:
        faces = self.detect_faces(frame) if boxes is None else boxes
        if not faces:
            return EmbeddingResult(False, np.empty(0, dtype=np.float32), reason="No face detected")
        if len(faces) > 1:
            return EmbeddingResult(False, np.empty(0, dtype=np.float32), reason="Multiple faces detected")
        x, y, w, h = faces[0]
        face_box = (x, y, w, h)
        face = frame[y : y + h, x : x + w]
        quality = assess_face_quality(face)
        if not quality.accepted:
            return EmbeddingResult(False, np.empty(0, dtype=np.float32), reason=quality.reason, face_box=face_box)
        return EmbeddingResult(True, self._fallback_embedding(face), quality.score, face_box=face_box)

    def detect_faces(self, frame_bgr: np.ndarray) -> list[tuple[int, int, int, int]]:
        with getattr(self, "_lock", nullcontext()):
            return self._detect_faces(frame_bgr)

    def _detect_faces(self, frame_bgr: np.ndarray) -> list[tuple[int, int, int, int]]:
        if self._face_recognition is not None:
            detector = getattr(self, "_face_detector", None)
            if detector is not None and detector.options.backend == "yunet":
                boxes = detector.detect(frame_bgr, [])
                # Tất cả các mặt DNN thấy đều được giữ; không chọn mặt lớn nhất.
                if boxes:
                    return boxes
                # HOG chỉ cứu khi DNN không thấy mặt/không sẵn sàng, tránh chạy cả hai mỗi frame.
                rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
                locations = self._face_recognition.face_locations(rgb, model="hog")
                return [(left, top, right - left, bottom - top) for top, right, bottom, left in locations]
            rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            locations = self._face_recognition.face_locations(rgb, model="hog")
            boxes = [(left, top, right - left, bottom - top) for top, right, bottom, left in locations]
            return detector.detect(frame_bgr, boxes) if detector is not None else boxes
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        faces = self.detector.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(80, 80))
        return [(int(x), int(y), int(w), int(h)) for x, y, w, h in faces]

    def detect_rescue_faces(self, frame_bgr: np.ndarray) -> list[tuple[int, int, int, int]]:
        """Tránh chạy lại HOG tốn CPU trên từng canvas xoay nếu YuNet sẵn sàng."""
        with getattr(self, "_lock", nullcontext()):
            detector = getattr(self, "_face_detector", None)
            if detector is not None and detector.status()["yunet_ready"]:
                return detector.detect(frame_bgr, [])
            return self._detect_faces(frame_bgr)

    def extract_embeddings_from_frame(self, frame_bgr: np.ndarray):
        ok, encoded = cv2.imencode(".jpg", frame_bgr)
        if not ok:
            return []
        result = self.extract_frame_embeddings(encoded.tobytes())
        return [(face.face_box, face.embedding) for face in result.faces if face.accepted and face.face_box is not None]

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
    embedding = np.asarray(embedding)
    if embedding.ndim != 1 or embedding.size == 0 or not np.isfinite(embedding).all():
        return MatchResult(None, 0.0, 0.0, "unknown")
    templates = {
        student_id: valid
        for student_id, items in templates.items()
        if (valid := [item for item in items if np.shape(item) == embedding.shape and np.isfinite(item).all()])
    }
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
