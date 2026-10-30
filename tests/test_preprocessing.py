import numpy as np
import pytest

from ai_pipeline.preprocessing import (
    PreprocessingOptions, align_eyes, enhance_face_region, kirsch_edges, native_face_region, normalize_lighting,
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


def test_v1_profile_remains_exactly_compatible_and_rollout_controls_are_not_identity():
    from dataclasses import replace

    options = PreprocessingOptions()
    assert options.profile == "pre-v1-986b1750fc"
    assert replace(options, shadow_v2=True, shadow_sample_rate=0.1).profile == options.profile
    upgraded = replace(options, version="v2")
    assert upgraded.profile.startswith("pre-v2-")
    assert replace(upgraded, lighting_method="gamma").profile != upgraded.profile
    assert replace(upgraded, shadow_sample_rate=0.5).profile == upgraded.profile


def test_adaptive_lighting_keeps_good_images_exact_and_does_not_touch_background():
    from ai_pipeline.quality import measure_face_quality

    frame = np.random.default_rng(1).integers(50, 200, (200, 240, 3), dtype=np.uint8)
    original = frame.copy()
    options = PreprocessingOptions(version="v2")
    good = measure_face_quality(frame[40:160, 60:180])
    output, operations = enhance_face_region(frame, (60, 40, 120, 120), good, options)
    assert operations == ()
    np.testing.assert_array_equal(output, original)
    dark = (frame * 0.5).astype(np.uint8)
    metrics = measure_face_quality(dark[40:160, 60:180])
    output, operations = enhance_face_region(dark, (60, 40, 120, 120), metrics, options)
    assert operations == ("gamma",)
    assert output[40:160, 60:180].mean() > dark[40:160, 60:180].mean()
    np.testing.assert_array_equal(output[:10], dark[:10])
    np.testing.assert_array_equal(frame, original)
    assert output.shape == frame.shape and output.dtype == np.uint8


def test_adaptive_denoising_removes_impulses_and_clean_image_is_unchanged():
    from dataclasses import replace
    from ai_pipeline.quality import measure_face_quality

    frame = np.full((140, 140, 3), 120, np.uint8)
    frame[::5, ::5] = 255
    metrics = measure_face_quality(frame)
    options = PreprocessingOptions(version="v2", denoise_method="adaptive", lighting_method="none")
    output, operations = enhance_face_region(frame, (0, 0, 140, 140), metrics, options)
    assert operations == ("median-3",)
    assert np.count_nonzero(output == 255) < np.count_nonzero(frame == 255) / 10
    output, operations = enhance_face_region(frame, (0, 0, 140, 140),
                                             replace(metrics, impulse_fraction=0, noise_sigma=0), options)
    np.testing.assert_array_equal(output, frame)
    assert operations == ()


def test_native_metrics_exclude_rescue_canvas_and_refuse_synthetic_border():
    frame = np.random.default_rng(1).integers(40, 200, (200, 240, 3), dtype=np.uint8)
    prepared = rotate_roll(orient_image(frame), 20)
    native, mask = native_face_region(frame, prepared, (90, 90, 90, 90))
    assert native.size and mask.shape == native.shape[:2]
    assert np.any(mask == 0) and np.any(mask == 255)
    with pytest.raises(ValueError, match="clipped"):
        native_face_region(frame, prepared, (0, 0, 90, 90))


def test_composed_alignment_renders_native_pixels_once(monkeypatch):
    import cv2

    frame = np.random.default_rng(2).integers(0, 256, (200, 240, 3), dtype=np.uint8)
    prepared = rotate_roll(orient_image(frame), 20)
    calls = []
    warp = cv2.warpAffine

    def capture(pixels, matrix, *args, **kwargs):
        calls.append((pixels, matrix))
        return warp(pixels, matrix, *args, **kwargs)

    monkeypatch.setattr(cv2, "warpAffine", capture)
    eyes = {"left_eye": [(90, 90), (94, 90)], "right_eye": [(150, 105), (154, 105)]}
    aligned = align_eyes(prepared, eyes, source_image=frame)
    assert len(calls) == 1 and calls[0][0] is frame
    np.testing.assert_allclose(calls[0][1], aligned.source_to_image[:2])


def test_experimental_algorithms_preserve_bgr_contract_and_handle_constant_images():
    from ai_pipeline.experiments import multiscale_retinex, tan_triggs

    for pixels in (np.full((80, 100, 3), 90, np.uint8),
                   np.random.default_rng(1).integers(40, 150, (80, 100, 3), dtype=np.uint8)):
        original = pixels.copy()
        for transform in (multiscale_retinex, tan_triggs):
            result = transform(pixels)
            assert result.dtype == np.uint8 and result.shape == pixels.shape
            assert np.isfinite(result).all()
            np.testing.assert_array_equal(pixels, original)


def test_decoder_applies_exif_orientation_once_without_a_second_pipeline_rotation():
    import struct
    import cv2
    from ai_pipeline.preprocessing import decode_bgr_image

    frame = np.zeros((80, 120, 3), np.uint8)
    frame[:, :60] = (20, 90, 200)
    ok, encoded = cv2.imencode(".jpg", frame)
    assert ok
    # Minimal little-endian TIFF IFD containing orientation=6 (90° clockwise).
    tiff = b"II" + struct.pack("<HIH", 42, 8, 1) + struct.pack("<HHIHHI", 0x112, 3, 1, 6, 0, 0)
    exif = b"Exif\x00\x00" + tiff
    jpeg = encoded.tobytes()
    tagged = jpeg[:2] + b"\xff\xe1" + struct.pack(">H", len(exif) + 2) + exif + jpeg[2:]
    decoded = decode_bgr_image(tagged)
    expected = cv2.rotate(decode_bgr_image(jpeg), cv2.ROTATE_90_CLOCKWISE)
    assert decoded.shape == (120, 80, 3)
    np.testing.assert_array_equal(decoded, expected)
    np.testing.assert_array_equal(orient_image(decoded).image, expected)
