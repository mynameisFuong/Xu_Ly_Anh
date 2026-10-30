from types import SimpleNamespace

import cv2
import numpy as np

from ai_pipeline.analysis import FaceAnalysis
from ai_pipeline.preprocessing import PreprocessingOptions
from ai_pipeline.recognition import EmbeddingResult, FaceRecognizer, PoseResult, match_embedding


class FaceLibrary:
    def __init__(self, calls):
        self.calls = calls
        self.encoded_images = []

    def face_landmarks(self, image, *_args, **_kwargs):
        self.calls.append("landmarks")
        return [{"left_eye": [(65, 80), (69, 80)], "right_eye": [(110, 90), (114, 90)]}]

    def face_encodings(self, image, *_args, **_kwargs):
        self.calls.append("embedding")
        self.encoded_images.append(image.copy())
        return [np.ones(128, dtype=np.float32)]


def fixtures(*, preprocessing="enforce"):
    calls = []
    library = FaceLibrary(calls)
    legacy = EmbeddingResult(True, np.arange(128, dtype=np.float32), 0.9,
                             pose=PoseResult("right", 25, 3), face_box=(40, 40, 100, 100))
    recognizer = SimpleNamespace(
        _face_recognition=library,
        detect_faces=lambda frame: [(40, 40, 100, 100)],
        _extract_dlib=lambda *_args, **_kwargs: legacy,
    )
    pipeline = FaceAnalysis(recognizer, preprocessing=PreprocessingOptions(mode=preprocessing))
    frame = np.random.default_rng(2).integers(50, 210, (200, 200, 3), dtype=np.uint8)
    return pipeline, frame, calls, library, legacy


def test_pose_is_measured_before_alignment_and_pixels_are_not_mutated(monkeypatch):
    pipeline, frame, calls, library, _ = fixtures()
    original = frame.copy()
    monkeypatch.setattr("ai_pipeline.analysis.estimate_head_pose", lambda *_: PoseResult("right", 25, 3))
    result = pipeline.analyze(frame)
    assert result.accepted and result.pose.label == "right"
    assert calls == ["landmarks", "embedding"]
    np.testing.assert_array_equal(frame, original)
    assert not np.array_equal(library.encoded_images[0], cv2.cvtColor(original, cv2.COLOR_BGR2RGB))
    assert result.embedding.dtype == np.float32 and result.embedding.shape == (128,)


def test_shadow_keeps_legacy_embedding_pose_and_decision():
    pipeline, frame, _, _, legacy = fixtures(preprocessing="shadow")
    result = pipeline.analyze(frame)
    assert result.accepted == legacy.accepted
    assert result.pose == legacy.pose
    assert result.face_box == legacy.face_box
    np.testing.assert_array_equal(result.embedding, legacy.embedding)
    assert result.diagnostics.shadow_embedding_distance is not None


def test_bad_quality_and_multiple_faces_never_reach_embedding():
    pipeline, frame, calls, _, _ = fixtures()
    result = pipeline.analyze(np.zeros_like(frame))
    assert not result.accepted and not calls
    pipeline.recognizer.detect_faces = lambda _: [(0, 0, 90, 90), (95, 95, 90, 90)]
    result = pipeline.analyze(frame)
    assert result.reason == "Multiple faces detected" and not calls


def test_rotation_rescue_returns_box_in_original_coordinates():
    pipeline, _, _, _, _ = fixtures()
    frame = np.random.default_rng(3).integers(50, 210, (180, 240, 3), dtype=np.uint8)
    pipeline.recognizer.detect_faces = lambda image: [(20, 30, 100, 110)] if image.shape[:2] == (240, 180) else []
    result = pipeline.analyze(frame)
    assert result.accepted
    assert result.face_box == (30, 60, 110, 100)
    assert "rotate-90" in result.diagnostics.operations


def test_roll_rescue_encodes_the_detector_box_without_aabb_roundtrip_expansion():
    from dataclasses import replace
    from ai_pipeline.preprocessing import orient_image, rotate_roll

    pipeline, _, _, library, _ = fixtures()
    pipeline.preprocessing = replace(pipeline.preprocessing, align_eyes=False, normalize_lighting=False,
                                     search_rotations=False)
    frame = np.random.default_rng(12).integers(50, 210, (180, 240, 3), dtype=np.uint8)
    shape = rotate_roll(orient_image(frame), 20).image.shape
    pipeline.recognizer.detect_faces = lambda image: [(80, 70, 100, 100)] if image.shape == shape else []
    locations = []

    def encode(_image, boxes, **_kwargs):
        locations.extend(boxes)
        return [np.zeros(128, np.float32)]

    library.face_encodings = encode
    result = pipeline.analyze(frame)
    assert result.accepted and "detect-roll-20" in result.diagnostics.operations
    assert locations == [(70, 180, 170, 80)]


def test_failed_alignment_falls_back_to_a_valid_embedding():
    pipeline, frame, calls, library, _ = fixtures()
    library.face_landmarks = lambda *_args, **_kwargs: []
    result = pipeline.analyze(frame)
    assert result.accepted and calls == ["embedding"]
    assert "alignment-fallback" in result.diagnostics.warnings


def test_shadow_can_measure_rotation_rescue_without_accepting_a_legacy_rejection():
    pipeline, _, _, _, _ = fixtures(preprocessing="shadow")
    frame = np.random.default_rng(3).integers(50, 210, (180, 240, 3), dtype=np.uint8)
    pipeline.recognizer._extract_dlib = lambda *_args, **_kwargs: EmbeddingResult(
        False, np.empty(0, np.float32), reason="No face detected")
    pipeline.recognizer.detect_faces = lambda image: [(20, 30, 100, 110)] if image.shape[:2] == (240, 180) else []
    result = pipeline.analyze(frame)
    assert not result.accepted and result.reason == "No face detected"
    assert result.diagnostics.shadow_accepted is True
    assert pipeline.metrics()["counts"]["shadow_accepted"] == 1


def test_encoding_failure_retries_source():
    pipeline, frame, _, library, _ = fixtures()
    attempts = []

    def encode(*_args, **_kwargs):
        attempts.append(True)
        return [] if len(attempts) == 1 else [np.zeros(128, np.float32)]

    library.face_encodings = encode
    result = pipeline.analyze(frame)
    assert result.accepted and len(attempts) == 2
    assert "encoding-fallback" in result.diagnostics.warnings


def test_empty_and_invalid_encoded_images_are_rejected():
    recognizer = FaceRecognizer.__new__(FaceRecognizer)
    for raw in (b"", b"not an image"):
        result = recognizer.extract_single_embedding(raw)
        assert not result.accepted and result.reason == "Cannot decode image"


def test_only_enforced_preprocessing_changes_the_template_version(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "face_recognition", None)
    legacy = FaceRecognizer()
    shadow = FaceRecognizer(preprocessing=PreprocessingOptions(mode="shadow"))
    upgraded = FaceRecognizer(preprocessing=PreprocessingOptions(mode="enforce"))
    assert legacy.model_version == shadow.model_version == "0.1.0"
    assert upgraded.model_version.startswith("0.1.0:pre-v1-")
    assert not upgraded.supports_pose


def test_matching_ignores_malformed_templates_and_nonfinite_queries():
    query = np.array([0.1, 0.2], np.float32)
    templates = {1: [np.ones(3), np.array([np.nan, 0])], 2: [query.copy()]}
    assert match_embedding(query, templates, threshold=0.5, margin=0.04, metric="euclidean").student_id == 2
    assert match_embedding(np.array([np.nan, 1]), templates, threshold=0.5, margin=0.04).student_id is None


def test_detector_lighting_rescue_still_uses_native_source_quality():
    from ai_pipeline.detection import HybridFaceDetector

    pipeline, frame, _, _, _ = fixtures()
    helper = HybridFaceDetector.__new__(HybridFaceDetector)
    helper._detector = object()
    helper.rescued_frames = helper.lighting_rescues = helper.extra_face_frames = 0
    outputs = iter(([], [(40, 40, 100, 100)]))
    helper._boxes = lambda _: next(outputs)
    pipeline.recognizer.detect_faces = lambda image: helper.detect(image, [])
    result = pipeline.analyze(frame)
    assert result.accepted and helper.lighting_rescues == 1

    dark = np.zeros_like(frame)
    pipeline.recognizer.detect_faces = lambda _: [(40, 40, 100, 100)]
    assert not pipeline.analyze(dark).accepted


def test_roll_search_uses_fast_rescue_before_cardinal_rotations():
    pipeline, frame, _, _, _ = fixtures()
    calls = []
    pipeline.recognizer.detect_faces = lambda image: []

    def rescue(image):
        calls.append(image.shape)
        return [(80, 70, 100, 100)]

    pipeline.recognizer.detect_rescue_faces = rescue
    result = pipeline.analyze(frame)
    assert result.accepted and "detect-roll-20" in result.diagnostics.operations
    assert len(calls) == 1


def test_v2_good_input_preserves_pixels_and_uses_dlib_alignment(monkeypatch):
    from dataclasses import replace

    pipeline, frame, _, library, _ = fixtures()
    pipeline.preprocessing = replace(pipeline.preprocessing, version="v2")
    monkeypatch.setattr("ai_pipeline.analysis.estimate_head_pose", lambda *_: PoseResult("front", 0, 0))
    result = pipeline.analyze(frame)
    assert result.accepted and result.diagnostics.operations == ()
    assert result.diagnostics.quality.brightness > 90
    np.testing.assert_array_equal(library.encoded_images[0], cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    assert result.face_box == (40, 40, 100, 100)
    assert result.embedding.dtype == np.float32 and result.embedding.shape == (128,)


def test_v2_uses_source_quality_and_does_not_rescue_destroyed_images():
    from dataclasses import replace

    pipeline, frame, calls, _, _ = fixtures()
    pipeline.preprocessing = replace(pipeline.preprocessing, version="v2", denoise_method="adaptive")
    for pixels in (np.zeros_like(frame), np.full_like(frame, 255), np.full_like(frame, 100)):
        result = pipeline.analyze(pixels)
        assert not result.accepted and not calls
    assert pipeline.analyze((frame * 0.55).astype(np.uint8)).accepted
    assert "gamma" in pipeline.analyze((frame * 0.55).astype(np.uint8)).diagnostics.operations


def test_v2_search_budget_bounds_missing_face_cost():
    from dataclasses import replace

    pipeline, frame, calls, _, _ = fixtures()
    pipeline.preprocessing = replace(pipeline.preprocessing, version="v2", max_detection_attempts=3)
    detections = []
    pipeline.recognizer.detect_faces = lambda pixels: detections.append(pixels.shape) or []
    result = pipeline.analyze(frame)
    assert not result.accepted and result.reason == "No face detected"
    assert len(detections) == 3 and not calls
    assert result.diagnostics.detection_attempts == 3


def test_sampled_v2_shadow_preserves_enforced_v1_and_skips_unsampled_work(monkeypatch):
    from dataclasses import replace

    pipeline, frame, _, _, _ = fixtures()
    baseline = pipeline.analyze(frame)
    pipeline.preprocessing = replace(pipeline.preprocessing, shadow_v2=True, shadow_sample_rate=0.25)
    pipeline._shadow_credit = 0.75
    candidates = []

    def fail_candidate(*_args, **_kwargs):
        candidates.append(True)
        raise ValueError("Invalid experimental transform")

    monkeypatch.setattr(pipeline, "_process_v2", fail_candidate)
    for _ in range(8):
        result = pipeline.analyze(frame)
        assert result.accepted == baseline.accepted
        np.testing.assert_array_equal(result.embedding, baseline.embedding)
        assert result.face_box == baseline.face_box and result.pose == baseline.pose
    assert len(candidates) == 2
    assert pipeline.metrics()["counts"]["shadow_rejected"] == 2


def test_v2_bad_alignment_and_photometric_failures_use_quality_approved_source(monkeypatch):
    from dataclasses import replace

    pipeline, frame, _, library, _ = fixtures()
    pipeline.preprocessing = replace(pipeline.preprocessing, version="v2", v2_align_eyes=True)
    library.face_landmarks = lambda *_args, **_kwargs: [{"left_eye": [(0, 0), (1, 0)], "right_eye": [(0, 2), (1, 2)]}]

    def failed(*_args, **_kwargs):
        raise ValueError("Enhancement failed")

    monkeypatch.setattr(pipeline, "_enhance_region", failed)
    result = pipeline.analyze(frame)
    assert result.accepted
    assert "alignment-fallback" in result.diagnostics.warnings
    assert "enhancement-fallback" in result.diagnostics.warnings
    np.testing.assert_array_equal(library.encoded_images[0], cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))


def test_only_active_shadow_candidate_is_reported():
    from dataclasses import replace

    pipeline, _, _, _, _ = fixtures()
    pipeline.preprocessing = replace(pipeline.preprocessing, version="v2", shadow_v2=True)
    assert pipeline.shadow_options() is None
    pipeline.preprocessing = replace(pipeline.preprocessing, mode="shadow", shadow_v2=False)
    assert pipeline.shadow_options().version == "v2"
    pipeline.preprocessing = replace(pipeline.preprocessing, version="v1", mode="enforce", shadow_v2=True)
    assert pipeline.shadow_options().version == "v2"
