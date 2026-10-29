
"""Train/evaluate PAD from an explicitly partitioned, consented image dataset.

Exports remain unapproved until a human reviews the evaluation report.
"""

import argparse
from collections import Counter
import csv
from hashlib import sha256
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2
import numpy as np

from ai_pipeline.liveness import CONTEXT_RATIO, FEATURE_DIM, FEATURE_VERSION, PAD_SIZE, extract_features, pad_crop
from ai_pipeline.quality import assess_face_quality
from ai_pipeline.recognition import FaceRecognizer
from ai_pipeline.preprocessing import transform_box

SPLITS = ("train", "validation", "test")
LABELS = {"live": 1, "print": 0, "replay": 0}


def read_dataset(csv_path: Path) -> list[dict]:
    with csv_path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        required = {"path", "label", "split", "subject_id", "session_id"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("CSV requires path,label,split,subject_id,session_id")
        rows = list(reader)
    if not rows:
        raise ValueError("Dataset is empty")
    subject_splits = {}
    path_splits = {}
    for row in rows:
        if row["split"] not in SPLITS or row["label"] not in LABELS:
            raise ValueError("Unsupported dataset split or label")
        if not row["subject_id"].strip() or not row["session_id"].strip():
            raise ValueError("Every sample needs a subject and capture session")
        subject = row["subject_id"].strip()
        split = row["split"]
        if subject in subject_splits and subject_splits[subject] != split:
            raise ValueError("Subject leakage across dataset splits")
        subject_splits[subject] = split
        if not row["path"].strip():
            raise ValueError("Dataset image path is empty")
        row["resolved_path"] = (csv_path.parent / row["path"]).resolve()
        path = str(row["resolved_path"]).casefold()
        if path in path_splits:
            raise ValueError("Duplicate image path in dataset")
        path_splits[path] = split
    for split in SPLITS:
        labels = {row["label"] for row in rows if row["split"] == split}
        if labels != set(LABELS):
            raise ValueError(f"Split {split} must contain live, print and replay samples")
    return rows


def load_samples(rows, recognizer):
    samples = {split: [] for split in SPLITS}
    hashes = set()
    for row in rows:
        raw = row["resolved_path"].read_bytes()
        digest = sha256(raw).hexdigest()
        if digest in hashes:
            raise ValueError("Duplicate image contents in dataset")
        hashes.add(digest)
        frame = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError("Cannot decode a dataset image")
        boxes = recognizer.detect_faces(frame)
        if len(boxes) != 1:
            raise ValueError("Every dataset image must contain exactly one detectable face")
        box = transform_box(boxes[0], np.eye(3), frame.shape)
        if box is None:
            raise ValueError("Invalid dataset face crop")
        x, y, width, height = box
        if not assess_face_quality(frame[y:y + height, x:x + width]).accepted:
            raise ValueError("Dataset image fails the runtime source-quality gate")
        samples[row["split"]].append((extract_features(pad_crop(frame, box)), row["label"]))
    return samples


def score_samples(svm, features, mean, scale, direction):
    normalized = np.ascontiguousarray((features - mean) / scale, dtype=np.float32)
    _, margins = svm.predict(normalized, flags=cv2.ml.STAT_MODEL_RAW_OUTPUT)
    return direction * margins.ravel().astype(np.float64)


def evaluation(scores, labels, threshold):
    labels = np.asarray(labels)
    accepted = scores >= threshold
    live = labels == "live"
    attacks = ~live
    return {
        "count": int(len(labels)),
        "counts_by_label": dict(Counter(labels.tolist())),
        "apcer": float(accepted[attacks].mean()),
        "bpcer": float((~accepted[live]).mean()),
        "apcer_print": float(accepted[labels == "print"].mean()),
        "apcer_replay": float(accepted[labels == "replay"].mean()),
    }


def train_and_export(samples, output_dir: Path, *, target_apcer=0.05, svm_c=1.0):
    if not 0 <= target_apcer < 0.5 or not np.isfinite(svm_c) or svm_c <= 0:
        raise ValueError("Expected target APCER in [0, 0.5) and positive finite SVM C")
    arrays = {}
    for split in SPLITS:
        values = samples.get(split, [])
        if {label for _, label in values} != set(LABELS):
            raise ValueError("Each split requires live, print and replay samples")
        features = np.asarray([feature for feature, _ in values], dtype=np.float32)
        if features.shape != (len(values), FEATURE_DIM) or not np.isfinite(features).all():
            raise ValueError("Invalid dataset feature dimensions or values")
        arrays[split] = (features, [label for _, label in values])
    train_x, train_labels = arrays["train"]
    mean = train_x.mean(axis=0)
    scale = train_x.std(axis=0)
    scale[scale < 1e-6] = 1
    normalized = np.ascontiguousarray((train_x - mean) / scale, dtype=np.float32)
    train_y = np.asarray([LABELS[label] for label in train_labels], dtype=np.int32)
    svm = cv2.ml.SVM_create()
    svm.setType(cv2.ml.SVM_C_SVC)
    svm.setKernel(cv2.ml.SVM_LINEAR)
    svm.setC(svm_c)
    svm.setTermCriteria((cv2.TERM_CRITERIA_MAX_ITER | cv2.TERM_CRITERIA_EPS, 2000, 1e-6))
    if not svm.train(normalized, cv2.ml.ROW_SAMPLE, train_y):
        raise ValueError("SVM training failed")
    _, predictions = svm.predict(normalized)
    _, raw = svm.predict(normalized, flags=cv2.ml.STAT_MODEL_RAW_OUTPUT)
    predicted_live = predictions.ravel() == 1
    if predicted_live.all() or not predicted_live.any():
        raise ValueError("SVM collapsed to a single class; improve the training dataset")
    direction = 1 if raw.ravel()[predicted_live].mean() > raw.ravel()[~predicted_live].mean() else -1
    validation_x, validation_labels = arrays["validation"]
    validation_scores = score_samples(svm, validation_x, mean, scale, direction)
    attack_scores = validation_scores[np.asarray(validation_labels) != "live"]
    candidates = np.nextafter(np.unique(attack_scores), np.inf)
    # Freeze the threshold on validation data; never tune against the test set.
    live_threshold = next(
        float(value) for value in candidates
        if all(
            float((validation_scores[np.asarray(validation_labels) == attack] >= value).mean()) <= target_apcer
            for attack in ("print", "replay")
        )
    )
    spoof_threshold = min(0.0, live_threshold - 1e-4)
    report = {
        "target_validation_apcer": target_apcer,
        "warning": "Dataset metrics do not establish general replay resistance. Review capture conditions and sample counts.",
        "validation": evaluation(validation_scores, validation_labels, live_threshold),
        "test": evaluation(score_samples(svm, arrays["test"][0], mean, scale, direction),
                           arrays["test"][1], live_threshold),
    }
    output_dir.mkdir(parents=True, exist_ok=False)
    svm.save(str(output_dir / "svm.xml"))
    np.savez(output_dir / "normalizer.npz", mean=mean, scale=scale)
    checksums = {name: sha256((output_dir / name).read_bytes()).hexdigest()
                 for name in ("svm.xml", "normalizer.npz")}
    manifest = {
        "feature_version": FEATURE_VERSION, "feature_dim": FEATURE_DIM,
        "pad_size": PAD_SIZE, "context_ratio": CONTEXT_RATIO,
        "model_version": "hog-dft-" + checksums["svm.xml"][:12],
        "margin_direction": direction, "live_threshold": live_threshold,
        "spoof_threshold": spoof_threshold, "approved_for_enforcement": False,
        "labels": {"live": 1, "spoof": 0}, "sha256": checksums,
        "training_opencv_version": cv2.__version__,
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (output_dir / "evaluation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True, help="CSV with full camera images and disjoint subjects")
    parser.add_argument("--output", type=Path, required=True, help="New artifact directory (must not already exist)")
    parser.add_argument("--target-apcer", type=float, default=0.05)
    parser.add_argument("--svm-c", type=float, default=1.0)
    args = parser.parse_args()
    try:
        if args.output.exists():
            raise ValueError("Output directory already exists; use a new model version directory")
        rows = read_dataset(args.dataset.resolve())
        samples = load_samples(rows, FaceRecognizer())
        report = train_and_export(samples, args.output, target_apcer=args.target_apcer, svm_c=args.svm_c)
    except (OSError, ValueError, cv2.error) as exc:
        parser.exit(1, f"Training stopped: {exc}\n")
    print(json.dumps(report, indent=2))
    print("Exported model is NOT approved for enforcement. Review evaluation before deployment.")


if __name__ == "__main__":
    main()
