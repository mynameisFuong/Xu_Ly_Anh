from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.app.config import Settings
from scripts.run_web import prepare_local_environment


def test_local_launcher_overrides_stale_terminal_values_and_uses_project_root(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("PREPROCESSING_MODE=enforce\n", encoding="utf-8")
    monkeypatch.setenv("PREPROCESSING_MODE", "off")
    monkeypatch.chdir(tmp_path.parent)
    prepare_local_environment(tmp_path)
    settings = Settings(_env_file=None)
    assert settings.preprocessing_mode == "enforce"
    assert Path.cwd() == tmp_path


def test_standard_settings_keep_environment_priority_for_deployment(tmp_path, monkeypatch):
    file = tmp_path / ".env"
    file.write_text("PREPROCESSING_MODE=enforce\n", encoding="utf-8")
    monkeypatch.setenv("PREPROCESSING_MODE", "shadow")
    assert Settings(_env_file=file).preprocessing_mode == "shadow"


def test_retired_liveness_env_does_not_load_models_or_break_startup(tmp_path, monkeypatch):
    import sys
    from backend.app.services.face_templates import build_default_recognizer

    file = tmp_path / ".env"
    file.write_text("LIVENESS_MODE=enforce\nWEB_LIVENESS_REQUIRED=true\n"
                    "LIVENESS_MODEL_DIR=missing-model\nLIVENESS_BACKEND=minifasnet\n", encoding="utf-8")
    settings = Settings(_env_file=file)
    assert not any("liveness" in key for key in settings.model_dump())
    monkeypatch.setitem(sys.modules, "face_recognition", None)
    monkeypatch.setitem(sys.modules, "onnxruntime", None)
    monkeypatch.setattr("backend.app.services.face_templates.get_settings", lambda: settings)
    build_default_recognizer.cache_clear()
    try:
        recognizer = build_default_recognizer()
        assert recognizer.model_version.startswith("0.1.0:pre-v3-")
        assert recognizer._analysis is not None
    finally:
        build_default_recognizer.cache_clear()


def test_retiring_old_settings_does_not_hide_unrelated_config_typos(tmp_path):
    file = tmp_path / ".env"
    file.write_text("PREPROCESSING_MOD=enforce\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        Settings(_env_file=file)


def test_v2_settings_reach_the_shared_recognizer_without_changing_v3_default():
    from backend.app.services.face_templates import build_preprocessing_options
    from ai_pipeline.preprocessing import PreprocessingOptions

    settings = Settings(_env_file=None, preprocessing_version="v2", preprocessing_denoise_method="adaptive")
    options = build_preprocessing_options(settings)
    assert options.version == "v2" and options.denoise_method == "adaptive"
    assert not options.v2_align_eyes and options.shadow_sample_rate == 0.1
    assert build_preprocessing_options(Settings(_env_file=None)).profile == PreprocessingOptions(version="v3").profile
    with pytest.raises(ValidationError):
        Settings(_env_file=None, preprocessing_max_detection_attempts=9)
