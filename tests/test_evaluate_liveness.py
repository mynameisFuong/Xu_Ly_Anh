from types import SimpleNamespace
from pathlib import Path
import os
import subprocess
import sys

import pytest

from scripts.evaluate_liveness import evaluate


def test_evaluation_counts_rejected_live_samples_and_each_attack_type(tmp_path):
    rows = []
    for split in ("validation", "test"):
        for label in ("live", "print", "replay"):
            path = tmp_path / f"{split}-{label}.jpg"
            path.write_bytes(f"{split}-{label}".encode())
            rows.append({"split": split, "label": label, "resolved_path": path})
    # Stub chỉ kiểm tra phép tính báo cáo, không phải độ chính xác model.
    recognizer = SimpleNamespace(extract_single_embedding=lambda _: SimpleNamespace(accepted=False, diagnostics=None))
    report = evaluate(rows, recognizer)
    assert report["test"]["bpcer"] == 1
    assert report["test"]["apcer_print"] == report["test"]["apcer_replay"] == 0
    assert report["test"]["status_counts"] == {"source-rejected": 3}


@pytest.mark.parametrize("script", ["evaluate_liveness.py", "download_liveness_models.py"])
def test_windows_cli_help_works_with_legacy_console_encoding(script):
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, str(root / "scripts" / script), "--help"],
                            cwd=root, env={**os.environ, "PYTHONIOENCODING": "cp1258"}, capture_output=True)
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    assert "usage:" in result.stdout.decode("utf-8")
