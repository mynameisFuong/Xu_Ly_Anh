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
    metrics: "QualityMetrics | None" = None


@dataclass(frozen=True)
class QualityMetrics:
    brightness: float
    contrast: float
    laplacian_variance: float
    tenengrad: float
    shadow_fraction: float
    highlight_fraction: float
    noise_sigma: float
    impulse_fraction: float


def measure_face_quality(face_bgr: np.ndarray, mask: np.ndarray | None = None) -> QualityMetrics:
    """Measure native source pixels, never an enhanced/resized face as evidence."""
    gray = cv2.cvtColor(face_bgr, cv2.COLOR_BGR2GRAY)
    valid = np.ones(gray.shape, np.uint8) if mask is None else (mask != 0).astype(np.uint8)
    if valid.shape != gray.shape or not np.any(valid):
        raise ValueError("Empty face crop")
    pixels = gray[valid != 0]
    inner = cv2.erode(valid, np.ones((3, 3), np.uint8), borderType=cv2.BORDER_CONSTANT, borderValue=0) != 0
    if not np.any(inner):
        raise ValueError("Empty face crop")
    laplacian = cv2.Laplacian(gray, cv2.CV_64F)
    # Scale-normalized diagnostic only; native sharpness remains the hard gate.
    normalized = cv2.resize(gray, (128, 128), interpolation=cv2.INTER_AREA)
    normalized_mask = cv2.resize(valid, (128, 128), interpolation=cv2.INTER_NEAREST)
    normalized_mask = cv2.erode(normalized_mask, np.ones((3, 3), np.uint8)) != 0
    gx = cv2.Sobel(normalized, cv2.CV_32F, 1, 0)
    gy = cv2.Sobel(normalized, cv2.CV_32F, 0, 1)
    gradient = cv2.Sobel(gray, cv2.CV_32F, 1, 0) ** 2 + cv2.Sobel(gray, cv2.CV_32F, 0, 1) ** 2
    flat = inner & (gradient <= np.percentile(gradient[inner], 25))
    # Robust high-pass MAD in low-gradient regions reduces edge/texture bias.
    kernel = np.array([[1, -2, 1], [-2, 4, -2], [1, -2, 1]], np.float32)
    residual = cv2.filter2D(gray, cv2.CV_32F, kernel)[flat]
    sigma = float(np.median(np.abs(residual - np.median(residual))) / (0.67448975 * 6))
    median = cv2.medianBlur(gray, 3)
    impulses = ((gray <= 3) | (gray >= 252)) & (np.abs(gray.astype(np.int16) - median) >= 40) & inner
    return QualityMetrics(
        brightness=float(pixels.mean()), contrast=float(np.percentile(pixels, 90) - np.percentile(pixels, 10)),
        laplacian_variance=float(laplacian[inner].var()),
        tenengrad=float((gx * gx + gy * gy)[normalized_mask].mean()) if np.any(normalized_mask) else 0.0,
        shadow_fraction=float(np.mean(pixels <= 5)), highlight_fraction=float(np.mean(pixels >= 250)),
        noise_sigma=sigma, impulse_fraction=float(np.count_nonzero(impulses) / np.count_nonzero(inner)),
    )


def assess_face_quality_v2(face_bgr: np.ndarray, mask: np.ndarray | None = None, *,
                           native_min_side: float | None = None) -> QualityResult:
    if face_bgr.size == 0:
        return QualityResult(False, 0.0, "Empty face crop")
    min_side = min(face_bgr.shape[:2]) if native_min_side is None else native_min_side
    if min_side < MIN_FACE_SIZE:
        return QualityResult(False, 0.0, f"Face is too small: min side {min_side:.0f} px")
    metrics = measure_face_quality(face_bgr, mask)

    def reject(reason):
        return QualityResult(False, 0.0, reason, metrics)

    if metrics.brightness < MIN_BRIGHTNESS or metrics.shadow_fraction > 0.5:
        return reject(f"Image is too dark: brightness {metrics.brightness:.1f}")
    if metrics.brightness > MAX_BRIGHTNESS or metrics.highlight_fraction > 0.5:
        return reject(f"Image is overexposed: brightness {metrics.brightness:.1f}")
    if metrics.laplacian_variance < MIN_BLUR_VARIANCE:
        return reject(f"Image is blurry: blur score {metrics.laplacian_variance:.1f}")
    if metrics.contrast < 12:
        return reject("Image has insufficient detail")
    brightness_score = min(metrics.brightness / 120, 1.0)
    sharpness_score = min(metrics.laplacian_variance / 250, 1.0)
    return QualityResult(True, round((brightness_score + sharpness_score) / 2, 3), metrics=metrics)


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
