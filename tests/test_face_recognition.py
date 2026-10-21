import numpy as np

from ai_pipeline.recognition import classify_pose, match_embedding


def test_classify_pose_covers_guided_faceid_directions():
    assert classify_pose(0, 0) == "front"
    assert classify_pose(-24, 0) == "left"
    assert classify_pose(25, 0) == "right"
    assert classify_pose(0, -18) == "up"
    assert classify_pose(0, 19) == "down"


def test_euclidean_match_uses_best_of_multiple_pose_templates():
    templates = {
        1: [np.array([0.0, 0.0], dtype=np.float32), np.array([0.8, 0.8], dtype=np.float32)],
        2: [np.array([0.5, 0.5], dtype=np.float32)],
    }

    result = match_embedding(
        np.array([0.78, 0.79], dtype=np.float32),
        templates,
        threshold=0.20,
        margin=0.10,
        metric="euclidean",
    )

    assert result.decision == "recognized"
    assert result.student_id == 1
    assert result.score > 0.95


def test_euclidean_match_rejects_ambiguous_people():
    templates = {
        1: [np.array([0.10, 0.10], dtype=np.float32)],
        2: [np.array([0.11, 0.11], dtype=np.float32)],
    }

    result = match_embedding(
        np.array([0.105, 0.105], dtype=np.float32),
        templates,
        threshold=0.20,
        margin=0.04,
        metric="euclidean",
    )

    assert result.decision == "low_confidence"
    assert result.student_id is None
