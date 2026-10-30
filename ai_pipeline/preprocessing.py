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
    version: str = "v1"
    lighting_method: str = "adaptive"
    denoise_method: str = "off"
    v2_align_eyes: bool = False
    roi_padding: float = 0.25
    gamma_min: float = 0.65
    gamma_max: float = 1.4
    clahe_clip_limit: float = 1.5
    max_detection_attempts: int = 8
    shadow_v2: bool = False
    shadow_sample_rate: float = 1.0

    def __post_init__(self):
        if self.mode not in {"off", "shadow", "enforce"} or self.version not in {"v1", "v2"}:
            raise ValueError("Invalid preprocessing mode or version")
        if self.lighting_method not in {"none", "adaptive", "gamma", "clahe"}:
            raise ValueError("Unsupported lighting method")
        if self.denoise_method not in {"off", "adaptive", "median", "bilateral"}:
            raise ValueError("Unsupported denoising method")
        if not (0 < self.gamma_min <= 1 <= self.gamma_max <= 2):
            raise ValueError("Gamma bounds must contain 1 and lie in (0, 2]")
        if not (0 <= self.roi_padding <= 0.5 and 0 < self.clahe_clip_limit <= 4):
            raise ValueError("Unsafe ROI padding or CLAHE clip limit")
        if not (0 < self.max_roll_degrees <= 60 and 1 <= self.max_detection_attempts <= 8):
            raise ValueError("Unsafe roll or detection search limit")
        if not 0 <= self.shadow_sample_rate <= 1:
            raise ValueError("Shadow sample rate must lie in [0, 1]")

    @property
    def profile(self) -> str:
        # Keep the original hash byte-for-byte: existing templates remain usable.
        legacy = ("align_eyes", "normalize_lighting", "search_rotations", "search_rolls",
                  "mirror_input", "max_roll_degrees")
        values = {name: getattr(self, name) for name in legacy}
        if self.version == "v2":
            values = {name: value for name, value in vars(self).items()
                      if name not in {"mode", "shadow_v2", "shadow_sample_rate", "align_eyes"}}
        payload = json.dumps(values, sort_keys=True).encode()
        return f"pre-{self.version}-" + sha256(payload).hexdigest()[:10]


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


def decode_bgr_image(image_bytes: bytes) -> np.ndarray | None:
    """OpenCV applies EXIF once. All downstream coordinates use this decoded image."""
    encoded = np.frombuffer(image_bytes, dtype=np.uint8)
    try:
        return cv2.imdecode(encoded, cv2.IMREAD_COLOR) if encoded.size else None
    except cv2.error:
        return None


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


def align_eyes(prepared: PreparedFrame, landmarks: dict, *, max_roll_degrees: float = 40,
               source_image: np.ndarray | None = None) -> PreparedFrame:
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
    matrix = np.vstack([affine, [0, 0, 1]])
    combined = matrix @ prepared.source_to_image
    # v2 renders from native pixels once, even after a detection rescue warp.
    pixels = prepared.image if source_image is None else source_image
    render_matrix = affine if source_image is None else combined[:2]
    image = cv2.warpAffine(pixels, render_matrix, (w, h), flags=cv2.INTER_LINEAR,
                           borderMode=cv2.BORDER_REFLECT_101)
    return PreparedFrame(image, combined, prepared.operations + ("align-eyes",))


def native_face_region(source: np.ndarray, prepared: PreparedFrame, box):
    """Return native pixels and a polygon mask, excluding rotated background."""
    x, y, w, h = box
    corners = np.array([[x, y, 1], [x + w - 1, y, 1],
                        [x + w - 1, y + h - 1, 1], [x, y + h - 1, 1]], np.float64)
    mapped = corners @ np.linalg.inv(prepared.source_to_image).T
    points = mapped[:, :2] / mapped[:, 2:3]
    sh, sw = source.shape[:2]
    if (not np.isfinite(points).all() or np.any(points < -0.5)
            or np.any(points[:, 0] > sw - 0.5) or np.any(points[:, 1] > sh - 0.5)):
        raise ValueError("Face is clipped")
    native_box = source_box(prepared, box, source.shape)
    if native_box is None:
        raise ValueError("Empty face crop")
    nx, ny, nw, nh = native_box
    mask = np.zeros((nh, nw), np.uint8)
    cv2.fillConvexPoly(mask, np.rint(points - [nx, ny]).astype(np.int32), 255)
    return source[ny:ny + nh, nx:nx + nw], mask


def enhance_face_region(image: np.ndarray, box, metrics, options: PreprocessingOptions):
    """Quality-gated luminance/noise processing on a padded ROI; BGR uint8 out."""
    validate_bgr(image)
    x, y, w, h = box
    px, py = round(w * options.roi_padding), round(h * options.roi_padding)
    left, top = max(0, x - px), max(0, y - py)
    right, bottom = min(image.shape[1], x + w + px), min(image.shape[0], y + h + py)
    if right <= left or bottom <= top:
        raise ValueError("Empty face crop")
    roi = image[top:bottom, left:right].copy()
    operations = []
    method = options.denoise_method
    if method == "adaptive":
        method = "median" if metrics.impulse_fraction >= 0.01 else (
            "bilateral" if metrics.noise_sigma >= 4 else "off")
    # Explicit methods are still gated: clean input should not lose texture.
    if method == "median" and metrics.impulse_fraction >= 0.01:
        roi = cv2.medianBlur(roi, 3)
        operations.append("median-3")
    elif method == "bilateral" and metrics.noise_sigma >= 4:
        roi = cv2.bilateralFilter(roi, 5, 15, 3)
        operations.append("bilateral-5")
    method = options.lighting_method if options.normalize_lighting else "none"
    if method == "adaptive":
        method = "gamma" if metrics.brightness < 90 or metrics.brightness > 175 else (
            "clahe" if metrics.contrast < 55 else "none")
    ycrcb = cv2.cvtColor(roi, cv2.COLOR_BGR2YCrCb)
    luminance = ycrcb[:, :, 0]
    if method == "gamma" and (metrics.brightness < 90 or metrics.brightness > 175):
        mean = np.clip(metrics.brightness / 255, 1 / 255, 254 / 255)
        gamma = float(np.clip(math.log(120 / 255) / math.log(mean), options.gamma_min, options.gamma_max))
        lut = np.rint(255 * (np.arange(256, dtype=np.float64) / 255) ** gamma).astype(np.uint8)
        ycrcb[:, :, 0] = cv2.LUT(luminance, lut)
        operations.append("gamma")
    elif method == "clahe" and metrics.contrast < 55:
        # Grid count adapts to small ROIs to avoid tiny noisy tiles.
        grid = max(2, min(8, min(roi.shape[:2]) // 24))
        ycrcb[:, :, 0] = cv2.createCLAHE(options.clahe_clip_limit, (grid, grid)).apply(luminance)
        operations.append("clahe-roi")
    if not operations:
        return image.copy(), ()
    if "gamma" in operations or "clahe-roi" in operations:
        roi = cv2.cvtColor(ycrcb, cv2.COLOR_YCrCb2BGR)
    output = image.copy()
    output[top:bottom, left:right] = roi
    return np.ascontiguousarray(output), tuple(operations)


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
