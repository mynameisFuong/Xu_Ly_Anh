import json
from types import SimpleNamespace

import numpy as np
import pytest

from ai_pipeline.recognition import ENROLLMENT_POSES, EmbeddingResult, FrameEmbeddingResult
from scripts.evaluate_stream import evaluate, load_dataset


def dataset(tmp_path):
    entries = []
    for index, pose in enumerate(ENROLLMENT_POSES):
        name = f"enroll-{index}.jpg"
        (tmp_path / name).write_bytes(f"enroll-{index}".encode())
        entries.append(dict(subject="a", session="day1", partition="test", path=name, pose=pose))
    frames = []
    for index in range(3):
        name = f"frame-{index}.jpg"
        (tmp_path / name).write_bytes(f"frame-{index}".encode())
        frames.append(dict(path=name, timestamp=index * 0.3,
                           faces=[dict(subject="a", box=[0, 0, 100, 100])]))
    data = dict(enrollment=entries, streams=[dict(session="day2", partition="test", condition="normal", frames=frames)])
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(data))
    return path, data


def recognizer():
    face = EmbeddingResult(True, np.zeros(128), face_box=(0, 0, 100, 100))
    return SimpleNamespace(distance_metric="euclidean", model_version="test-model",
                           extract_single_embedding=lambda _: face,
                           extract_frame_embeddings=lambda *_args, **_kwargs: FrameEmbeddingResult((face,), 200, 200))


def test_offline_evaluation_counts_attendance_delays_and_missed_people_without_database(tmp_path):
    path, _ = dataset(tmp_path)
    data = load_dataset(path)
    report = evaluate(data, recognizer())
    assert report["counts"]["correct_attendance"] == 1
    assert report["counts"]["missed_attendance"] == 0
    assert report["time_to_attendance_seconds_p50_p95"] == pytest.approx([0.6, 0.6])
    assert "embedding" not in json.dumps(report)
    assert "subject" not in json.dumps(report)


def test_unknown_person_misidentified_as_enrolled_person_is_a_false_attendance(tmp_path):
    path, data = dataset(tmp_path)
    for frame in data["streams"][0]["frames"]:
        frame["faces"][0]["subject"] = "unknown"
    path.write_text(json.dumps(data))
    report = evaluate(load_dataset(path), recognizer())
    assert report["counts"]["false_attendance"] == 1
    assert report["counts"].get("correct_attendance", 0) == 0


@pytest.mark.parametrize("problem", ["session", "content", "timestamps", "partition"])
def test_evaluation_rejects_dataset_leakage_and_invalid_time(tmp_path, problem):
    path, data = dataset(tmp_path)
    if problem == "session":
        data["streams"][0]["session"] = "day1"
    elif problem == "content":
        data["streams"][0]["frames"][0]["path"] = data["enrollment"][0]["path"]
    elif problem == "timestamps":
        data["streams"][0]["frames"][1]["timestamp"] = 0
    else:
        data["streams"][0]["partition"] = "validation"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        load_dataset(path)


def test_frozen_frame_cannot_confirm_attendance_in_evaluation(tmp_path):
    path, data = dataset(tmp_path)
    for frame in data["streams"][0]["frames"]:
        frame["path"] = "frame-0.jpg"
    path.write_text(json.dumps(data))
    report = evaluate(load_dataset(path), recognizer())
    assert report["counts"]["repeated_frames_ignored"] == 2
    assert report["counts"]["missed_attendance"] == 1
