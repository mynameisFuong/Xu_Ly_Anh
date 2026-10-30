"""Multi-face overlays for native camera clients; web uses its own DOM layer."""

from functools import lru_cache
from pathlib import Path
import unicodedata

import cv2
import numpy as np


@lru_cache(maxsize=1)
def _font():
    try:
        from PIL import ImageFont

        for path in (Path("C:/Windows/Fonts/segoeui.ttf"),
                     Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")):
            if path.is_file():
                return ImageFont.truetype(str(path), 17)
    except (ImportError, OSError):
        pass
    return None


def draw_stream_faces(frame, response, *, reference_frame=None):
    output = frame.copy()
    faces = response.get("faces", [])
    if not faces and response.get("face_box"):
        faces = [response]
    if (response.get("frame_width", frame.shape[1]), response.get("frame_height", frame.shape[0])) != (frame.shape[1], frame.shape[0]):
        faces = []
    labels = []
    current_small = cv2.resize(frame, (128, 96), interpolation=cv2.INTER_AREA) if reference_frame is not None else None
    reference_small = cv2.resize(reference_frame, (128, 96), interpolation=cv2.INTER_AREA) if reference_frame is not None else None
    if not faces:
        cv2.rectangle(output, (10, 10), (frame.shape[1] - 10, frame.shape[0] - 10), (107, 201, 242), 2)
    for face in faces:
        box = face.get("face_box")
        if not box or len(box) != 4:
            continue
        x, y, w, h = (int(value) for value in box)
        recognized = face.get("decision") == "recognized" and face.get("attendance")
        if recognized and reference_small is not None:
            sx, sy = 128 / frame.shape[1], 96 / frame.shape[0]
            left, right = max(0, int((x + w * 0.15) * sx)), min(128, int(np.ceil((x + w * 0.85) * sx)))
            top, bottom = max(0, int((y + h * 0.15) * sy)), min(96, int(np.ceil((y + h * 0.85) * sy)))
            delta = np.abs(current_small[top:bottom, left:right].astype(np.int16) - reference_small[top:bottom, left:right])
            if not delta.size or delta.mean() > 10 or np.mean(delta > 18) > 0.15:
                recognized = False
        color = (187, 224, 85) if recognized else (107, 201, 242)
        cv2.rectangle(output, (x, y), (x + w, y + h), color, 2)
        text = face.get("full_name", "") if recognized else "Đang nhận diện"
        labels.append((max(0, x), max(0, y - 26), text))
    font = _font()
    if font is not None:
        from PIL import Image, ImageDraw

        image = Image.fromarray(cv2.cvtColor(output, cv2.COLOR_BGR2RGB))
        draw = ImageDraw.Draw(image)
        for x, y, text in labels:
            draw.text((x, y), text, font=font, fill="white", stroke_width=2, stroke_fill="black")
        return cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)
    for x, y, text in labels:
        ascii_text = unicodedata.normalize("NFKD", text.replace("Đ", "D").replace("đ", "d")).encode("ascii", "ignore").decode()
        cv2.putText(output, ascii_text, (x, y + 18), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
    return output
