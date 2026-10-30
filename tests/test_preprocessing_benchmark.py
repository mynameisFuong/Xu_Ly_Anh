from dataclasses import replace
import json
from types import SimpleNamespace

import numpy as np
import pytest

from ai_pipeline.preprocessing import PreprocessingOptions
from ai_pipeline.recognition import EmbeddingResult
from scripts.benchmark_preprocessing import Sample, evaluate_profile, load_manifest, profile_options, sample_bytes, threshold_at_far


def test_manifest_rejects_identity_session_and_source_leakage(tmp_path):
    for index in range(3):
        (tmp_path / f"{index}.jpg").write_bytes(bytes([index]))
    samples = [dict(path="0.jpg", subject="a", session="day1", role="enroll", partition="validation"),
               dict(path="1.jpg", subject="a", session="day2", role="probe", partition="validation")]
    manifest = tmp_path / "manifest.json"

    def load(rows):
        manifest.write_text(json.dumps({"samples": rows}), encoding="utf-8")
        return load_manifest(manifest)

    assert len(load(samples)) == 2
    with pytest.raises(ValueError, match="sessions overlap"):
        load([samples[0], dict(samples[1], session="day1")])
    with pytest.raises(ValueError, match="identities must be disjoint"):
        load(samples + [dict(samples[0], path="2.jpg", partition="test")])
    with pytest.raises(ValueError, match="leaks across"):
        load([samples[0], dict(samples[1], path="0.jpg")])
    with pytest.raises(ValueError, match="leaks across"):
        load([dict(samples[0], source_id="original"), dict(samples[1], source_id="original")])


def test_evaluation_counts_failed_extraction_in_rejection_rate_and_unknown_transactions(tmp_path):
    samples, embeddings = [], {}
    rows = [("a", "enroll", [0.0, 0.0]), ("a", "probe", [0.1, 0.0]),
            ("a", "probe", None), ("u", "unknown", [0.05, 0.0]), ("u", "unknown", None)]
    for index, (subject, role, vector) in enumerate(rows):
        path = tmp_path / f"{index}.jpg"
        path.write_bytes(bytes([index]))
        samples.append(Sample(path, subject, "day1" if role == "enroll" else "day2", role, "validation"))
        embeddings[bytes([index])] = EmbeddingResult(vector is not None, np.asarray(vector or [], np.float32))
    recognizer = SimpleNamespace(model_version="test:pre-v2", extract_single_embedding=lambda pixels: embeddings[pixels])
    report = evaluate_profile(samples, recognizer, threshold=0.52, margin=0.04)
    assert report["false_reject_rate"] == 0.5
    assert report["fpir"] == 0.5
    assert report["fmr"] == 1 and report["fnmr"] == 0
    assert report["known_probes"] == report["unknown_probes"] == 2
    assert report["impostor_comparisons"] == report["genuine_comparisons"] == 1
    assert "embedding" not in json.dumps(report)
    test_samples = [replace(sample, partition="test") for sample in samples]
    assert evaluate_profile(test_samples, recognizer)["tar_at_target_far"] is None


def test_far_calibration_is_conservative_including_ties_and_never_uses_test_scores():
    cutoff = threshold_at_far([0.1, 0.1, 0.4, 0.6], 0.25)
    assert np.mean(np.array([0.1, 0.1, 0.4, 0.6]) <= cutoff) <= 0.25
    assert threshold_at_far([], 0.01) is None
    assert threshold_at_far([0.3, 0.5], 0) < 0.3


def test_ablation_profiles_are_distinct_and_disable_shadow_overhead():
    base = PreprocessingOptions(shadow_v2=True)
    profiles = [profile_options(name, base) for name in
                ("v1", "v2-geometry", "v2-gamma", "v2-clahe", "v2-adaptive", "v2-denoise", "v2-align")]
    assert len({options.profile for options in profiles}) == len(profiles)
    assert all(not options.shadow_v2 and options.shadow_sample_rate == 0 for options in profiles)
    assert profile_options("legacy", base).mode == "off"
    with pytest.raises(ValueError):
        profile_options("nonexistent", base)


@pytest.mark.parametrize("variant", ["original", "rotate-90", "rotate-180", "rotate-270", "roll-20",
                                     "roll-minus20", "dark", "low-contrast", "noise", "jpeg"])
def test_synthetic_benchmark_inputs_keep_source_unchanged_and_share_size_policy(tmp_path, variant):
    import cv2
    from ai_pipeline.preprocessing import decode_bgr_image

    image = np.random.default_rng(1).integers(30, 220, (240, 400, 3), np.uint8)
    ok, encoded = cv2.imencode(".jpg", image)
    assert ok
    path = tmp_path / "image.jpg"
    original = encoded.tobytes()
    path.write_bytes(original)
    sample = Sample(path, "a", "day2", "probe", "validation", variant=variant)
    transformed = decode_bgr_image(sample_bytes(sample, max_side=200))
    assert transformed.dtype == np.uint8
    if variant in {"rotate-90", "rotate-270"}:
        assert transformed.shape == (200, 120, 3)
    elif variant.startswith("roll-"):
        assert transformed.shape[0] > 120 and transformed.shape[1] > 200
    else:
        assert transformed.shape == (120, 200, 3)
    assert path.read_bytes() == original
