from fastapi import FastAPI

from backend.app.api import router
from backend.app.config import get_settings
from backend.app.database import create_all


def create_app() -> FastAPI:
    settings = get_settings()
    settings.storage_dir.mkdir(parents=True, exist_ok=True)

    app = FastAPI(
        title="Face Attendance MVP",
        version="0.1.0",
        description="Local-first face attendance system for one-camera MVP.",
    )
    app.include_router(router)

    @app.on_event("startup")
    def on_startup() -> None:
        create_all()

    return app


app = create_app()
