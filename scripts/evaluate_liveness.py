"""Đánh giá PAD pretrained trên validation/test tách người; không tự duyệt model."""

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sys
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from ai_pipeline.minifasnet import MiniFASNetDetector
from ai_pipeline.preprocessing import PreprocessingOptions
from ai_pipeline.recognition import FaceRecognizer
from scripts.train_liveness import read_dataset


def evaluate(rows, recognizer):
    samples = {split: [] for split in ("validation", "test")}
    hashes = set()
    for row in rows:
        data = row["resolved_path"].read_bytes()
        digest = sha256(data).hexdigest()
        if digest in hashes:
            raise ValueError("Duplicate image contents in dataset")
        hashes.add(digest)
        if row["split"] not in samples:
            continue
        started = perf_counter()
        result = recognizer.extract_single_embedding(data)
        pad = getattr(result.diagnostics, "liveness", None)
        samples[row["split"]].append((row["label"], result.accepted and pad is not None and pad.status == "live",
                                      pad.status if pad else "source-rejected", (perf_counter() - started) * 1000))
    report = {}
    for split, values in samples.items():
        rates = {}
        for label in ("live", "print", "replay"):
            selected = [accepted for kind, accepted, _, _ in values if kind == label]
            if not selected:
                raise ValueError(f"Missing {label} samples in {split}")
            rates["bpcer" if label == "live" else "apcer_" + label] = float(
                np.mean([not item for item in selected]) if label == "live" else np.mean(selected))
        report[split] = {
            "counts_by_label": dict(Counter(label for label, _, _, _ in values)),
            "status_counts": dict(Counter(status for _, _, status, _ in values)),
            **rates,
            "p50_ms": float(np.percentile([ms for _, _, _, ms in values], 50)),
            "p95_ms": float(np.percentile([ms for _, _, _, ms in values], 95)),
        }
    return report


def main():
    # PowerShell có thể truyền cp1258 cho pipe, không chứa đủ dấu tiếng Việt.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, default=Path("storage/pad-models/minifasnet-v1"))
    parser.add_argument("--live-threshold", type=float, default=0.9)
    parser.add_argument("--preprocessing", choices=("off", "enforce"), default="enforce")
    parser.add_argument("--output", type=Path, required=True, help="New aggregate report JSON, not an existing file")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output already exists; use a new report path")
    detector = MiniFASNetDetector(args.model_dir, live_threshold=args.live_threshold)
    if not detector.ready:
        parser.error(detector.error)
    recognizer = FaceRecognizer(preprocessing=PreprocessingOptions(mode=args.preprocessing),
                                liveness=detector, liveness_mode="shadow")
    if not recognizer.supports_pose:
        parser.error("Install the dlib Face ID engine before evaluation")
    try:
        report = evaluate(read_dataset(args.dataset.resolve()), recognizer)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    report.update({"model_version": detector.model_version, "live_threshold": args.live_threshold,
                   "recognition_profile": recognizer.model_version,
                   "scope": "Passive PAD only, not end-to-end challenge/deepfake resistance",
                   "approved_for_enforcement": False})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as file:
        json.dump(report, file, indent=2)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
