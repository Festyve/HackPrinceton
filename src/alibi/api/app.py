"""FastAPI application (grown milestone by milestone). Bound to localhost by default."""

from __future__ import annotations

from fastapi import FastAPI

from alibi import __version__
from alibi.config import Settings, load_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    app = FastAPI(title="ALIBI", version=__version__, docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.settings = settings

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True, "version": __version__}

    @app.get("/api/runtime")
    def runtime() -> dict:
        return settings.public_dict()

    return app
