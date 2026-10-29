from ai_pipeline.temporal import CameraConfirmationStore, TemporalConfirmer


def test_confirmation_resets_when_candidate_changes_or_camera_loses_face():
    confirmer = TemporalConfirmer(min_hits=2)
    assert not confirmer.observe(1)
    assert not confirmer.observe(2)
    assert not confirmer.observe(1)
    assert confirmer.observe(1)
    confirmer.reset()
    assert not confirmer.observe(1)


def test_server_confirmations_are_bounded_isolated_and_expire():
    now = [0.0]
    store = CameraConfirmationStore(min_hits=2, window_seconds=4, max_streams=2, clock=lambda: now[0])
    assert not store.observe("a", 1)
    assert not store.observe("b", 1)
    assert store.observe("a", 1)
    assert not store.observe("a", 2)
    now[0] = 5
    assert not store.observe("a", 2)
    store.reset("a")
    assert not store.observe("a", 2)
    store.observe("b", 1)
    store.observe("c", 1)
    assert len(store._streams) == 2
