"""Standalone application of the processing module: it runs alone, next to the staging tables, without the ingest module's code."""
from __future__ import annotations

from fastapi import FastAPI

from app.core.api import create_base_app, mount_ui
from app.core.config import get_cors_origins, get_schema, get_ui_dir
from app.modules.eba_processing.presentation.router import build_router


def create_app(schema: str | None = None, ui_dir: str | None = None) -> FastAPI:
    app = create_base_app("EBA Data Explorer: processing", "Preview, profile, charts and validation of staged EBA data.", cors_origins=get_cors_origins())
    app.include_router(build_router(schema or get_schema()))
    mount_ui(app, ui_dir)
    return app


def app_from_env() -> FastAPI:
    return create_app(get_schema(), get_ui_dir())
