"""Pure image transforms. Coordinates always retain a path back to the source."""

from dataclasses import dataclass
from hashlib import sha256
import json
import math

import cv2
import numpy as np


@dataclass(frozen=True)
class PreprocessingOptions:
    mode: str = "off"
    align_eyes: bool = True
    normalize_lighting: bool = True
    search_rotations: bool = True
    search_rolls: bool = True
    mirror_input: bool = False
    max_roll_degrees: float = 40.0

    @property
    def profile(self) -> str:
        values = dict(vars(self))
        values.pop("mode")
        payload = json.dumps(values, sort_keys=True).encode()
        return "pre-v1-" + sha256(payload).hexdigest()[:10]


@dataclass(frozen=True)
class PreparedFrame:
    image: np.ndarray
    source_to_image: np.ndarray
    operations: tuple[str, ...] = ()


def validate_bgr(image: np.ndarray) -> None:
    if not isinstance(image, np.ndarray) or image.dtype != np.uint8:
        raise ValueError("Expected uint8 BGR image")
    if image.ndim != 3 or image.shape[2] != 3 or min(image.shape[:2]) == 0:
        raise ValueError("Expected nonempty H x W x 3 BGR image")


def orient_image(image: np.ndarray, *, rotation: int = 0, mirror: bool = False) -> PreparedFrame:
    """Apply explicit metadata/configuration, never infer a horizontal reflection."""
    validate_bgr(image)
    height, width = image.shape[:2]
    matrix = np.eye(3, dtype=np.float64)
    output = image.copy()
    operations = []
    if mirror:
        output = cv2.flip(output, 1)
        matrix = np.array([[-1, 0, width - 1], [0, 1, 0], [0, 0, 1]], dtype=np.float64)
        operations.append("unmirror")
    if rotation == 90:
        output = cv2.rotate(output, cv2.ROTATE_90_CLOCKWISE)
        rotate = np.array([[0, -1, height - 1], [1, 0, 0], [0, 0, 1]], dtype=np.float64)
    elif rotation == 180:
        output = cv2.rotate(output, cv2.ROTATE_180)
        rotate = np.array([[-1, 0, width - 1], [0, -1, height - 1], [0, 0, 1]], dtype=np.float64)
    elif rotation == 270:
        output = cv2.rotate(output, cv2.ROTATE_90_COUNTERCLOCKWISE)
        rotate = np.array([[0, 1, 0], [-1, 0, width - 1], [0, 0, 1]], dtype=np.float64)
    elif rotation == 0:
        rotate = np.eye(3)
    else:
        raise ValueError("Rotation must be 0, 90, 180 or 270 degrees clockwise")
    if rotation:
        operations.append(f"rotate-{rotation}")
    return PreparedFrame(np.ascontiguousarray(output), rotate @ matrix, tuple(operations))


def transform_box(box, matrix: np.ndarray, output_shape) -> tuple[int, int, int, int] | None:
    """Transform all four pixel corners of an xywh box, then clip safely."""
    x, y, width, height = box
    if width <= 0 or height <= 0:
        return None
    corners = np.array([[x, y, 1], [x + width - 1, y, 1],
                        [x, y + height - 1, 1], [x + width - 1, y + height - 1, 1]], dtype=np.float64)
    mapped = corners @ matrix.T
    if not np.isfinite(mapped).all() or np.any(np.abs(mapped[:, 2]) < 1e-10):
        return None
    mapped = mapped[:, :2] / mapped[:, 2:3]
    h, w = output_shape[:2]
    left = max(0, int(np.floor(mapped[:, 0].min() + 1e-7)))
    top = max(0, int(np.floor(mapped[:, 1].min() + 1e-7)))
    right = min(w, int(np.ceil(mapped[:, 0].max() - 1e-7)) + 1)
    bottom = min(h, int(np.ceil(mapped[:, 1].max() - 1e-7)) + 1)
    return (left, top, right - left, bottom - top) if right > left and bottom > top else None


def rotate_roll(prepared: PreparedFrame, angle: float) -> PreparedFrame:
    """Mở rộng canvas để tìm mặt bị nghiêng; luôn lưu phép biến đổi ngược."""
    h, w = prepared.image.shape[:2]
    matrix = cv2.getRotationMatrix2D(((w - 1) / 2, (h - 1) / 2), angle, 1)
    radians = math.radians(angle)
    out_w = int(math.ceil(w * abs(math.cos(radians)) + h * abs(math.sin(radians))))
    out_h = int(math.ceil(h * abs(math.cos(radians)) + w * abs(math.sin(radians))))
    matrix[:, 2] += [(out_w - w) / 2, (out_h - h) / 2]
    image = cv2.warpAffine(prepared.image, matrix, (out_w, out_h), flags=cv2.INTER_LINEAR,
                           borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0))
    return PreparedFrame(image, np.vstack([matrix, [0, 0, 1]]) @ prepared.source_to_image,
                         prepared.operations + (f"detect-roll-{angle:g}",))


def source_box(prepared: PreparedFrame, box, source_shape):
    return transform_box(box, np.linalg.inv(prepared.source_to_image), source_shape)


def align_eyes(prepared: PreparedFrame, landmarks: dict, *, max_roll_degrees: float = 40) -> PreparedFrame:
    eyes = [np.asarray(landmarks.get(name, []), dtype=np.float64) for name in ("left_eye", "right_eye")]
    if any(eye.ndim != 2 or eye.shape[1] != 2 or len(eye) < 2 or not np.isfinite(eye).all() for eye in eyes):
        raise ValueError("Reliable eye landmarks are unavailable")
    centers = sorted((eye.mean(axis=0) for eye in eyes), key=lambda point: point[0])
    left, right = centers
    distance = float(np.linalg.norm(right - left))
    if distance < 8:
        raise ValueError("Eye landmarks are too close")
    h, w = prepared.image.shape[:2]
    if any(not (0 <= point[0] < w and 0 <= point[1] < h) for point in centers):
        raise ValueError("Eye landmarks lie outside the image")
    angle = math.degrees(math.atan2(right[1] - left[1], right[0] - left[0]))
    if abs(angle) > max_roll_degrees:
        raise ValueError("Head roll exceeds the safe alignment range")
    if abs(angle) < 0.5:
        return prepared
    center = tuple(float(value) for value in (left + right) / 2)
    affine = cv2.getRotationMatrix2D(center, angle, 1.0)
    image = cv2.warpAffine(prepared.image, affine, (w, h), flags=cv2.INTER_LINEAR,
                           borderMode=cv2.BORDER_REFLECT_101)
    matrix = np.vstack([affine, [0, 0, 1]])
    return PreparedFrame(image, matrix @ prepared.source_to_image, prepared.operations + ("align-eyes",))


def normalize_lighting(image: np.ndarray) -> np.ndarray:
    validate_bgr(image)
    ycrcb = cv2.cvtColor(image, cv2.COLOR_BGR2YCrCb)
    ycrcb[:, :, 0] = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(ycrcb[:, :, 0])
    return np.ascontiguousarray(cv2.cvtColor(ycrcb, cv2.COLOR_YCrCb2BGR))


def kirsch_edges(image: np.ndarray) -> np.ndarray:
    """Optional diagnostic branch; never substitute this for an RGB face."""
    validate_bgr(image)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    ring = [(0, 0), (0, 1), (0, 2), (1, 2), (2, 2), (2, 1), (2, 0), (1, 0)]
    responses = []
    for direction in range(8):
        kernel = np.full((3, 3), -3, dtype=np.float32)
        kernel[1, 1] = 0
        for offset in range(3):
            kernel[ring[(direction + offset) % 8]] = 5
        responses.append(cv2.filter2D(gray, cv2.CV_32F, kernel))
    return np.maximum.reduce(responses).astype(np.float32)
