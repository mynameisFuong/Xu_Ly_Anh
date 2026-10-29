import numpy as np
import pytest

from ai_pipeline.preprocessing import (
    PreprocessingOptions, align_eyes, kirsch_edges, normalize_lighting,
    orient_image, rotate_roll, source_box, transform_box, validate_bgr,
)


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("mirror", [False, True])
def test_orientation_roundtrips_source_coordinates_and_pixels(rotation, mirror):
    frame = np.random.default_rng(10).integers(0, 256, (90, 140, 3), dtype=np.uint8)
    original = frame.copy()
    prepared = orient_image(frame, rotation=rotation, mirror=mirror)
    box = (23, 17, 40, 30)
    mapped = transform_box(box, prepared.source_to_image, prepared.image.shape)
    assert source_box(prepared, mapped, frame.shape) == box
    x, y, _ = prepared.source_to_image @ [35, 25, 1]
    np.testing.assert_array_equal(prepared.image[int(y), int(x)], frame[25, 35])
    np.testing.assert_array_equal(frame, original)
    assert prepared.image.dtype == np.uint8


def test_eye_alignment_levels_eyes_without_changing_shape_or_input():
    frame = np.random.default_rng(8).integers(0, 256, (160, 200, 3), dtype=np.uint8)
    original = frame.copy()
    landmarks = {"left_eye": [(50, 60), (54, 60)], "right_eye": [(110, 80), (114, 80)]}
    prepared = align_eyes(orient_image(frame), landmarks)
    eyes = np.array([[52, 60, 1], [112, 80, 1]]) @ prepared.source_to_image.T
    assert abs(eyes[0, 1] - eyes[1, 1]) < 1e-6
    assert prepared.image.shape == frame.shape
    np.testing.assert_array_equal(original, frame)


@pytest.mark.parametrize("landmarks", [{}, {"left_eye": [(2, 3)], "right_eye": [(2, 3)]},
                                         {"left_eye": [(-20, 30), (-18, 30)], "right_eye": [(80, 40), (82, 40)]}])
def test_alignment_rejects_unreliable_landmarks(landmarks):
    with pytest.raises(ValueError):
        align_eyes(orient_image(np.zeros((100, 100, 3), np.uint8)), landmarks)


def test_lighting_and_kirsch_are_separate_pure_branches():
    frame = np.random.default_rng(4).integers(40, 150, (120, 100, 3), dtype=np.uint8)
    original = frame.copy()
    normalized = normalize_lighting(frame)
    edges = kirsch_edges(frame)
    assert normalized.shape == frame.shape and normalized.dtype == np.uint8
    assert edges.shape == frame.shape[:2] and edges.dtype == np.float32
    assert np.isfinite(edges).all()
    np.testing.assert_array_equal(frame, original)


def test_profile_is_stable_across_rollout_modes_but_changes_with_geometry():
    assert PreprocessingOptions(mode="shadow").profile == PreprocessingOptions(mode="enforce").profile
    assert PreprocessingOptions().profile != PreprocessingOptions(mirror_input=True).profile


def test_clipping_never_wraps_negative_numpy_indices():
    assert transform_box((-10, -20, 50, 60), np.eye(3), (100, 100, 3)) == (0, 0, 40, 40)
    assert transform_box((150, 0, 50, 60), np.eye(3), (100, 100, 3)) is None
    with pytest.raises(ValueError):
        validate_bgr(np.zeros((10, 10), dtype=np.uint8))


def test_roll_rescue_expands_canvas_and_preserves_inverse_coordinates():
    image = np.random.default_rng(11).integers(0, 256, (200, 300, 3), dtype=np.uint8)
    original = image.copy()
    prepared = rotate_roll(orient_image(image), 20)
    assert prepared.image.shape[0] > 200 and prepared.image.shape[1] > 300
    points = np.array([[60, 50, 1], [180, 150, 1]])
    mapped = points @ prepared.source_to_image.T
    restored = mapped @ np.linalg.inv(prepared.source_to_image).T
    np.testing.assert_allclose(restored, points)
    np.testing.assert_array_equal(image, original)
