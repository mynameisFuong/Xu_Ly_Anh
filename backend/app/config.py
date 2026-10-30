from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./attendance.db"
    storage_dir: Path = Path("./storage")
    camera_api_token: str = "change-me-camera-token"
    attendance_threshold: float = 0.65
    attendance_margin: float = 0.05
    attendance_min_hits: int = Field(default=3, ge=1, le=20)
    attendance_window_seconds: int = Field(default=4, ge=1, le=60)
    face_distance_threshold: float = 0.52
    face_distance_margin: float = 0.04
    enrollment_num_jitters: int = 3
    stream_max_faces_per_frame: int = Field(default=8, ge=1, le=32)
    stream_confirmation_window_seconds: int = Field(default=30, ge=4, le=120)
    face_detection_backend: Literal["hog", "hybrid", "yunet"] = "hog"
    face_detection_model_path: Path = Path("storage/face-models/face_detection_yunet_2023mar.onnx")
    face_detection_score_threshold: float = Field(default=0.9, ge=0.5, lt=1)
    face_detection_max_side: int = Field(default=640, ge=320, le=1280)
    preprocessing_mode: Literal["off", "shadow", "enforce"] = "off"
    preprocessing_align_eyes: bool = True
    preprocessing_normalize_lighting: bool = True
    preprocessing_search_rotations: bool = True
    preprocessing_search_rolls: bool = True
    preprocessing_mirror_input: bool = False
    preprocessing_max_roll_degrees: float = Field(default=40, gt=0, le=60)
    preprocessing_version: Literal["v1", "v2"] = "v1"
    preprocessing_lighting_method: Literal["none", "adaptive", "gamma", "clahe"] = "adaptive"
    preprocessing_denoise_method: Literal["off", "adaptive", "median", "bilateral"] = "off"
    preprocessing_v2_align_eyes: bool = False
    preprocessing_roi_padding: float = Field(default=0.25, ge=0, le=0.5)
    preprocessing_gamma_min: float = Field(default=0.65, gt=0, le=1)
    preprocessing_gamma_max: float = Field(default=1.4, ge=1, le=2)
    preprocessing_clahe_clip_limit: float = Field(default=1.5, gt=0, le=4)
    preprocessing_max_detection_attempts: int = Field(default=8, ge=1, le=8)
    # Sample v2 alongside an enforced v1 without changing its templates/decisions.
    preprocessing_shadow_v2: bool = True
    preprocessing_shadow_sample_rate: float = Field(default=0.1, ge=0, le=1)

    @model_validator(mode="before")
    @classmethod
    def ignore_retired_liveness_settings(cls, values):
        # Old .env files must still boot; retired switches cannot reactivate PAD.
        if isinstance(values, dict):
            return {key: value for key, value in values.items()
                    if not key.lower().startswith(("liveness_", "web_liveness_"))}
        return values

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()
