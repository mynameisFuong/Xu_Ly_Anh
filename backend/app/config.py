from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./attendance.db"
    storage_dir: Path = Path("./storage")
    camera_api_token: str = "change-me-camera-token"
    attendance_threshold: float = 0.65
    attendance_margin: float = 0.05
    attendance_min_hits: int = 3
    attendance_window_seconds: int = 4

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()
