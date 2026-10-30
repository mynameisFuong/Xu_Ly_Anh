import cv2
import numpy as np
import pytest

from ai_pipeline.evidence import face_evidence
from ai_pipeline.preprocessing import decode_bgr_image


def test_evidence_crops_only_confirmed_person_and_is_a_real_jpeg():
    frame = np.zeros((100, 200, 3), np.uint8)
    frame[:, :100] = (10, 20, 200)
    frame[:, 100:] = (200, 20, 10)
    _, encoded = cv2.imencode(".png", frame)
    evidence = face_evidence(encoded.tobytes(), (0, 0, 100, 100))
    decoded = decode_bgr_image(evidence)
    assert evidence.startswith(b"\xff\xd8") and decoded.shape == (100, 100, 3)
    assert decoded[:, :, 2].mean() > 190 and decoded[:, :, 0].mean() < 20


def test_invalid_evidence_never_falls_back_to_saving_full_frame():
    with pytest.raises(ValueError):
        face_evidence(b"invalid", (0, 0, 100, 100))
