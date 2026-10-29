"""PAD MiniFASNet hai tỉ lệ, giữ đúng BGR 0..255 và lớp live=1 của upstream."""

from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path
from threading import Lock

import cv2
import numpy as np

from ai_pipeline.liveness import LivenessResult
from ai_pipeline.preprocessing import validate_bgr


MODEL_SPECS = (
    ("MiniFASNetV2.onnx", 2.7, "b32929adc2d9c34b9486f8c4c7bc97c1b69bc0ea9befefc380e4faae4e463907"),
    ("MiniFASNetV1SE.onnx", 4.0, "ebab7f90c7833fbccd46d3a555410e78d969db5438e169b6524be444862b3676"),
)
MODEL_VERSION = "minifasnet-v2-v1se-onnx-v1"
RELEASE_URL = "https://github.com/yakhyo/face-anti-spoofing/releases/download/weights/"


def minifasnet_tensor(frame, box, scale):
    """Crop có ngữ cảnh: dịch vùng crop vào ảnh thay vì cắt mất biên như clip đơn."""
    validate_bgr(frame)
    x, y, width, height = box
    h, w = frame.shape[:2]
    if not np.isfinite([x, y, width, height, scale]).all() or min(width, height) <= 0:
        raise ValueError("Invalid PAD crop")
    if x < 0 or y < 0 or x + width > w or y + height > h or scale < 1:
        raise ValueError("PAD box must lie inside the source")
    factor = min((h - 1) / height, (w - 1) / width, scale)
    crop_w, crop_h = width * factor, height * factor
    left = min(max(x + width / 2 - crop_w / 2, 0), w - 1 - crop_w)
    top = min(max(y + height / 2 - crop_h / 2, 0), h - 1 - crop_h)
    right, bottom = left + crop_w, top + crop_h
    crop = frame[int(top):int(bottom) + 1, int(left):int(right) + 1]
    resized = cv2.resize(crop, (80, 80), interpolation=cv2.INTER_LINEAR)
    return np.ascontiguousarray(resized.transpose(2, 0, 1)[None], dtype=np.float32)


class MiniFASNetDetector:
    def __init__(self, model_dir, *, live_threshold=0.9, allow_pretrained=False):
        self._sessions = []
        self._lock = Lock()
        self.approved = False
        self.model_version = MODEL_VERSION
        self.error = "MiniFASNet models are missing, corrupt or incompatible"
        self.threshold = live_threshold
        self.allow_pretrained = allow_pretrained
        try:
            import onnxruntime as ort

            if not 0.5 < live_threshold < 1:
                raise ValueError("Invalid MiniFASNet live threshold")
            directory = Path(model_dir)
            manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
            if manifest["model_version"] != MODEL_VERSION:
                raise ValueError("Unsupported MiniFASNet profile")
            self.approved = manifest.get("approved_for_enforcement") is True
            options = ort.SessionOptions()
            options.intra_op_num_threads = 1
            options.inter_op_num_threads = 1
            for filename, scale, checksum in MODEL_SPECS:
                data = (directory / filename).read_bytes()
                if sha256(data).hexdigest() != checksum:
                    raise ValueError("MiniFASNet checksum mismatch")
                try:
                    session = ort.InferenceSession(data, sess_options=options, providers=["CPUExecutionProvider"])
                except Exception as exc:
                    # ONNX Runtime có các lớp lỗi native riêng theo phiên bản.
                    raise ValueError("Cannot load MiniFASNet session") from exc
                inputs, outputs = session.get_inputs(), session.get_outputs()
                if len(inputs) != 1 or inputs[0].shape[1:] != [3, 80, 80] or inputs[0].type != "tensor(float)":
                    raise ValueError("Unsupported MiniFASNet input")
                if len(outputs) != 1 or outputs[0].shape[-1] != 3:
                    raise ValueError("Unsupported MiniFASNet output")
                self._sessions.append((session, inputs[0].name, outputs[0].name, scale))
            self.error = None
        except (ImportError, OSError, ValueError, KeyError, TypeError, RuntimeError):
            self._sessions = []

    @property
    def ready(self):
        return len(self._sessions) == len(MODEL_SPECS)

    @property
    def can_enforce(self):
        return self.ready and (self.approved or self.allow_pretrained)

    def evaluate(self, frame, box, *, require_approved=False):
        if not self.ready or (require_approved and not self.can_enforce):
            return LivenessResult("unavailable", reason=self.error or "Model requires field evaluation approval",
                                  model_version=self.model_version)
        try:
            scores = []
            with self._lock:
                for session, input_name, output_name, scale in self._sessions:
                    tensor = minifasnet_tensor(frame, box, scale)
                    try:
                        output = session.run([output_name], {input_name: tensor})[0]
                    except Exception as exc:
                        raise ValueError("MiniFASNet session failed") from exc
                    logits = np.asarray(output, dtype=np.float64)
                    if logits.shape != (1, 3) or not np.isfinite(logits).all():
                        raise ValueError("Invalid MiniFASNet output")
                    probability = np.exp(logits[0] - logits[0].max())
                    probability /= probability.sum()
                    scores.append(float(probability[1]))
            # Cả hai mô hình phải đồng ý; không dùng trung bình để che điểm thấp.
            score = min(scores)
            status = "live" if score >= self.threshold else "spoof" if score < 0.5 else "uncertain"
            return LivenessResult(status, score=score, model_version=self.model_version)
        except (ValueError, RuntimeError, cv2.error):
            return LivenessResult("unavailable", reason="MiniFASNet inference failed", model_version=self.model_version)


@lru_cache(maxsize=4)
def load_minifasnet_detector(model_dir, live_threshold=0.9, allow_pretrained=False):
    return MiniFASNetDetector(model_dir, live_threshold=live_threshold, allow_pretrained=allow_pretrained)
