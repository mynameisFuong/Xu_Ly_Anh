from dataclasses import dataclass

import cv2
import numpy as np

MIN_FACE_SIZE = 80
MIN_BRIGHTNESS = 45
MAX_BRIGHTNESS = 230
MIN_BLUR_VARIANCE = 20


@dataclass(frozen=True)
class QualityResult:
    accepted: bool
    score: float
    reason: str | None = None


def assess_face_quality(face_bgr: np.ndarray) -> QualityResult:
    if face_bgr.size == 0:
        return QualityResult(False, 0.0, "Empty face crop")

    height, width = face_bgr.shape[:2]
    if min(height, width) < MIN_FACE_SIZE:
        return QualityResult(False, 0.0, f"Face is too small: min side {min(height, width)} px")

    gray = cv2.cvtColor(face_bgr, cv2.COLOR_BGR2GRAY)
    brightness = float(gray.mean())
    blur = float(cv2.Laplacian(gray, cv2.CV_64F).var())

    if brightness < MIN_BRIGHTNESS:
        return QualityResult(False, 0.0, f"Image is too dark: brightness {brightness:.1f}")
    if brightness > MAX_BRIGHTNESS:
        return QualityResult(False, 0.0, f"Image is overexposed: brightness {brightness:.1f}")
    if blur < MIN_BLUR_VARIANCE:
        return QualityResult(False, 0.0, f"Image is blurry: blur score {blur:.1f}")

    brightness_score = min(brightness / 120.0, 1.0)
    blur_score = min(blur / 250.0, 1.0)
    score = round((brightness_score + blur_score) / 2.0, 3)
    return QualityResult(True, score)
