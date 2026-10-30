"""Benchmark-only photometric references; not selectable in production settings."""

import cv2
import numpy as np

from ai_pipeline.preprocessing import validate_bgr


def multiscale_retinex(image: np.ndarray) -> np.ndarray:
    """Luminance MSR (Jobson et al., 1997), bounded 1–99 percentile stretch."""
    validate_bgr(image)
    ycrcb = cv2.cvtColor(image, cv2.COLOR_BGR2YCrCb)
    luminance = ycrcb[:, :, 0].astype(np.float32) + 1
    response = np.zeros(luminance.shape, np.float32)
    for sigma in (15, 80, 250):
        response += (np.log(luminance) - np.log(cv2.GaussianBlur(luminance, (0, 0), sigma))) / 3
    low, high = np.percentile(response, [1, 99])
    if high - low < 1e-6:
        return image.copy()
    ycrcb[:, :, 0] = np.clip((response - low) * 255 / (high - low), 0, 255).astype(np.uint8)
    return cv2.cvtColor(ycrcb, cv2.COLOR_YCrCb2BGR)


def tan_triggs(image: np.ndarray) -> np.ndarray:
    """Tan–Triggs (2010): gamma, DoG, two robust normalizations, tanh."""
    validate_bgr(image)
    gray = (cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255) ** 0.2
    dog = cv2.GaussianBlur(gray, (0, 0), 1) - cv2.GaussianBlur(gray, (0, 0), 2)
    alpha, tau = 0.1, 10.0
    dog /= max(float(np.mean(np.abs(dog) ** alpha) ** (1 / alpha)), 1e-8)
    dog /= max(float(np.mean(np.minimum(np.abs(dog), tau) ** alpha) ** (1 / alpha)), 1e-8)
    result = tau * np.tanh(dog / tau)
    low, high = float(result.min()), float(result.max())
    if high - low < 1e-6:
        return image.copy()
    normalized = np.clip((result - low) * 255 / (high - low), 0, 255).astype(np.uint8)
    return cv2.cvtColor(normalized, cv2.COLOR_GRAY2BGR)
