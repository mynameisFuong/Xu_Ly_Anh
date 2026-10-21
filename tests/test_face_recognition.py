import numpy as np

from ai_pipeline.recognition import FaceRecognizer, PoseResult, classify_enrollment_pose, classify_pose, match_embedding


def test_classify_pose_covers_guided_faceid_directions():
    assert classify_pose(0, 0) == "front"
    assert classify_pose(-24, 0) == "left"
    assert classify_pose(25, 0) == "right"
    assert classify_pose(0, -18) == "up"
    assert classify_pose(0, 19) == "down"


def test_relative_pitch_accepts_a_gentle_tilt_from_front_position():
    front_pitch = 9
    assert classify_enrollment_pose(PoseResult("front", 0, 0), "up", front_pitch) == "up"
    assert classify_enrollment_pose(PoseResult("down", 0, 17), "down", front_pitch) == "down"
    assert classify_enrollment_pose(PoseResult("front", 0, 9), "up", front_pitch) == "front"
    assert classify_enrollment_pose(PoseResult("right", 22, 0), "up", front_pitch) == "right"
    assert classify_enrollment_pose(PoseResult("front", 0, 9), "front", front_pitch) == "front"


def test_detected_face_box_is_returned_even_when_image_quality_is_low():
    class FaceLibrary:
        def face_locations(self, *_args, **_kwargs):
            return [(20, 80, 100, 10)]

        def face_landmarks(self, *_args, **_kwargs):
            return []

        def face_encodings(self, *_args, **_kwargs):
            return [np.zeros(128, dtype=np.float32)]

    recognizer = FaceRecognizer.__new__(FaceRecognizer)
    recognizer._face_recognition = FaceLibrary()
    result = recognizer._extract_dlib(np.zeros((120, 100, 3), dtype=np.uint8), num_jitters=1)
    assert result.face_box == (10, 20, 70, 80)


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
