from hashlib import sha256
from pathlib import Path

import cv2
import numpy as np

from ai_pipeline.detection import FaceDetectionOptions, HybridFaceDetector, YUNET_SHA256


class Network:
    def __init__(self, outputs):
        self.outputs = iter(outputs)
        self.inputs = []
        self.size = None

    def setInputSize(self, size):
        self.size = size

    def detect(self, frame):
        self.inputs.append(frame.copy())
        assert self.size == (frame.shape[1], frame.shape[0])
        return 1, next(self.outputs)


def face(box, score=0.95):
    return [*box, *([0] * 10), score]


def detector(outputs):
    instance = HybridFaceDetector.__new__(HybridFaceDetector)
    instance.options = FaceDetectionOptions(backend="hybrid")
    instance._detector = Network(outputs)
    instance.error = None
    instance.rescued_frames = instance.lighting_rescues = instance.extra_face_frames = 0
    return instance


def test_yunet_rescues_hog_miss_and_maps_bounded_input_to_native_pixels():
    network = detector([np.array([face((50, 60, 100, 110))], np.float32)])
    frame = np.zeros((960, 1280, 3), np.uint8)
    assert network.detect(frame, []) == [(100, 120, 200, 220)]
    assert network._detector.inputs[0].shape == (480, 640, 3)
    assert network.status()["rescued_frames"] == 1


def test_hog_box_is_preserved_and_second_face_is_not_silently_discarded():
    network = detector([np.array([face((38, 38, 104, 104)), face((220, 40, 90, 110))], np.float32)])
    assert network.detect(np.zeros((300, 400, 3), np.uint8), [(40, 40, 100, 100)]) == [
        (40, 40, 100, 100), (220, 40, 90, 110),
    ]
    assert network.extra_face_frames == 1


def test_lighting_rescue_changes_detection_input_without_modifying_source():
    network = detector([None, np.array([face((30, 40, 90, 100))], np.float32)])
    frame = np.random.default_rng(7).integers(40, 80, (200, 200, 3), dtype=np.uint8)
    original = frame.copy()
    assert network.detect(frame, []) == [(30, 40, 90, 100)]
    np.testing.assert_array_equal(frame, original)
    assert not np.array_equal(network._detector.inputs[0], network._detector.inputs[1])
    assert network.lighting_rescues == 1


def test_invalid_boxes_and_low_confidence_are_not_accepted():
    rows = np.array([face((-10, -20, 80, 100)), face((20, 20, -10, 30)),
                     face((20, 20, 90, 90), 0.4), face((np.nan, 20, 90, 90))], np.float32)
    network = detector([rows])
    assert network.detect(np.zeros((200, 200, 3), np.uint8), []) == [(0, 0, 70, 80)]


def test_missing_or_tampered_artifact_retains_hog_without_loading_untrusted_model(tmp_path, monkeypatch):
    loads = []
    monkeypatch.setattr(cv2.FaceDetectorYN, "create", lambda *_args: loads.append(True))
    path = tmp_path / "model.onnx"
    missing = HybridFaceDetector(FaceDetectionOptions(backend="hybrid", model_path=path))
    assert not missing.status()["yunet_ready"]
    path.write_bytes(b"untrusted model")
    tampered = HybridFaceDetector(FaceDetectionOptions(backend="hybrid", model_path=path))
    assert tampered.detect(np.zeros((200, 200, 3), np.uint8), [(30, 40, 90, 100)]) == [(30, 40, 90, 100)]
    assert not loads


def test_downloaded_detector_can_infer_when_available():
    import pytest

    path = Path("storage/face-models/face_detection_yunet_2023mar.onnx")
    if not path.exists():
        pytest.skip("Run scripts/download_face_detector.py for local inference smoke test")
    assert sha256(path.read_bytes()).hexdigest() == YUNET_SHA256
    network = HybridFaceDetector(FaceDetectionOptions(backend="hybrid", model_path=path))
    assert network.status()["yunet_ready"]
    assert network.detect(np.zeros((480, 640, 3), np.uint8), []) == []
    assert network.error is None
