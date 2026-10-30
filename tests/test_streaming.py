import numpy as np
import pytest

from ai_pipeline.streaming import FaceObservation, MultiFaceTracker, StaleFrameError, StreamBusyError, StreamStateStore


def test_rapid_frames_do_not_count_as_independent_observations():
    tracker = MultiFaceTracker(min_hits=3)
    face = FaceObservation((0, 0, 100, 100), 1)
    for frame_id, now in enumerate((0, 0.01, 0.02, 0.03)):
        result = tracker.update([face], frame_id=frame_id, now=now)[0]
        assert result.hits == 1 and not result.confirmed
    assert not tracker.update([face], frame_id=4, now=0.3)[0].confirmed
    assert tracker.update([face], frame_id=5, now=0.6)[0].confirmed


def test_long_unobserved_gap_discards_old_evidence():
    tracker = MultiFaceTracker(min_hits=3, max_gap_seconds=2)
    face = FaceObservation((0, 0, 100, 100), 1)
    tracker.update([face], frame_id=0, now=0)
    previous = tracker.update([face], frame_id=1, now=1)[0]
    returned = tracker.update([face], frame_id=2, now=4)[0]
    assert returned.track_id != previous.track_id and returned.hits == 1 and not returned.confirmed


def test_longer_confirmation_duration_can_finish_without_sliding_away_early_evidence():
    tracker = MultiFaceTracker(min_hits=3, min_confirmation_seconds=2)
    face = FaceObservation((0, 0, 100, 100), 1)
    for index in range(9):
        result = tracker.update([face], frame_id=index, now=index * 0.25)[0]
        assert result.confirmed == (index == 8)
    assert result.hits == 3


def test_appearance_change_cannot_inherit_votes_even_when_matcher_returns_same_identity():
    tracker = MultiFaceTracker(min_hits=2)
    box = (0, 0, 100, 100)
    first = tracker.update([FaceObservation(box, 1, embedding=np.zeros(128))], frame_id=0, now=0)[0]
    second = tracker.update([FaceObservation(box, 1, embedding=np.ones(128))], frame_id=1, now=1)[0]
    assert second.track_id != first.track_id and not second.confirmed


def test_crossing_faces_keep_independent_evidence_using_appearance():
    tracker = MultiFaceTracker(min_hits=3)
    left, right = (0, 0, 100, 100), (60, 0, 100, 100)
    first = tracker.update([FaceObservation(left, 1, embedding=np.zeros(128)),
                            FaceObservation(right, 2, embedding=np.ones(128))], frame_id=0, now=0)
    swapped = tracker.update([FaceObservation(left, 2, embedding=np.ones(128)),
                              FaceObservation(right, 1, embedding=np.zeros(128))], frame_id=1, now=1)
    assert swapped[0].track_id == first[1].track_id and swapped[1].track_id == first[0].track_id
    assert all(item.hits == 2 and not item.confirmed for item in swapped)


def test_people_are_confirmed_independently_and_unknown_does_not_reset_other_person():
    tracker = MultiFaceTracker(min_hits=3)
    a, b = (10, 20, 90, 100), (140, 20, 90, 100)
    first = tracker.update([FaceObservation(a, 1), FaceObservation(b, 2)], frame_id=0, now=0)
    second = tracker.update([FaceObservation(a, 1), FaceObservation(b, None)], frame_id=1, now=1)
    third = tracker.update([FaceObservation(a, 1), FaceObservation(b, 2)], frame_id=2, now=2)
    assert first[0].track_id == second[0].track_id == third[0].track_id
    assert third[0].confirmed and third[0].hits == 3
    assert not third[1].confirmed and third[1].hits == 1
    fourth = tracker.update([FaceObservation(b, 2), FaceObservation((260, 20, 90, 100), 3)], frame_id=3, now=3)
    assert fourth[0].track_id == first[1].track_id and fourth[0].hits == 2
    assert fourth[1].hits == 1 and not fourth[1].confirmed


def test_identity_swap_absence_and_duplicate_identity_never_inherit_confirmation():
    tracker = MultiFaceTracker(min_hits=2)
    box = (10, 20, 90, 100)
    tracker.update([FaceObservation(box, 1)], frame_id=0, now=0)
    swapped = tracker.update([FaceObservation(box, 2)], frame_id=1, now=1)
    assert swapped[0].hits == 1 and not swapped[0].confirmed
    tracker.update([], frame_id=2, now=2)
    returned = tracker.update([FaceObservation(box, 2)], frame_id=3, now=3)
    assert returned[0].hits == 1 and not returned[0].confirmed
    duplicate = tracker.update([FaceObservation(box, 2), FaceObservation((160, 20, 90, 100), 2)], frame_id=4, now=4)
    assert all(item.hits == 0 and not item.confirmed for item in duplicate)
    with pytest.raises(StaleFrameError):
        tracker.update([FaceObservation(box, 2)], frame_id=4, now=5)


def test_skipped_budget_does_not_add_or_discard_votes_but_confirmation_still_expires():
    tracker = MultiFaceTracker(min_hits=2, window_seconds=5)
    box = (10, 20, 90, 100)
    tracker.update([FaceObservation(box, 1)], frame_id=0, now=0)
    skipped = tracker.update([FaceObservation(box, None, processed=False)], frame_id=1, now=1)
    assert skipped[0].hits == 1 and not skipped[0].confirmed
    assert tracker.update([FaceObservation(box, 1)], frame_id=2, now=2)[0].confirmed
    assert not tracker.update([FaceObservation(box, 1)], frame_id=3, now=8)[0].confirmed


def test_stream_store_isolates_clients_rejects_overlap_and_replay_and_evicts_only_idle_states():
    now = [0]
    store = StreamStateStore(max_streams=1, ttl_seconds=10, clock=lambda: now[0])
    with store.checkout("a", 0) as original:
        with pytest.raises(StreamBusyError):
            with store.checkout("a", 1):
                pass
        with pytest.raises(StreamBusyError):
            with store.checkout("b", 0):
                pass
    with pytest.raises(StaleFrameError):
        with store.checkout("a", 0):
            pass
    with store.checkout("b", 0) as other:
        assert other is not original
    now[0] = 11
    with store.checkout("b", 0) as expired:
        assert expired is not other
    assert len(store._streams) == 1


@pytest.mark.parametrize("version", ["v1", "v2"])
def test_batch_detects_once_encodes_two_faces_and_enrollment_still_rejects_multi_face(version):
    from types import SimpleNamespace
    import cv2
    from ai_pipeline.analysis import FaceAnalysis
    from ai_pipeline.preprocessing import PreprocessingOptions
    from ai_pipeline.recognition import FaceRecognizer

    calls = []
    boxes = [(20, 30, 100, 110), (170, 30, 100, 110)]
    recognizer = FaceRecognizer.__new__(FaceRecognizer)
    recognizer._face_recognition = SimpleNamespace(face_encodings=lambda _frame, locations, **_kwargs:
                                                   calls.append(locations[0]) or [np.ones(128, np.float32)])
    detections = []
    recognizer.detect_faces = lambda _frame: detections.append(True) or boxes
    options = PreprocessingOptions(mode="enforce", version=version, align_eyes=False,
                                   normalize_lighting=False, shadow_v2=False)
    recognizer._analysis = FaceAnalysis(recognizer, preprocessing=options)
    frame = np.random.default_rng(8).integers(50, 200, (200, 300, 3), np.uint8)
    ok, encoded = cv2.imencode(".png", frame)
    assert ok
    batch = recognizer.extract_frame_embeddings(encoded.tobytes())
    assert (batch.width, batch.height) == (300, 200)
    assert len(batch.faces) == 2 and all(item.accepted for item in batch.faces)
    assert [item.face_box for item in batch.faces] == boxes
    assert calls == [(30, 120, 140, 20), (30, 270, 140, 170)]
    assert len(detections) == 1
    single = recognizer.extract_single_embedding(encoded.tobytes())
    assert not single.accepted and single.reason == "Multiple faces detected"


def test_one_bad_face_does_not_block_others_and_budget_rotates_fairly():
    from types import SimpleNamespace
    import cv2
    from ai_pipeline.recognition import FaceRecognizer

    recognizer = FaceRecognizer.__new__(FaceRecognizer)
    recognizer._face_recognition = SimpleNamespace(face_encodings=lambda *_args, **_kwargs: [np.ones(128, np.float32)])
    recognizer.detect_faces = lambda _: [(10, 30, 90, 100), (120, 30, 90, 100), (230, 30, 90, 100)]
    frame = np.random.default_rng(9).integers(50, 200, (200, 340, 3), np.uint8)
    frame[30:130, 120:210] = 0
    _, encoded = cv2.imencode(".png", frame)
    first = recognizer.extract_frame_embeddings(encoded.tobytes(), max_faces=1, offset=0)
    second = recognizer.extract_frame_embeddings(encoded.tobytes(), max_faces=1, offset=1)
    third = recognizer.extract_frame_embeddings(encoded.tobytes(), max_faces=1, offset=2)
    assert first.faces[0].accepted and third.faces[2].accepted
    assert not second.faces[1].accepted and "dark" in second.faces[1].reason
    assert first.faces[1].reason == "Waiting for face processing"
    assert len(first.faces) == len(second.faces) == len(third.faces) == 3


def test_v3_stream_finds_rolled_face_beside_upright_face_without_duplicates():
    from types import SimpleNamespace
    import cv2
    from ai_pipeline.analysis import FaceAnalysis
    from ai_pipeline.preprocessing import PreprocessingOptions, orient_image, rotate_roll, transform_box
    from ai_pipeline.recognition import FaceRecognizer

    frame = np.random.default_rng(22).integers(60, 190, (240, 500, 3), np.uint8)
    first, second = (100, 70, 100, 100), (300, 70, 100, 100)
    rotated = rotate_roll(orient_image(frame), 20)
    rotated_first = transform_box(first, rotated.source_to_image, rotated.image.shape)
    rotated_second = transform_box(second, rotated.source_to_image, rotated.image.shape)
    recognizer = FaceRecognizer.__new__(FaceRecognizer)
    recognizer._face_recognition = SimpleNamespace(face_encodings=lambda *_args, **_kwargs:
                                                   [np.ones(128, np.float32)])
    recognizer.detect_faces = lambda _image: [first]
    rescue_calls = []
    recognizer.detect_rescue_faces = lambda _image: rescue_calls.append(True) or [rotated_first, rotated_second]
    options = PreprocessingOptions(mode="enforce", version="v3", lighting_method="none",
                                   v3_extra_detection_attempts=1)
    recognizer._analysis = FaceAnalysis(recognizer, preprocessing=options)
    _, encoded = cv2.imencode(".png", frame)
    batch = recognizer.extract_frame_embeddings(encoded.tobytes())
    assert len(rescue_calls) == 1
    assert len(batch.faces) == 2 and all(face.accepted for face in batch.faces)
    assert batch.faces[0].face_box == first
    assert batch.faces[1].face_box[0] > 250
