from types import SimpleNamespace

import numpy as np
import pytest

from camera_worker.main import load_pipeline_policy, scan_on_server


def test_worker_sends_pixels_token_stream_and_dry_run_without_unverified_event(monkeypatch):
    posted = []

    def post(url, **kwargs):
        posted.append((url, kwargs))
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"decision": "unknown"})

    monkeypatch.setattr("camera_worker.main.requests.post", post)
    result = scan_on_server("http://example.test", "token", 3, "camera", "stream", np.zeros((100, 100, 3), np.uint8), dry_run=True)
    assert result["decision"] == "unknown"
    url, args = posted[0]
    assert url.endswith("/sessions/3/camera-scan-frame")
    assert args["params"] == {"dry_run": "true", "stream_id": "stream"}
    assert args["headers"] == {"X-Camera-Token": "token"}
    assert args["json"]["image_base64"] and "student_id" not in args["json"]


def test_worker_rejects_unknown_server_policy(monkeypatch):
    monkeypatch.setattr("camera_worker.main.requests.get", lambda *_args, **_kwargs: SimpleNamespace(
        raise_for_status=lambda: None,
        json=lambda: {"preprocessing_mode": "unsupported"},
    ))
    with pytest.raises(RuntimeError, match="unsupported pipeline policy"):
        load_pipeline_policy("http://example.test", "token")


def test_worker_accepts_preprocessing_policy_without_pad_settings(monkeypatch):
    monkeypatch.setattr("camera_worker.main.requests.get", lambda *_args, **_kwargs: SimpleNamespace(
        raise_for_status=lambda: None, json=lambda: {"preprocessing_mode": "enforce"},
    ))
    assert load_pipeline_policy("http://example.test", "token")["preprocessing_mode"] == "enforce"


def test_multi_face_worker_sends_sequence_and_stream_in_body_without_legacy_vote(monkeypatch):
    posted = []
    monkeypatch.setattr("camera_worker.main.requests.post", lambda url, **kwargs:
                        posted.append((url, kwargs)) or SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"faces": []}))
    scan_on_server("http://example.test", "token", 3, "camera", "stream", np.zeros((100, 100, 3), np.uint8), frame_id=7)
    url, args = posted[0]
    assert url.endswith("/sessions/3/camera-scan-stream")
    assert args["json"]["stream_id"] == "stream" and args["json"]["frame_id"] == 7
    assert "student_id" not in args["json"] and "idempotency_key" not in args["json"]


def test_native_overlay_draws_independent_yellow_and_green_boxes_without_mutating_video():
    from ai_pipeline.overlay import draw_stream_faces

    frame = np.zeros((200, 320, 3), np.uint8)
    response = {"frame_width": 320, "frame_height": 200, "faces": [
        {"face_box": [10, 50, 90, 100], "decision": "recognized", "attendance": {"id": 1}, "full_name": "Nguyễn An"},
        {"face_box": [150, 50, 90, 100], "decision": "pending"},
    ]}
    result = draw_stream_faces(frame, response)
    np.testing.assert_array_equal(result[100, 10], [187, 224, 85])
    np.testing.assert_array_equal(result[100, 150], [107, 201, 242])
    assert not frame.any()
    changed = np.full_like(frame, 220)
    stale = draw_stream_faces(changed, response, reference_frame=frame)
    np.testing.assert_array_equal(stale[100, 10], [107, 201, 242])
