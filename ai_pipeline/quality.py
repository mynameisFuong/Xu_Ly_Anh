from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class QualityResult:
    accepted: bool
    score: float
    reason: str | None = None


def assess_face_quality(face_bgr: np.ndarray) -> QualityResult:
    if face_bgr.size == 0:
        return QualityResult(False, 0.0, "Empty face crop")

    height, width = face_bgr.shape[:2]
    if min(height, width) < 80:
        return QualityResult(False, 0.0, "Face is too small")

    gray = cv2.cvtColor(face_bgr, cv2.COLOR_BGR2GRAY)
    brightness = float(gray.mean())
    blur = float(cv2.Laplacian(gray, cv2.CV_64F).var())

    if brightness < 45:
        return QualityResult(False, 0.0, "Image is too dark")
    if brightness > 230:
        return QualityResult(False, 0.0, "Image is overexposed")
    if blur < 70:
        return QualityResult(False, 0.0, "Image is blurry")

    brightness_score = min(brightness / 120.0, 1.0)
    blur_score = min(blur / 250.0, 1.0)
    score = round((brightness_score + blur_score) / 2.0, 3)
    return QualityResult(True, score)
