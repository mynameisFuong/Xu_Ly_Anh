from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
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
    liveness_mode: Literal["off", "shadow", "enforce"] = "off"
    liveness_model_dir: Path | None = None
    liveness_backend: Literal["hog-svm", "minifasnet"] = "hog-svm"
    liveness_live_threshold: float = Field(default=0.90, gt=0.5, lt=1)
    liveness_allow_pretrained: bool = False
    web_liveness_required: bool = True
    web_liveness_ttl_seconds: float = Field(default=45, ge=10, le=120)
    web_liveness_max_gap_seconds: float = Field(default=5, ge=1, le=15)
    web_liveness_min_interval_seconds: float = Field(default=0.25, ge=0.1, le=2)
    web_liveness_hold_seconds: float = Field(default=0.5, ge=0.2, le=3)
    web_liveness_min_hits: int = Field(default=2, ge=2, le=6)
    web_liveness_identity_distance: float = Field(default=0.5, gt=0, le=0.6)
    web_liveness_yaw_degrees: float = Field(default=18, ge=12, le=30)
    web_liveness_pitch_degrees: float = Field(default=12, ge=8, le=25)

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()
