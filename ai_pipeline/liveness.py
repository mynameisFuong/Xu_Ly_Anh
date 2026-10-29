"""Versioned HOG + spatial DFT presentation-attack baseline.

No bundled weights and no heuristic 'live' default. SVM margins are not probabilities.
"""

from dataclasses import dataclass
from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path
from threading import Lock

import cv2
import numpy as np

from ai_pipeline.preprocessing import transform_box, validate_bgr

FEATURE_VERSION = "hog-dft-v1"
PAD_SIZE = 128
CONTEXT_RATIO = 1.35
HOG_DIM = 8100
FEATURE_DIM = HOG_DIM + 16 + 8 + 3


@dataclass(frozen=True)
class LivenessResult:
    status: str
    score: float | None = None
    reason: str | None = None
    model_version: str | None = None


def pad_crop(frame: np.ndarray, box) -> np.ndarray:
    validate_bgr(frame)
    x, y, width, height = box
    expanded = (int(np.floor(x - width * (CONTEXT_RATIO - 1) / 2)),
                int(np.floor(y - height * (CONTEXT_RATIO - 1) / 2)),
                int(np.ceil(width * CONTEXT_RATIO)), int(np.ceil(height * CONTEXT_RATIO)))
    clipped = transform_box(expanded, np.eye(3), frame.shape)
    if clipped is None:
        raise ValueError("Invalid liveness crop")
    x, y, width, height = clipped
    return frame[y:y + height, x:x + width].copy()


def extract_features(face_bgr: np.ndarray) -> np.ndarray:
    validate_bgr(face_bgr)
    gray = cv2.cvtColor(face_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, (PAD_SIZE, PAD_SIZE), interpolation=cv2.INTER_AREA)
    hog = cv2.HOGDescriptor((128, 128), (16, 16), (8, 8), (8, 8), 9)
    spatial = hog.compute(gray).ravel()
    signal = gray.astype(np.float32)
    signal -= signal.mean()
    signal *= np.outer(np.hanning(PAD_SIZE), np.hanning(PAD_SIZE)).astype(np.float32)
    power = np.log1p(np.abs(np.fft.fftshift(np.fft.fft2(signal))) ** 2)
    power[PAD_SIZE // 2, PAD_SIZE // 2] = 0
    total = float(power.sum())
    distribution = power / max(total, 1e-12)
    yy, xx = np.mgrid[-PAD_SIZE // 2:PAD_SIZE // 2, -PAD_SIZE // 2:PAD_SIZE // 2]
    radius = np.hypot(xx, yy) / (PAD_SIZE / np.sqrt(2))
    angle = (np.arctan2(yy, xx) + np.pi) / (2 * np.pi)
    radial = np.histogram(radius, bins=16, range=(0, 1.00001), weights=distribution)[0]
    angular = np.histogram(angle, bins=8, range=(0, 1.00001), weights=distribution)[0]
    nonzero = distribution[distribution > 0]
    statistics = [distribution[radius > 0.5].sum(), distribution.max(),
                  -(nonzero * np.log(nonzero)).sum() / np.log(PAD_SIZE ** 2)]
    features = np.concatenate([spatial, radial, angular, statistics]).astype(np.float32)
    if features.shape != (FEATURE_DIM,) or not np.isfinite(features).all():
        raise ValueError("Invalid PAD feature vector")
    return features


class LivenessDetector:
    def __init__(self, model_dir: str | Path | None = None):
        self._lock = Lock()
        self._svm = None
        self.error = "Liveness model is not configured"
        self.approved = False
        self.model_version = None
        if model_dir is None:
            return
        try:
            directory = Path(model_dir)
            manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
            if manifest["feature_version"] != FEATURE_VERSION or manifest["feature_dim"] != FEATURE_DIM:
                raise ValueError("Unsupported liveness feature profile")
            if manifest["pad_size"] != PAD_SIZE or manifest["context_ratio"] != CONTEXT_RATIO:
                raise ValueError("Unsupported liveness crop profile")
            if manifest.get("labels") != {"live": 1, "spoof": 0}:
                raise ValueError("Unsupported liveness label mapping")
            for filename in ("svm.xml", "normalizer.npz"):
                if sha256((directory / filename).read_bytes()).hexdigest() != manifest["sha256"][filename]:
                    raise ValueError("Liveness artifact checksum mismatch")
            with np.load(directory / "normalizer.npz", allow_pickle=False) as arrays:
                self.mean = arrays["mean"].astype(np.float32)
                self.scale = arrays["scale"].astype(np.float32)
            if self.mean.shape != (FEATURE_DIM,) or self.scale.shape != (FEATURE_DIM,):
                raise ValueError("Invalid liveness normalizer dimensions")
            if not np.isfinite(self.mean).all() or not np.isfinite(self.scale).all() or np.any(self.scale <= 0):
                raise ValueError("Invalid liveness normalizer")
            self.direction = float(manifest["margin_direction"])
            self.live_threshold = float(manifest["live_threshold"])
            self.spoof_threshold = float(manifest["spoof_threshold"])
            if self.direction not in (-1, 1) or not np.isfinite([self.live_threshold, self.spoof_threshold]).all():
                raise ValueError("Invalid liveness thresholds")
            if self.spoof_threshold >= self.live_threshold:
                raise ValueError("Liveness thresholds must leave an uncertainty interval")
            self.model_version = str(manifest["model_version"])
            self.approved = manifest.get("approved_for_enforcement") is True
            svm = cv2.ml.SVM_load(str(directory / "svm.xml"))
            if not svm.isTrained() or svm.getVarCount() != FEATURE_DIM:
                raise ValueError("Invalid liveness SVM dimensions")
            if svm.getType() != cv2.ml.SVM_C_SVC or svm.getKernelType() != cv2.ml.SVM_LINEAR:
                raise ValueError("Expected a linear C-SVC liveness model")
            self._svm = svm
            self.error = None
        except (OSError, ValueError, KeyError, TypeError, cv2.error):
            self.error = "Liveness model is missing, corrupt or incompatible"

    @property
    def ready(self) -> bool:
        return self._svm is not None

    def evaluate(self, frame: np.ndarray, box, *, require_approved: bool = False) -> LivenessResult:
        if not self.ready or (require_approved and not self.approved):
            reason = self.error or "Liveness model has not been approved for enforcement"
            return LivenessResult("unavailable", reason=reason, model_version=self.model_version)
        try:
            features = extract_features(pad_crop(frame, box))
            normalized = np.ascontiguousarray(((features - self.mean) / self.scale)[None, :], dtype=np.float32)
            if not np.isfinite(normalized).all():
                raise ValueError("Invalid normalized PAD features")
            with self._lock:
                _, margin = self._svm.predict(normalized, flags=cv2.ml.STAT_MODEL_RAW_OUTPUT)
            score = self.direction * float(margin[0, 0])
            if not np.isfinite(score):
                raise ValueError("Invalid liveness score")
            status = "live" if score >= self.live_threshold else "spoof" if score <= self.spoof_threshold else "uncertain"
            return LivenessResult(status, score=score, model_version=self.model_version)
        except (ValueError, cv2.error, FloatingPointError):
            return LivenessResult("unavailable", reason="Liveness analysis failed", model_version=self.model_version)


@lru_cache(maxsize=4)
def load_liveness_detector(model_dir: str | None) -> LivenessDetector:
    """Artifacts are immutable for a process lifetime; restart after deployment."""
    return LivenessDetector(model_dir)
