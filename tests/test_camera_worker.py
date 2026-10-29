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
        json=lambda: {"liveness_mode": "unsupported", "preprocessing_mode": "off"},
    ))
    with pytest.raises(RuntimeError, match="unsupported pipeline policy"):
        load_pipeline_policy("http://example.test", "token")
