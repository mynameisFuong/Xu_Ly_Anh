"""Crop evidence to the confirmed face box instead of retaining the full frame."""

import cv2
import numpy as np

from ai_pipeline.preprocessing import decode_bgr_image, transform_box


def face_evidence(image_bytes, box):
    frame = decode_bgr_image(image_bytes)
    if frame is None or box is None:
        raise ValueError("Missing evidence image or face box")
    clipped = transform_box(box, np.eye(3), frame.shape)
    if clipped is None:
        raise ValueError("Invalid evidence face box")
    x, y, width, height = clipped
    ok, encoded = cv2.imencode(".jpg", frame[y:y + height, x:x + width], [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not ok:
        raise ValueError("Cannot encode evidence face")
    return encoded.tobytes()
