"""Read-only, labeled multi-face evaluation. Never writes attendance or face vectors."""

import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import sys
from time import perf_counter

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai_pipeline.detection import box_iou
from ai_pipeline.gallery import CompiledGallery
from ai_pipeline.recognition import ENROLLMENT_POSES
from ai_pipeline.streaming import FaceObservation, MultiFaceTracker


def load_dataset(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    boundaries, subjects = {}, defaultdict(set)
    enrollment_sessions = defaultdict(set)
    for item in data["enrollment"]:
        if item["partition"] not in {"validation", "test"} or item["pose"] not in ENROLLMENT_POSES:
            raise ValueError("Invalid enrollment partition or pose")
        subjects[item["partition"]].add(item["subject"])
        enrollment_sessions[(item["partition"], item["subject"])].add(item["session"])
        item["path"] = (path.parent / item["path"]).resolve()
        digest = sha256(item["path"].read_bytes()).hexdigest()
        boundary = (item["partition"], item["subject"], "enroll", item["pose"])
        if digest in boundaries and boundaries[digest] != boundary:
            raise ValueError("Enrollment image leaks across identities or partitions")
        boundaries[digest] = boundary
    for stream in data["streams"]:
        partition = stream["partition"]
        if partition not in {"validation", "test"} or not stream["frames"]:
            raise ValueError("Invalid or empty evaluation stream")
        previous_time = -1.0
        for frame in stream["frames"]:
            timestamp = frame["timestamp"]
            if not np.isfinite(timestamp) or timestamp < 0 or timestamp <= previous_time:
                raise ValueError("Frame timestamps must be finite, nonnegative and increasing")
            previous_time = timestamp
            frame["path"] = (path.parent / frame["path"]).resolve()
            digest = sha256(frame["path"].read_bytes()).hexdigest()
            boundary = (partition, stream["session"], "probe")
            if digest in boundaries and boundaries[digest] != boundary:
                raise ValueError("Image leaks between enrollment, evaluation sessions or partitions")
            boundaries[digest] = boundary
            seen_subjects = set()
            for face in frame["faces"]:
                subject, box = face["subject"], face["box"]
                if subject in seen_subjects or len(box) != 4 or not np.isfinite(box).all() or min(box[2:]) <= 0:
                    raise ValueError("Invalid or duplicate ground-truth face")
                seen_subjects.add(subject)
                subjects[partition].add(subject)
                if stream["session"] in enrollment_sessions[(partition, subject)]:
                    raise ValueError("Enrollment and evaluation sessions overlap")
    if subjects["validation"] & subjects["test"]:
        raise ValueError("Validation and test identities must be disjoint")
    return data


def associate(boxes, labels):
    """One-to-one spatial assignment; identity is deliberately excluded."""
    edges = sorted(((box_iou(box, label["box"]), index, target)
                    for index, box in enumerate(boxes) for target, label in enumerate(labels)), reverse=True)
    assigned, used = {}, set()
    for overlap, index, target in edges:
        if overlap >= 0.5 and index not in assigned and target not in used:
            assigned[index] = labels[target]["subject"]
            used.add(target)
    return assigned


def evaluate(data, recognizer, *, partition="test", threshold=0.52, margin=0.04,
             min_hits=3, min_interval=0.25, min_duration=0.5, max_gap=10, max_faces=8):
    if recognizer.distance_metric != "euclidean":
        raise ValueError("Evaluation requires the real Face ID engine, not the demo fallback")
    entries = [item for item in data["enrollment"] if item["partition"] == partition]
    identities = {subject: index for index, subject in enumerate(sorted({item["subject"] for item in entries}))}
    templates, poses = defaultdict(list), defaultdict(set)
    for item in entries:
        result = recognizer.extract_single_embedding(item["path"].read_bytes())
        if result.accepted:
            templates[identities[item["subject"]]].append(result.embedding)
            poses[identities[item["subject"]]].add(item["pose"])
    templates = {person: vectors for person, vectors in templates.items() if set(ENROLLMENT_POSES) <= poses[person]}
    if not templates:
        raise ValueError("No complete five-pose identities survived enrollment quality checks")
    gallery = CompiledGallery(templates, 128)
    counts = Counter({key: 0 for key in ("frames", "repeated_frames_ignored", "labeled_faces", "detected_labeled_faces",
                                        "track_id_changes", "correct_attendance", "false_attendance",
                                        "expected_attendance", "missed_attendance")})
    latencies, recognition_delays = [], []
    condition_counts = defaultdict(Counter)
    for stream in data["streams"]:
        if stream["partition"] != partition:
            continue
        tracker = MultiFaceTracker(min_hits=min_hits, min_interval_seconds=min_interval,
                                   min_confirmation_seconds=min_duration, max_gap_seconds=max_gap)
        first_seen, recognized, logged, previous_tracks, digests = {}, set(), set(), {}, set()
        for frame_id, frame in enumerate(stream["frames"]):
            condition = condition_counts[stream.get("condition", "unspecified")]
            for label in frame["faces"]:
                identity = identities.get(label["subject"])
                if identity in templates:
                    first_seen.setdefault(identity, frame["timestamp"])
            raw = frame["path"].read_bytes()
            digest = sha256(raw).hexdigest()
            counts["frames"] += 1
            if digest in digests:
                counts["repeated_frames_ignored"] += 1
                continue
            digests.add(digest)
            started = perf_counter()
            batch = recognizer.extract_frame_embeddings(raw, max_faces=max_faces, offset=frame_id * max_faces)
            faces = [face for face in batch.faces if face.face_box is not None]
            matches = gallery.match_many([face.embedding if face.accepted else np.empty(0) for face in faces],
                                         threshold=threshold, margin=margin)
            observations = [FaceObservation(face.face_box, match.student_id,
                                            processed=face.reason != "Waiting for face processing",
                                            embedding=(face.embedding if face.accepted and face.embedding.shape == (128,)
                                                       and np.isfinite(face.embedding).all() else None))
                            for face, match in zip(faces, matches)]
            confirmations = tracker.update(observations, frame_id=frame_id, now=frame["timestamp"])
            latencies.append((perf_counter() - started) * 1000)
            assigned = associate([face.face_box for face in faces], frame["faces"])
            counts["labeled_faces"] += len(frame["faces"])
            counts["detected_labeled_faces"] += len(assigned)
            for index, (match, confirmation) in enumerate(zip(matches, confirmations)):
                subject = assigned.get(index)
                if subject is not None:
                    previous = previous_tracks.get(subject)
                    if previous is not None and previous != confirmation.track_id:
                        counts["track_id_changes"] += 1
                    previous_tracks[subject] = confirmation.track_id
                if not confirmation.confirmed or match.student_id in logged:
                    continue
                logged.add(match.student_id)
                expected = identities.get(subject)
                correct = subject is not None and expected in templates and match.student_id == expected
                counts["correct_attendance" if correct else "false_attendance"] += 1
                condition["correct_attendance" if correct else "false_attendance"] += 1
                if correct:
                    recognized.add(expected)
                    recognition_delays.append(frame["timestamp"] - first_seen[expected])
        counts["expected_attendance"] += len(first_seen)
        counts["missed_attendance"] += len(set(first_seen) - recognized)
        condition_counts[stream.get("condition", "unspecified")]["missed_attendance"] += len(set(first_seen) - recognized)
    if not counts["frames"]:
        raise ValueError("No evaluation frames in selected partition")
    return {"partition": partition, "model_version": recognizer.model_version,
            "parameters": {"threshold": threshold, "margin": margin, "min_hits": min_hits,
                           "min_interval": min_interval, "min_duration": min_duration, "max_gap": max_gap,
                           "max_faces": max_faces},
            "counts": dict(counts), "by_condition": {key: dict(value) for key, value in condition_counts.items()},
            "attendance_precision": (counts["correct_attendance"] / (counts["correct_attendance"] + counts["false_attendance"])
                                     if counts["correct_attendance"] + counts["false_attendance"] else None),
            "attendance_recall": (counts["correct_attendance"] / counts["expected_attendance"]
                                  if counts["expected_attendance"] else None),
            "processing_ms_p50_p95": np.percentile(latencies, [50, 95]).tolist() if latencies else None,
            "time_to_attendance_seconds_p50_p95": np.percentile(recognition_delays, [50, 95]).tolist() if recognition_delays else None,
            "limitations": "Offline labeled replay, not camera-to-screen latency or an anti-spoofing evaluation. "
                           "Tune only on validation; freeze parameters before evaluating test."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--partition", choices=("validation", "test"), default="test")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    from backend.app.config import get_settings
    from backend.app.services.face_templates import build_default_recognizer

    settings = get_settings()
    report = evaluate(load_dataset(args.manifest), build_default_recognizer(), partition=args.partition,
                      threshold=settings.face_distance_threshold, margin=settings.face_distance_margin,
                      min_hits=settings.attendance_min_hits,
                      min_interval=settings.stream_min_observation_interval_seconds,
                      min_duration=settings.stream_min_confirmation_seconds,
                      max_gap=settings.stream_max_observation_gap_seconds, max_faces=settings.stream_max_faces_per_frame)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote aggregate evaluation report: {args.output}")


if __name__ == "__main__":
    main()
