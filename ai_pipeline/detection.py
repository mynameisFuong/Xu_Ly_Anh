"""Detector hỗ trợ góc khó; không thay ảnh nguồn cho embedding hoặc PAD."""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

import cv2
import numpy as np

from ai_pipeline.preprocessing import normalize_lighting


YUNET_COMMIT = "f12e12798e8314f7c074a6656816c048dcc95b7a"
YUNET_FILENAME = "face_detection_yunet_2023mar.onnx"
YUNET_SHA256 = "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"
YUNET_BASE_URL = f"https://media.githubusercontent.com/media/opencv/opencv_zoo/{YUNET_COMMIT}/models/face_detection_yunet/"


@dataclass(frozen=True)
class FaceDetectionOptions:
    backend: str = "hog"
    model_path: Path = Path("storage/face-models") / YUNET_FILENAME
    score_threshold: float = 0.9
    max_side: int = 640


def box_iou(left, right):
    lx, ly, lw, lh = left
    rx, ry, rw, rh = right
    intersection = max(0, min(lx + lw, rx + rw) - max(lx, rx)) * max(0, min(ly + lh, ry + rh) - max(ly, ry))
    return intersection / max(1, lw * lh + rw * rh - intersection)


class HybridFaceDetector:
    """Được gọi dưới lock của FaceRecognizer vì OpenCV DNN giữ state input."""

    def __init__(self, options: FaceDetectionOptions):
        self.options = options
        self._detector = None
        self.error = None
        self.rescued_frames = 0
        self.lighting_rescues = 0
        self.extra_face_frames = 0
        try:
            if not 0.5 <= options.score_threshold < 1 or not 320 <= options.max_side <= 1280:
                raise ValueError("invalid-configuration")
            if sha256(options.model_path.read_bytes()).hexdigest() != YUNET_SHA256:
                raise ValueError("checksum-mismatch")
            self._detector = cv2.FaceDetectorYN.create(
                str(options.model_path), "", (320, 320), options.score_threshold, 0.3, 5000,
                cv2.dnn.DNN_BACKEND_OPENCV, cv2.dnn.DNN_TARGET_CPU,
            )
        except OSError:
            self.error = "model-missing"
        except (ValueError, cv2.error):
            self.error = "model-invalid"

    def status(self):
        return {"backend": self.options.backend, "yunet_ready": self._detector is not None and self.error is None,
                "error": self.error, "rescued_frames": self.rescued_frames,
                "lighting_rescues": self.lighting_rescues, "extra_face_frames": self.extra_face_frames}

    def _boxes(self, frame):
        height, width = frame.shape[:2]
        scale = min(1.0, self.options.max_side / max(height, width))
        work = cv2.resize(frame, (max(1, round(width * scale)), max(1, round(height * scale))),
                          interpolation=cv2.INTER_AREA) if scale < 1 else frame
        wh, ww = work.shape[:2]
        self._detector.setInputSize((ww, wh))
        _count, faces = self._detector.detect(np.ascontiguousarray(work))
        boxes = []
        for row in faces if faces is not None else ():
            if len(row) != 15 or not np.isfinite(row).all() or row[14] < self.options.score_threshold:
                continue
            x, y, w, h = (float(value) for value in row[:4])
            if w <= 0 or h <= 0:
                continue
            # Box DNN dùng tọa độ liên tục; map cả biên phải/dưới trước khi làm tròn.
            left, top = max(0, int(np.floor(x * width / ww))), max(0, int(np.floor(y * height / wh)))
            right = min(width, int(np.ceil((x + w) * width / ww)))
            bottom = min(height, int(np.ceil((y + h) * height / wh)))
            if right > left and bottom > top:
                boxes.append((left, top, right - left, bottom - top))
        return boxes

    def detect(self, frame, hog_boxes):
        if self._detector is None:
            return list(hog_boxes)
        try:
            boxes = self._boxes(frame)
            if not boxes and not hog_boxes:
                boxes = self._boxes(normalize_lighting(frame))
                if boxes:
                    self.lighting_rescues += 1
            self.error = None
        except cv2.error:
            self.error = "inference-unavailable"
            return list(hog_boxes)
        # Giữ box HOG đã dùng để tạo template; không chọn mặt lớn nhất khi có nhiều người.
        merged = list(hog_boxes)
        for box in boxes:
            if not any(box_iou(box, existing) >= 0.3 for existing in merged):
                merged.append(box)
        if boxes and not hog_boxes:
            self.rescued_frames += 1
        if len(merged) > len(hog_boxes) and hog_boxes:
            self.extra_face_frames += 1
        return merged
