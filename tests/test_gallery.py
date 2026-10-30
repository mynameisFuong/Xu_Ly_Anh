import numpy as np
import pytest

from ai_pipeline.gallery import CompiledGallery
from ai_pipeline.recognition import match_embedding


@pytest.mark.parametrize("metric", ["euclidean", "cosine"])
def test_batch_gallery_preserves_reference_decisions_for_multiple_people(metric):
    rng = np.random.default_rng(42)
    templates = {person: [rng.normal(size=128) for _ in range(5)] for person in range(120)}
    templates[150] = [np.zeros(3), np.full(128, np.nan)]
    probes = [templates[person][1] + rng.normal(0, 0.01, 128) for person in range(20)]
    probes += [rng.normal(size=128), np.full(128, np.inf), np.zeros(3)]
    parameters = dict(threshold=0.52 if metric == "euclidean" else 0.65, margin=0.04, metric=metric)
    expected = [match_embedding(probe, templates, **parameters) for probe in probes]
    actual = CompiledGallery(templates, 128, metric=metric).match_many(
        probes, threshold=parameters["threshold"], margin=parameters["margin"])
    for probe, reference, result in zip(probes, expected, actual):
        if np.shape(probe) != (128,):
            # A dimension-mismatched probe is rejected against the compiled model profile.
            assert result.student_id is None and result.decision == "unknown"
            continue
        assert result.student_id == reference.student_id and result.decision == reference.decision
        assert result.score == pytest.approx(reference.score, abs=1e-6)
        assert result.second_score == pytest.approx(reference.second_score, abs=1e-6)


def test_batch_gallery_rejects_ambiguous_identity_and_handles_empty_gallery():
    gallery = CompiledGallery({1: [np.zeros(128)], 2: [np.zeros(128)]}, 128)
    assert gallery.match_many([np.zeros(128)], threshold=0.52, margin=0.04)[0].student_id is None
    empty = CompiledGallery({}, 128)
    assert empty.match_many([], threshold=0.52, margin=0.04) == []
    assert empty.match_many([np.zeros(128)], threshold=0.52, margin=0.04)[0].decision == "unknown"
