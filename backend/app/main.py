from fastapi import FastAPI

from backend.app.api import router
from backend.app.config import get_settings
from backend.app.database import create_all


def create_app() -> FastAPI:
    settings = get_settings()
    settings.storage_dir.mkdir(parents=True, exist_ok=True)

    app = FastAPI(
        title="AttendAI - Face Attendance API",
        version="1.0.0-demo",
        description="Hệ thống điểm danh lớp học bằng nhận diện khuôn mặt.",
    )
    app.include_router(router)

    @app.on_event("startup")
    def on_startup() -> None:
        create_all()

    return app


app = create_app()
