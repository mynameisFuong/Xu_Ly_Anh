"""Shared orchestration; adapters keep the legacy public return contracts."""

from dataclasses import dataclass, replace
from collections import Counter, deque
from threading import Lock
from time import perf_counter

import cv2
import numpy as np

from ai_pipeline.preprocessing import (
    PreparedFrame, PreprocessingOptions, align_eyes, normalize_lighting,
    enhance_face_region, native_face_region, orient_image, rotate_roll, source_box, transform_box,
)
from ai_pipeline.quality import QualityMetrics, assess_face_quality, assess_face_quality_v2
from ai_pipeline.recognition import EmbeddingResult, estimate_head_pose
from ai_pipeline.detection import box_iou


@dataclass(frozen=True)
class AnalysisDiagnostics:
    operations: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    shadow_embedding_distance: float | None = None
    shadow_accepted: bool | None = None
    quality: QualityMetrics | None = None
    detection_attempts: int = 0
    preprocessing_ms: float | None = None


class FaceAnalysis:
    def __init__(self, recognizer, *, preprocessing: PreprocessingOptions):
        if preprocessing.mode not in {"off", "shadow", "enforce"}:
            raise ValueError("Pipeline modes must be off, shadow or enforce")
        self.recognizer = recognizer
        self.preprocessing = preprocessing
        self._metrics_lock = Lock()
        self._counts = Counter()
        self._latencies = deque(maxlen=128)
        self._shadow_distances = deque(maxlen=128)
        self._shadow_latencies = deque(maxlen=128)
        self._preprocessing_latencies = deque(maxlen=128)
        self._shadow_credit = 1 - preprocessing.shadow_sample_rate

    def metrics(self) -> dict:
        """Aggregate only: no face pixels, embeddings, candidate IDs or frame IDs."""
        with self._metrics_lock:
            return {
                "counts": dict(self._counts),
                "analysis_p50_ms": float(np.percentile(self._latencies, 50)) if self._latencies else None,
                "analysis_p95_ms": float(np.percentile(self._latencies, 95)) if self._latencies else None,
                "shadow_distance_mean": float(np.mean(self._shadow_distances)) if self._shadow_distances else None,
                "shadow_p95_ms": float(np.percentile(self._shadow_latencies, 95)) if self._shadow_latencies else None,
                "preprocessing_p95_ms": float(np.percentile(self._preprocessing_latencies, 95)) if self._preprocessing_latencies else None,
            }

    def _legacy(self, frame, num_jitters):
        if self.recognizer._face_recognition is not None:
            return self.recognizer._extract_dlib(frame, num_jitters=num_jitters)
        return self.recognizer._extract_fallback(frame)

    def shadow_options(self):
        options = self.preprocessing
        if options.mode == "shadow":
            return replace(options, version="v2") if options.shadow_v2 else options
        if options.mode == "enforce" and options.version == "v1" and options.shadow_v2:
            return replace(options, version="v2")
        return None

    def analyze(self, frame: np.ndarray, *, num_jitters: int = 1) -> EmbeddingResult:
        started = perf_counter()
        # Shadow must keep the old embedding, pose and acceptance decision.
        if self.preprocessing.mode != "enforce":
            result = self._legacy(frame, num_jitters)
            diagnostics = AnalysisDiagnostics()
        else:
            result = self._process(frame, self.preprocessing, num_jitters=num_jitters)
            diagnostics = result.diagnostics or AnalysisDiagnostics()

        candidate_options = self.shadow_options()
        shadow = candidate_options is not None
        with self._metrics_lock:
            self._shadow_credit += self.preprocessing.shadow_sample_rate if shadow else 0
            sample_shadow = shadow and self.preprocessing.shadow_sample_rate > 0 and self._shadow_credit >= 1 - 1e-9
            if sample_shadow:
                self._shadow_credit -= 1
        if sample_shadow:
            candidate_started = perf_counter()
            try:
                candidate = self._process(frame, candidate_options, num_jitters=num_jitters)
            except (ValueError, RuntimeError, cv2.error, np.linalg.LinAlgError):
                candidate = EmbeddingResult(False, np.empty(0, np.float32), reason="Shadow processing failed",
                                            diagnostics=AnalysisDiagnostics(warnings=("shadow-failed",)))
            with self._metrics_lock:
                self._shadow_latencies.append((perf_counter() - candidate_started) * 1000)
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
            for warning in diagnostics.warnings:
                self._counts[warning] += 1
            for operation in diagnostics.operations:
                self._counts[("shadow:" if sample_shadow else "operation:") + operation] += 1
            self._latencies.append((perf_counter() - started) * 1000)
            if diagnostics.preprocessing_ms is not None:
                self._preprocessing_latencies.append(diagnostics.preprocessing_ms)
            if diagnostics.shadow_embedding_distance is not None:
                self._shadow_distances.append(diagnostics.shadow_embedding_distance)
            if diagnostics.shadow_accepted is not None:
                self._counts["shadow_accepted" if diagnostics.shadow_accepted else "shadow_rejected"] += 1
        return replace(result, diagnostics=diagnostics)

    def _detect_frame(self, frame, options):
        started = perf_counter()
        prepared = orient_image(frame, mirror=options.mirror_input)
        elapsed = (perf_counter() - started) * 1000
        boxes = self.recognizer.detect_faces(prepared.image)
        attempts = 1
        rescue = getattr(self.recognizer, "detect_rescue_faces", self.recognizer.detect_faces)
        rotations = [("rotation", angle) for angle in (90, 180, 270)] if options.search_rotations else []
        rolls = [("roll", angle) for angle in (20, -20, 40, -40)
                 if options.version == "v1" or abs(angle) <= options.max_roll_degrees] if options.search_rolls else []
        steps = rolls + rotations if options.version == "v1" else rotations + rolls
        limit = 8 if options.version == "v1" else options.max_detection_attempts
        for kind, angle in steps:
            if boxes or attempts >= limit:
                break
            started = perf_counter()
            prepared = (orient_image(frame, rotation=angle, mirror=options.mirror_input) if kind == "rotation"
                        else rotate_roll(orient_image(frame, mirror=options.mirror_input), angle))
            elapsed += (perf_counter() - started) * 1000
            boxes = rescue(prepared.image)
            attempts += 1
        return prepared, boxes, attempts, elapsed

    def analyze_many(self, frame, *, max_faces=8, offset=0, num_jitters=1):
        """Detect once, then apply the unchanged profile to each independent box."""
        started = perf_counter()
        options = self.preprocessing if self.preprocessing.mode == "enforce" else None
        results = self.recognizer._extract_many(frame, options, max_faces=max_faces, offset=offset,
                                               num_jitters=num_jitters)
        candidate_options = self.shadow_options()
        with self._metrics_lock:
            self._shadow_credit += self.preprocessing.shadow_sample_rate if candidate_options else 0
            sample = candidate_options is not None and self.preprocessing.shadow_sample_rate > 0 and self._shadow_credit >= 1 - 1e-9
            if sample:
                self._shadow_credit -= 1
        if sample:
            shadow_started = perf_counter()
            try:
                candidates = self.recognizer._extract_many(frame, candidate_options, max_faces=max_faces,
                                                           offset=offset, num_jitters=num_jitters)
                distances = []
                for result in results:
                    if not result.accepted or result.face_box is None:
                        continue
                    overlaps = [item for item in candidates if item.accepted and item.face_box is not None
                                and item.embedding.shape == result.embedding.shape
                                and box_iou(result.face_box, item.face_box) >= 0.5]
                    if overlaps:
                        candidate = max(overlaps, key=lambda item: box_iou(result.face_box, item.face_box))
                        distances.append(float(np.linalg.norm(result.embedding - candidate.embedding)))
                with self._metrics_lock:
                    self._shadow_distances.extend(distances)
                    self._counts["stream_shadow_frames"] += 1
            except (ValueError, RuntimeError, cv2.error, np.linalg.LinAlgError):
                with self._metrics_lock:
                    self._counts["stream_shadow_failed"] += 1
            with self._metrics_lock:
                self._shadow_latencies.append((perf_counter() - shadow_started) * 1000)
        with self._metrics_lock:
            self._counts["stream_frames"] += 1
            self._counts["stream_faces"] += len(results)
            self._counts["stream_accepted_faces"] += sum(item.accepted for item in results)
            self._latencies.append((perf_counter() - started) * 1000)
        return results

    def _process(self, frame, options, *, num_jitters, detection=None, include_pose=True):
        if options.version == "v2":
            return self._process_v2(frame, options, num_jitters=num_jitters, detection=detection, include_pose=include_pose)
        return self._process_v1(frame, options, num_jitters=num_jitters, detection=detection, include_pose=include_pose)

    def _process_v2(self, frame, options, *, num_jitters, detection=None, include_pose=True):
        warnings = []
        prepared, boxes, attempts, preprocessing_ms = self._detect_frame(frame, options) if detection is None else detection
        box, quality, pose = None, None, None

        def rejected(reason):
            return EmbeddingResult(False, np.empty(0, np.float32), quality.score if quality else None,
                                   reason, pose, box, AnalysisDiagnostics(
                                       operations=prepared.operations, warnings=tuple(warnings),
                                       quality=quality.metrics if quality else None, detection_attempts=attempts,
                                       preprocessing_ms=preprocessing_ms))

        if not boxes:
            return rejected("No face detected")
        if len(boxes) != 1:
            return rejected("Multiple faces detected")
        work_box = transform_box(boxes[0], np.eye(3), prepared.image.shape)
        box = source_box(prepared, boxes[0], frame.shape)
        if work_box is None or box is None or work_box != tuple(boxes[0]):
            return rejected("Face is clipped")
        preprocessing_started = perf_counter()
        try:
            native, mask = native_face_region(frame, prepared, work_box)
            quality = assess_face_quality_v2(native, mask, native_min_side=min(work_box[2:]))
        except (ValueError, cv2.error, np.linalg.LinAlgError) as exc:
            preprocessing_ms += (perf_counter() - preprocessing_started) * 1000
            return rejected("Face is clipped" if str(exc) == "Face is clipped" else "Empty face crop")
        preprocessing_ms += (perf_counter() - preprocessing_started) * 1000
        if not quality.accepted:
            return rejected(quality.reason)
        library = self.recognizer._face_recognition
        landmarks = None
        if library is not None and (include_pose or options.v2_align_eyes):
            x, y, w, h = work_box
            try:
                found = library.face_landmarks(cv2.cvtColor(prepared.image, cv2.COLOR_BGR2RGB),
                                               [(y, x + w, y + h, x)], model="large")
                landmarks = found[0] if found else None
            except (ValueError, RuntimeError, cv2.error):
                warnings.append("landmarks-unavailable")
            if landmarks and include_pose:
                try:
                    pose = estimate_head_pose(landmarks, prepared.image.shape)
                except (ValueError, KeyError, IndexError, cv2.error):
                    warnings.append("pose-unavailable")
        preprocessing_started = perf_counter()
        transformed = prepared
        if options.v2_align_eyes:
            try:
                # Verify landmarks against the detected face, not just the canvas.
                x, y, w, h = work_box
                for name in ("left_eye", "right_eye"):
                    points = np.asarray((landmarks or {}).get(name, []), np.float64)
                    if (points.ndim != 2 or points.shape[1] != 2 or not np.isfinite(points).all()
                            or np.any(points < [x, y]) or np.any(points > [x + w - 1, y + h - 1])):
                        raise ValueError("Eye landmarks outside face")
                transformed = align_eyes(prepared, landmarks or {}, max_roll_degrees=options.max_roll_degrees,
                                         source_image=frame)
                relative = transformed.source_to_image @ np.linalg.inv(prepared.source_to_image)
                x, y, w, h = work_box
                corners = np.array([[x, y, 1], [x + w - 1, y, 1],
                                    [x, y + h - 1, 1], [x + w - 1, y + h - 1, 1]]) @ relative.T
                height, width = transformed.image.shape[:2]
                if np.any(corners[:, :2] < 0) or np.any(corners[:, 0] >= width) or np.any(corners[:, 1] >= height):
                    raise ValueError("Alignment would clip face")
            except (ValueError, cv2.error, np.linalg.LinAlgError):
                transformed = prepared
                warnings.append("alignment-fallback")

        def target_box(view):
            relative = view.source_to_image @ np.linalg.inv(prepared.source_to_image)
            return transform_box(work_box, relative, view.image.shape)

        try:
            image, operations = self._enhance_region(transformed.image, target_box(transformed), quality.metrics, options)
            transformed = PreparedFrame(image, transformed.source_to_image, transformed.operations + operations)
        except (ValueError, cv2.error):
            warnings.append("enhancement-fallback")
        preprocessing_ms += (perf_counter() - preprocessing_started) * 1000

        def encode(view):
            target = target_box(view)
            if target is None:
                return None
            x, y, w, h = target
            try:
                if library is None:
                    return self.recognizer._fallback_embedding(view.image[y:y + h, x:x + w])
                values = library.face_encodings(cv2.cvtColor(view.image, cv2.COLOR_BGR2RGB),
                                                [(y, x + w, y + h, x)], num_jitters=max(1, num_jitters), model="large")
                return values[0] if values else None
            except (ValueError, RuntimeError, cv2.error):
                return None

        def valid(value):
            return value is not None and np.shape(value) == (128 if library is not None else 256,) and np.isfinite(value).all()

        embedding = encode(transformed)
        if not valid(embedding) and transformed.operations != prepared.operations:
            warnings.append("encoding-fallback")
            transformed = prepared
            embedding = encode(prepared)
        if not valid(embedding):
            return rejected("Cannot encode face")
        return EmbeddingResult(True, np.asarray(embedding, np.float32), quality.score, pose=pose, face_box=box,
                               diagnostics=AnalysisDiagnostics(operations=transformed.operations, warnings=tuple(warnings),
                                                               quality=quality.metrics, detection_attempts=attempts,
                                                               preprocessing_ms=preprocessing_ms))

    _enhance_region = staticmethod(enhance_face_region)

    def _process_v1(self, frame, options, *, num_jitters, detection=None, include_pose=True):
        warnings = []
        prepared, boxes, _attempts, _elapsed = self._detect_frame(frame, options) if detection is None else detection
        box = None

        def rejected(reason, quality_score=None, pose=None):
            return EmbeddingResult(
                False, np.empty(0, dtype=np.float32), quality_score, reason, pose, box,
                AnalysisDiagnostics(operations=prepared.operations, warnings=tuple(warnings)),
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
        pose = None
        landmarks = None
        library = self.recognizer._face_recognition
        if library is not None and (include_pose or options.align_eyes):
            rgb = cv2.cvtColor(prepared.image, cv2.COLOR_BGR2RGB)
            wx, wy, ww, wh = work_box
            locations = [(wy, wx + ww, wy + wh, wx)]
            try:
                found = library.face_landmarks(rgb, locations, model="large")
            except (ValueError, RuntimeError, cv2.error):
                found = []
                warnings.append("landmarks-unavailable")
            landmarks = found[0] if found else None
            if landmarks and include_pose:
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
        diagnostics = AnalysisDiagnostics(operations=transformed.operations, warnings=tuple(warnings))
        return EmbeddingResult(True, np.asarray(embedding, dtype=np.float32), quality.score,
                               pose=pose, face_box=box, diagnostics=diagnostics)
