"""FastAPI application entrypoint."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .config import ROOT, get_settings
from .database import init_db
from .routes import auth, modules


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Erschliessungsumgebung")

    init_db()

    app.include_router(auth.router)
    app.include_router(modules.router)

    app.mount("/app", StaticFiles(directory=settings.app_dir, html=True), name="app")
    app.mount("/config", StaticFiles(directory=settings.config_dir), name="config")
    app.mount("/login", StaticFiles(directory=ROOT / "backend" / "static" / "login", html=True), name="login")

    @app.get("/")
    def root() -> RedirectResponse:
        return RedirectResponse("/login/")

    @app.get("/arbeitsbereiche")
    def workspace_page() -> FileResponse:
        return FileResponse(ROOT / "backend" / "static" / "login" / "arbeitsbereiche.html")

    return app


app = create_app()
