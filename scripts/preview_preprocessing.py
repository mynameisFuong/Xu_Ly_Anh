"""Export image-processing stages for a consenting face image; never changes the DB."""

import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai_pipeline.experiments import multiscale_retinex, tan_triggs
from ai_pipeline.preprocessing import (
    PreprocessingOptions, align_eyes, decode_bgr_image, enhance_face_region, kirsch_edges,
    orient_image, transform_box, validate_bgr,
)
from ai_pipeline.quality import assess_face_quality_v2, measure_face_quality
from ai_pipeline.recognition import FaceRecognizer


def render_previews(image, box, options, *, landmarks=None):
    """Render BGR stages and monochrome diagnostics without modifying input."""
    validate_bgr(image)
    x, y, w, h = box
    if w < 1 or h < 1 or x < 0 or y < 0 or x + w > image.shape[1] or y + h > image.shape[0]:
        raise ValueError("The detected face box must lie inside the source image")
    if min(w, h) < 16:
        raise ValueError("Face is too small for image diagnostics")
    native = image[y:y + h, x:x + w]
    quality = assess_face_quality_v2(native)
    metrics = quality.metrics or measure_face_quality(native)
    prepared = orient_image(image)
    work_box = box
    if landmarks is not None:
        for name in ("left_eye", "right_eye"):
            points = np.asarray(landmarks.get(name, []), np.float64)
            if (points.ndim != 2 or points.shape[1] != 2 or not np.isfinite(points).all()
                    or np.any(points < [x, y]) or np.any(points > [x + w - 1, y + h - 1])):
                raise ValueError("Eye landmarks lie outside the detected face")
        aligned = align_eyes(prepared, landmarks, max_roll_degrees=options.max_roll_degrees,
                             source_image=image)
        mapped = transform_box(box, aligned.source_to_image, image.shape)
        corners = np.array([[x, y, 1], [x + w - 1, y, 1], [x, y + h - 1, 1],
                            [x + w - 1, y + h - 1, 1]]) @ aligned.source_to_image.T
        if (mapped is None or np.any(corners[:, :2] < 0) or np.any(corners[:, 0] >= image.shape[1])
                or np.any(corners[:, 1] >= image.shape[0])):
            raise ValueError("Eye alignment clipped the face")
        prepared, work_box = aligned, mapped
    enhanced, operations = enhance_face_region(prepared.image, work_box, metrics, options)
    prepared_face = prepared.image[work_box[1]:work_box[1] + work_box[3],
                                   work_box[0]:work_box[0] + work_box[2]]
    edge = kirsch_edges(prepared_face)
    edge_limit = max(float(np.percentile(edge, 99)), 1.0)
    edge_preview = np.clip(edge * 255 / edge_limit, 0, 255).astype(np.uint8)
    stages = {
        "01-source-bgr.png": image.copy(),
        "02-geometry-bgr.png": prepared.image.copy(),
        "03-enhanced-bgr.png": enhanced,
        "04-kirsch-diagnostic.png": edge_preview,
        "05-retinex-experiment.png": multiscale_retinex(prepared_face),
        "06-tan-triggs-experiment.png": tan_triggs(prepared_face),
    }
    metadata = {
        "face_box_source_xywh": list(box), "face_box_processed_xywh": list(work_box),
        "quality_accepted_on_source": quality.accepted, "quality_reason": quality.reason,
        "source_metrics": vars(metrics),
        "geometry_operations": list(prepared.operations), "enhancement_operations": list(operations),
        "profile": options.profile, "notes": [
            "Retinex, Tan-Triggs and Kirsch are diagnostic experiments, not dlib input.",
            "The preview renders a selected face; it is not an attendance or recognition decision.",
        ],
    }
    return stages, metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path, help="Consented source image")
    parser.add_argument("output", type=Path, help="Private output directory for face images")
    parser.add_argument("--version", choices=("v2", "v3"), default="v3")
    parser.add_argument("--lighting", choices=("none", "adaptive", "gamma", "clahe"), default="adaptive")
    parser.add_argument("--denoise", choices=("off", "adaptive", "median", "bilateral"), default="off")
    parser.add_argument("--align-eyes", action="store_true", help="Experiment with extra eye alignment")
    args = parser.parse_args()
    image = decode_bgr_image(args.image.read_bytes())
    if image is None:
        parser.error("Cannot decode source image")
    recognizer = FaceRecognizer()
    boxes = recognizer.detect_faces(image)
    if not boxes:
        parser.error("No face detected")
    box = max(boxes, key=lambda candidate: candidate[2] * candidate[3])
    landmarks = None
    if args.align_eyes:
        if recognizer._face_recognition is None:
            parser.error("Eye alignment preview requires the dlib Face ID engine")
        x, y, w, h = box
        found = recognizer._face_recognition.face_landmarks(cv2.cvtColor(image, cv2.COLOR_BGR2RGB),
                                                            [(y, x + w, y + h, x)], model="large")
        if not found:
            parser.error("Reliable eye landmarks are unavailable")
        landmarks = found[0]
    options = replace(PreprocessingOptions(version=args.version), lighting_method=args.lighting,
                      denoise_method=args.denoise, v2_align_eyes=args.align_eyes)
    try:
        stages, metadata = render_previews(image, box, options, landmarks=landmarks)
    except (ValueError, cv2.error) as exc:
        parser.error(str(exc))
    args.output.mkdir(parents=True, exist_ok=True)
    for name, pixels in stages.items():
        if not cv2.imwrite(str(args.output / name), pixels):
            parser.error(f"Cannot write {name}")
    (args.output / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(stages)} image stages and metadata to {args.output}")


if __name__ == "__main__":
    main()
