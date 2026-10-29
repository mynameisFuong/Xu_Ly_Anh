from pathlib import Path
from types import SimpleNamespace

from backend.app.config import Settings
from scripts.run_web import prepare_local_environment


def test_local_launcher_overrides_stale_terminal_values_and_uses_project_root(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("LIVENESS_MODE=enforce\nPREPROCESSING_MODE=enforce\n", encoding="utf-8")
    monkeypatch.setenv("LIVENESS_MODE", "off")
    monkeypatch.setenv("PREPROCESSING_MODE", "off")
    monkeypatch.chdir(tmp_path.parent)
    prepare_local_environment(tmp_path)
    settings = Settings(_env_file=None)
    assert settings.liveness_mode == settings.preprocessing_mode == "enforce"
    assert Path.cwd() == tmp_path


def test_standard_settings_keep_environment_priority_for_deployment(tmp_path, monkeypatch):
    file = tmp_path / ".env"
    file.write_text("LIVENESS_MODE=enforce\n", encoding="utf-8")
    monkeypatch.setenv("LIVENESS_MODE", "shadow")
    assert Settings(_env_file=file).liveness_mode == "shadow"


def test_readiness_explains_disabled_mode_and_missing_model(monkeypatch):
    from backend.app.api import _web_liveness_message

    settings = Settings(_env_file=None, liveness_mode="off")
    monkeypatch.setattr("backend.app.api.get_settings", lambda: settings)
    assert "LIVENESS_MODE=enforce" in _web_liveness_message(None)
    settings.liveness_mode = "enforce"
    assert "Thiếu engine Face ID" in _web_liveness_message(None)
    engine = SimpleNamespace(supports_pose=True, distance_metric="euclidean", _analysis=None)
    assert "Model PAD chưa nạp được" in _web_liveness_message(engine)
