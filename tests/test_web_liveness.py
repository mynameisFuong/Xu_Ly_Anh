import numpy as np
import pytest

from ai_pipeline.recognition import EmbeddingResult, PoseResult
from backend.app.config import Settings
from backend.app.services.web_liveness import WebLivenessStore


@pytest.fixture
def context():
    settings = Settings(_env_file=None)
    now = [100.0]
    store = WebLivenessStore(settings, clock=lambda: now[0], choose=lambda: ["left", "up", "right"])
    owner = ("user", 1, 2)
    state = store.start(owner)
    return store, now, owner, state


def observation(store, now, owner, state, *, yaw=0, pitch=0, vector=None, student_id=1, **overrides):
    now[0] += 0.7
    values = dict(step_token=state["step_token"], sequence=state["sequence"],
                  digest=str(now[0]), student_id=student_id,
                  result=EmbeddingResult(True, np.zeros(128, np.float32) if vector is None else vector,
                                         pose=PoseResult("front", yaw, pitch)))
    values.update(overrides)
    return store.observe(state["challenge_id"], owner, **values)


def test_all_actions_require_fresh_frames_and_pass_is_consumed_once(context):
    store, now, owner, state = context
    original_id = state["challenge_id"]
    actions_seen = []
    for yaw, pitch in ((0, 0), (-22, 0), (0, 0), (0, -16), (0, 0), (22, 0), (0, 0)):
        actions_seen.append(state["action"])
        first = observation(store, now, owner, state, yaw=yaw, pitch=pitch)
        assert first["status"] == "pending" and first["step"] == state["step"]
        previous_token = state["step_token"]
        state = observation(store, now, owner, first, yaw=yaw, pitch=pitch)
        if state["status"] == "pending":
            assert state["step_token"] != previous_token
    assert state["status"] == "passed"
    assert actions_seen == ["center", "left", "center", "up", "center", "right", "center"]
    assert not store.valid(original_id, owner)
    assert store.observe(original_id, owner, step_token="", sequence=0, digest="new",
                         result=None, student_id=1)["status"] == "failed"


@pytest.mark.parametrize("attack", ["same-frame", "out-of-order", "wrong-token", "identity", "gap", "expired", "invalid-pose"])
def test_attacks_invalidate_challenge(context, attack):
    store, now, owner, state = context
    state = observation(store, now, owner, state)
    kwargs = {}
    if attack == "same-frame":
        kwargs["digest"] = str(now[0])
    elif attack == "out-of-order":
        kwargs["sequence"] = 0
    elif attack == "wrong-token":
        kwargs["step_token"] = "forged"
    elif attack == "identity":
        kwargs["vector"] = np.ones(128, np.float32)
    elif attack == "gap":
        now[0] += 6
    elif attack == "expired":
        now[0] += 46
    elif attack == "invalid-pose":
        kwargs["yaw"] = float("nan")
    result = observation(store, now, owner, state, **kwargs)
    assert result["status"] == "failed"
    assert not store.valid(state["challenge_id"], owner)


def test_wrong_owner_cannot_read_consume_or_cancel(context):
    store, now, owner, state = context
    assert not store.valid(state["challenge_id"], ("user", 2, 2))
    store.cancel(state["challenge_id"], ("user", 2, 2))
    assert store.valid(state["challenge_id"], owner)
    bad = observation(store, now, ("user", 2, 2), state)
    assert bad["status"] == "failed" and store.valid(state["challenge_id"], owner)


def test_wrong_pose_and_fast_frames_cannot_advance(context):
    store, now, owner, state = context
    state = observation(store, now, owner, state, yaw=25)
    assert state["step"] == 0
    state = observation(store, now, owner, state)
    now[0] -= 0.69
    fast = observation(store, now, owner, state)
    assert fast["step"] == 0
    state = observation(store, now, owner, fast)
    assert state["step"] == 1
    for _ in range(3):
        state = observation(store, now, owner, state, yaw=22)
    assert state["step"] == 1


def test_new_challenge_invalidates_previous_and_store_is_bounded(context):
    store, _, owner, state = context
    store.start(owner)
    assert not store.valid(state["challenge_id"], owner)
    for index in range(150):
        store.start(("user", index, 3))
    assert len(store._items) == 128


def retry(store, now, owner, state, **overrides):
    now[0] += 0.7
    values = dict(step_token=state["step_token"], sequence=state["sequence"],
                  digest=f"missing-{now[0]}", message="Tạm mất khuôn mặt")
    values.update(overrides)
    return store.retry_frame(state["challenge_id"], owner, **values)


def test_transient_miss_keeps_completed_steps_but_resets_current_hold_and_preserves_anchor(context):
    store, now, owner, state = context
    state = observation(store, now, owner, state)
    state = observation(store, now, owner, state)
    assert state["step"] == 1
    state = observation(store, now, owner, state, yaw=-22)
    anchor = store._items[state["challenge_id"]].anchor.copy()
    state = retry(store, now, owner, state)
    assert state["status"] == "pending" and state["step"] == 1
    item = store._items[state["challenge_id"]]
    assert item.hold_started is None and item.hits == 0
    np.testing.assert_array_equal(item.anchor, anchor)
    state = observation(store, now, owner, state, yaw=-22)
    assert state["step"] == 1
    state = observation(store, now, owner, state, yaw=-22)
    assert state["step"] == 2


@pytest.mark.parametrize("attack", ["repeat", "nonce", "sequence", "continuous-misses", "owner"])
def test_retry_frames_still_check_protocol_and_cannot_keep_a_lost_face_alive(context, attack):
    store, now, owner, state = context
    state = observation(store, now, owner, state)
    kwargs = {}
    request_owner = owner
    if attack == "repeat":
        kwargs["digest"] = str(now[0])
    elif attack == "nonce":
        kwargs["step_token"] = "forged"
    elif attack == "sequence":
        kwargs["sequence"] = state["sequence"] + 1
    elif attack == "owner":
        request_owner = ("user", 9, 2)
    elif attack == "continuous-misses":
        for _ in range(7):
            state = retry(store, now, owner, state)
            assert state["status"] == "pending" and state["step"] == 0
    result = retry(store, now, request_owner, state, **kwargs)
    assert result["status"] == "failed"
    assert store.valid(state["challenge_id"], owner) is (attack == "owner")


def test_missed_frame_does_not_allow_switching_identity(context):
    store, now, owner, state = context
    state = observation(store, now, owner, state)
    state = retry(store, now, owner, state)
    state = observation(store, now, owner, state, student_id=2)
    assert state["status"] == "failed"
