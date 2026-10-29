"""Shared orchestration; adapters keep the legacy public return contracts."""

from dataclasses import dataclass, replace
from collections import Counter, deque
from threading import Lock
from time import perf_counter

import cv2
import numpy as np

from ai_pipeline.liveness import LivenessDetector, LivenessResult
from ai_pipeline.preprocessing import (
    PreparedFrame, PreprocessingOptions, align_eyes, normalize_lighting,
    orient_image, rotate_roll, source_box, transform_box,
)
from ai_pipeline.quality import assess_face_quality
from ai_pipeline.recognition import EmbeddingResult, estimate_head_pose


@dataclass(frozen=True)
class AnalysisDiagnostics:
    liveness: LivenessResult | None = None
    operations: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    shadow_embedding_distance: float | None = None
    shadow_accepted: bool | None = None


class FaceAnalysis:
    def __init__(self, recognizer, *, preprocessing: PreprocessingOptions,
                 liveness: LivenessDetector | None = None, liveness_mode: str = "off"):
        if preprocessing.mode not in {"off", "shadow", "enforce"} or liveness_mode not in {"off", "shadow", "enforce"}:
            raise ValueError("Pipeline modes must be off, shadow or enforce")
        self.recognizer = recognizer
        self.preprocessing = preprocessing
        self.liveness = liveness or LivenessDetector()
        self.liveness_mode = liveness_mode
        self._metrics_lock = Lock()
        self._counts = Counter()
        self._latencies = deque(maxlen=128)
        self._pad_latencies = deque(maxlen=128)
        self._shadow_distances = deque(maxlen=128)

    def metrics(self) -> dict:
        """Aggregate only: no face pixels, embeddings, candidate IDs or frame IDs."""
        with self._metrics_lock:
            return {
                "counts": dict(self._counts),
                "analysis_p50_ms": float(np.percentile(self._latencies, 50)) if self._latencies else None,
                "analysis_p95_ms": float(np.percentile(self._latencies, 95)) if self._latencies else None,
                "pad_p95_ms": float(np.percentile(self._pad_latencies, 95)) if self._pad_latencies else None,
                "shadow_distance_mean": float(np.mean(self._shadow_distances)) if self._shadow_distances else None,
            }

    def _legacy(self, frame, num_jitters):
        if self.recognizer._face_recognition is not None:
            return self.recognizer._extract_dlib(frame, num_jitters=num_jitters)
        return self.recognizer._extract_fallback(frame)

    def _check_liveness(self, frame, box):
        started = perf_counter()
        result = self.liveness.evaluate(frame, box, require_approved=self.liveness_mode == "enforce")
        with self._metrics_lock:
            self._pad_latencies.append((perf_counter() - started) * 1000)
        return result

    def analyze(self, frame: np.ndarray, *, num_jitters: int = 1) -> EmbeddingResult:
        started = perf_counter()
        # Shadow must keep the old embedding, pose and acceptance decision.
        if self.preprocessing.mode != "enforce" and self.liveness_mode != "enforce":
            result = self._legacy(frame, num_jitters)
            pad = self._check_liveness(frame, result.face_box) if (
                self.liveness_mode == "shadow" and result.accepted and result.face_box is not None
            ) else None
            diagnostics = AnalysisDiagnostics(liveness=pad)
        else:
            options = self.preprocessing if self.preprocessing.mode == "enforce" else PreprocessingOptions()
            result = self._process(frame, options, num_jitters=num_jitters)
            diagnostics = result.diagnostics or AnalysisDiagnostics()

        if self.preprocessing.mode == "shadow" and (self.liveness_mode != "enforce" or result.accepted):
            candidate = self._process(frame, self.preprocessing, num_jitters=num_jitters, check_pad=False)
            distance = None
            if result.accepted and candidate.accepted and candidate.embedding.shape == result.embedding.shape:
                distance = float(np.linalg.norm(candidate.embedding - result.embedding))
            diagnostics = replace(
                diagnostics,
                operations=candidate.diagnostics.operations if candidate.diagnostics else (),
                warnings=candidate.diagnostics.warnings if candidate.diagnostics else (),
                shadow_embedding_distance=distance,
                shadow_accepted=candidate.accepted,
            )
        with self._metrics_lock:
            self._counts["frames"] += 1
            self._counts["accepted" if result.accepted else "rejected"] += 1
            if result.reason == "No face detected":
                self._counts["no_face"] += 1
            if result.reason == "Multiple faces detected":
                self._counts["multiple_faces"] += 1
            if diagnostics.liveness:
                self._counts["pad_" + diagnostics.liveness.status] += 1
            for warning in diagnostics.warnings:
                self._counts[warning] += 1
            self._latencies.append((perf_counter() - started) * 1000)
            if diagnostics.shadow_embedding_distance is not None:
                self._shadow_distances.append(diagnostics.shadow_embedding_distance)
            if diagnostics.shadow_accepted is not None:
                self._counts["shadow_accepted" if diagnostics.shadow_accepted else "shadow_rejected"] += 1
        return replace(result, diagnostics=diagnostics)

    def _process(self, frame, options, *, num_jitters, check_pad=True):
        warnings = []
        prepared = orient_image(frame, mirror=options.mirror_input if options.mode != "off" else False)
        boxes = self.recognizer.detect_faces(prepared.image)
        rescue = getattr(self.recognizer, "detect_rescue_faces", self.recognizer.detect_faces)
        if not boxes and options.mode != "off" and options.search_rolls:
            upright = orient_image(frame, mirror=options.mirror_input)
            for angle in (20, -20, 40, -40):
                prepared = rotate_roll(upright, angle)
                boxes = rescue(prepared.image)
                if boxes:
                    break
        if not boxes and options.mode != "off" and options.search_rotations:
            for rotation in (90, 180, 270):
                prepared = orient_image(frame, rotation=rotation, mirror=options.mirror_input)
                boxes = rescue(prepared.image)
                if boxes:
                    break
        pad = None
        box = None

        def rejected(reason, quality_score=None, pose=None):
            return EmbeddingResult(
                False, np.empty(0, dtype=np.float32), quality_score, reason, pose, box,
                AnalysisDiagnostics(pad, prepared.operations, tuple(warnings)),
            )

        if not boxes:
            return rejected("No face detected")
        if len(boxes) != 1:
            return rejected("Multiple faces detected")
        work_box = transform_box(boxes[0], np.eye(3), prepared.image.shape)
        box = source_box(prepared, boxes[0], frame.shape)
        if box is None or work_box is None:
            return rejected("Empty face crop")
        x, y, width, height = box
        # Measure the native pixels before interpolation, contrast or resizing.
        quality = assess_face_quality(frame[y:y + height, x:x + width])
        if not quality.accepted:
            return rejected(quality.reason, quality.score)
        if check_pad and self.liveness_mode != "off":
            pad = self._check_liveness(frame, box)
            if self.liveness_mode == "enforce" and pad.status != "live":
                reason = {"spoof": "Liveness spoof suspected", "uncertain": "Liveness uncertain"}.get(
                    pad.status, "Liveness unavailable")
                return rejected(reason, quality.score)

        pose = None
        landmarks = None
        library = self.recognizer._face_recognition
        if library is not None:
            rgb = cv2.cvtColor(prepared.image, cv2.COLOR_BGR2RGB)
            wx, wy, ww, wh = work_box
            locations = [(wy, wx + ww, wy + wh, wx)]
            try:
                found = library.face_landmarks(rgb, locations, model="large")
            except (ValueError, RuntimeError, cv2.error):
                found = []
                warnings.append("landmarks-unavailable")
            landmarks = found[0] if found else None
            if landmarks:
                try:
                    pose = estimate_head_pose(landmarks, prepared.image.shape)
                    if pose is None:
                        warnings.append("pose-unavailable")
                except (ValueError, KeyError, IndexError, cv2.error):
                    warnings.append("pose-unavailable")

        transformed = prepared
        if options.mode != "off":
            if options.align_eyes:
                try:
                    transformed = align_eyes(prepared, landmarks or {}, max_roll_degrees=options.max_roll_degrees)
                    # Do not use reflected/synthetic pixels to recover a clipped face.
                    matrix = transformed.source_to_image @ np.linalg.inv(prepared.source_to_image)
                    aligned_box = transform_box(work_box, matrix, transformed.image.shape)
                    wx, wy, ww, wh = work_box
                    corners = np.array([[wx, wy, 1], [wx + ww - 1, wy, 1],
                                        [wx, wy + wh - 1, 1], [wx + ww - 1, wy + wh - 1, 1]]) @ matrix.T
                    h, w = transformed.image.shape[:2]
                    if aligned_box is None or np.any(corners[:, :2] < 0) or np.any(corners[:, 0] >= w) or np.any(corners[:, 1] >= h):
                        raise ValueError("Alignment would clip the face")
                except (ValueError, cv2.error):
                    transformed = prepared
                    warnings.append("alignment-fallback")
            if options.normalize_lighting:
                try:
                    transformed = PreparedFrame(normalize_lighting(transformed.image), transformed.source_to_image,
                                                transformed.operations + ("clahe",))
                except (ValueError, cv2.error):
                    warnings.append("lighting-fallback")

        def encode(view):
            # Dùng box detector trong hệ tọa độ prepared; round-trip AABB qua ảnh
            # gốc khi xoay roll sẽ làm box phình lên và giảm độ chính xác dlib.
            relative = view.source_to_image @ np.linalg.inv(prepared.source_to_image)
            target = transform_box(work_box, relative, view.image.shape)
            if target is None:
                return None
            tx, ty, tw, th = target
            if library is None:
                return self.recognizer._fallback_embedding(view.image[ty:ty + th, tx:tx + tw])
            try:
                values = library.face_encodings(
                    cv2.cvtColor(view.image, cv2.COLOR_BGR2RGB), [(ty, tx + tw, ty + th, tx)],
                    num_jitters=max(1, num_jitters), model="large",
                )
            except (ValueError, RuntimeError, cv2.error):
                return None
            return values[0] if values else None

        expected_dim = 128 if library is not None else 256

        def valid(value):
            return value is not None and np.shape(value) == (expected_dim,) and np.isfinite(value).all()

        embedding = encode(transformed)
        if not valid(embedding):
            embedding = None
        if embedding is None and transformed.operations != prepared.operations:
            warnings.append("encoding-fallback")
            transformed = prepared
            embedding = encode(prepared)
        if not valid(embedding):
            return rejected("Cannot encode face", quality.score, pose)
        diagnostics = AnalysisDiagnostics(pad, transformed.operations, tuple(warnings))
        return EmbeddingResult(True, np.asarray(embedding, dtype=np.float32), quality.score,
                               pose=pose, face_box=box, diagnostics=diagnostics)
