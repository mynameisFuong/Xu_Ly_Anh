from types import SimpleNamespace

import numpy as np
import pytest

from ai_pipeline.minifasnet import MiniFASNetDetector, minifasnet_tensor


def test_crop_keeps_bgr_scale_dtype_and_never_changes_source():
    image = np.zeros((480, 640, 3), np.uint8)
    image[:] = (12, 105, 230)
    original = image.copy()
    for box in ((0, 0, 100, 120), (540, 360, 100, 120), (200, 150, 100, 120)):
        for scale in (2.7, 4.0):
            tensor = minifasnet_tensor(image, box, scale)
            assert tensor.shape == (1, 3, 80, 80) and tensor.dtype == np.float32
            np.testing.assert_array_equal(tensor[0, :, 20, 20], [12, 105, 230])
    np.testing.assert_array_equal(image, original)


@pytest.mark.parametrize("box", [(-1, 0, 80, 80), (0, 0, 0, 80), (20, 20, 90, 80)])
def test_invalid_crop_rejects(box):
    with pytest.raises(ValueError):
        minifasnet_tensor(np.zeros((100, 100, 3), np.uint8), box, 2.7)


def test_missing_or_unapproved_model_cannot_enforce(tmp_path):
    detector = MiniFASNetDetector(tmp_path)
    assert not detector.ready and not detector.can_enforce
    assert detector.evaluate(np.zeros((100, 100, 3), np.uint8), (0, 0, 80, 80), require_approved=True).status == "unavailable"


def fake_session(logits):
    return SimpleNamespace(run=lambda *_: [np.array([logits], np.float32)])


@pytest.mark.parametrize("second,expected", [([0, 8, 0], "live"), ([8, 0, 0], "spoof"), ([0, 1, 0], "uncertain")])
def test_both_networks_must_agree_and_scores_are_softmax_not_raw_logits(tmp_path, second, expected):
    detector = MiniFASNetDetector(tmp_path, allow_pretrained=True)
    detector._sessions = [(fake_session([0, 8, 0]), "input", "output", 2.7),
                          (fake_session(second), "input", "output", 4.0)]
    result = detector.evaluate(np.zeros((100, 100, 3), np.uint8), (10, 10, 80, 80), require_approved=True)
    assert result.status == expected and 0 <= result.score <= 1
    detector.allow_pretrained = False
    assert detector.evaluate(np.zeros((100, 100, 3), np.uint8), (10, 10, 80, 80), require_approved=True).status == "unavailable"
