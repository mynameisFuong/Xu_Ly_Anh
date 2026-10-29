import csv
import json

import numpy as np
import pytest

from ai_pipeline.liveness import FEATURE_DIM, LivenessDetector, extract_features, pad_crop
from scripts.train_liveness import read_dataset, train_and_export


@pytest.mark.parametrize("constant", [False, True])
def test_features_are_finite_fixed_length_and_do_not_mutate_input(constant):
    image = np.zeros((90, 110, 3), np.uint8) if constant else np.random.default_rng(1).integers(0, 256, (90, 110, 3), dtype=np.uint8)
    original = image.copy()
    first = extract_features(image)
    assert first.shape == (FEATURE_DIM,) and first.dtype == np.float32
    assert np.isfinite(first).all()
    np.testing.assert_array_equal(first, extract_features(image))
    np.testing.assert_array_equal(image, original)


def test_pad_crop_clips_to_native_pixels_without_padding():
    image = np.random.default_rng(0).integers(0, 256, (100, 100, 3), dtype=np.uint8)
    crop = pad_crop(image, (0, 0, 80, 80))
    np.testing.assert_array_equal(crop, image[:crop.shape[0], :crop.shape[1]])
    assert not np.shares_memory(crop, image)


def test_missing_model_is_never_live(tmp_path):
    for detector in (LivenessDetector(), LivenessDetector(tmp_path)):
        assert not detector.ready
        assert detector.evaluate(np.zeros((100, 100, 3), np.uint8), (0, 0, 100, 100)).status == "unavailable"


@pytest.fixture
def bundle(tmp_path):
    # Synthetic vectors verify artifact plumbing only, not anti-spoof accuracy.
    samples = {}
    for split in ("train", "validation", "test"):
        samples[split] = []
        for repetition in range(3):
            for label in ("live", "print", "replay"):
                features = np.zeros(FEATURE_DIM, np.float32)
                features[0] = (2 if label == "live" else -2) + repetition * 0.05
                samples[split].append((features, label))
    directory = tmp_path / "model"
    report = train_and_export(samples, directory)
    assert report["validation"]["apcer"] == 0
    assert report["test"]["bpcer"] == 0
    return directory


def test_export_loads_but_requires_explicit_enforcement_approval(bundle):
    detector = LivenessDetector(bundle)
    assert detector.ready and not detector.approved
    image = np.random.default_rng(7).integers(0, 256, (100, 100, 3), dtype=np.uint8)
    assert detector.evaluate(image, (0, 0, 100, 100), require_approved=True).status == "unavailable"
    shadow = detector.evaluate(image, (0, 0, 100, 100))
    assert shadow.status in {"live", "spoof", "uncertain"} and np.isfinite(shadow.score)


def test_tampered_model_and_wrong_feature_profile_are_rejected(bundle):
    manifest_path = bundle / "manifest.json"
    original = json.loads(manifest_path.read_text())
    changed = dict(original, feature_version="different-features")
    manifest_path.write_text(json.dumps(changed))
    assert not LivenessDetector(bundle).ready
    manifest_path.write_text(json.dumps(original))
    with (bundle / "svm.xml").open("ab") as file:
        file.write(b"tampered")
    assert not LivenessDetector(bundle).ready


def test_dataset_split_requires_disjoint_subjects_and_all_attack_types(tmp_path):
    path = tmp_path / "dataset.csv"
    rows = []
    for split in ("train", "validation", "test"):
        for label in ("live", "print", "replay"):
            rows.append([f"{split}-{label}.jpg", label, split, split, split])

    def write(values):
        with path.open("w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow(["path", "label", "split", "subject_id", "session_id"])
            writer.writerows(values)

    write(rows)
    assert len(read_dataset(path)) == 9
    rows[-1][3] = "train"
    write(rows)
    with pytest.raises(ValueError, match="Subject leakage"):
        read_dataset(path)
