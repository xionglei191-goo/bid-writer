from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .database import Database
from .knowledge.api import build_router as build_knowledge_router
from .knowledge.service import KnowledgeService
from .llm import LlmClient
from .production.api import build_router as build_production_router
from .production.service import ProductionService
from .settings import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.ensure_directories()
    db = Database(settings.db_path)
    migrations = db.migrate()
    llm = LlmClient()
    knowledge = KnowledgeService(db, settings, llm)
    production = ProductionService(db, settings, knowledge, llm)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        settings.ensure_directories()
        db.migrate()
        yield

    app = FastAPI(title="技术标生产与知识工程系统", version="2.0.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.db = db
    app.state.knowledge = knowledge
    app.state.production = production
    app.state.initial_migrations = migrations

    @app.exception_handler(Exception)
    async def handle_error(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=500, content={"error": f"{type(exc).__name__}: {exc}"})

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        knowledge_metrics = knowledge.metrics()
        with db.connect() as conn:
            projects = int(conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0])
            deliveries = int(conn.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0])
        return {
            "version": "2.0.0",
            "architecture": "knowledge-engineering-first",
            "database": str(settings.db_path),
            "workspace": str(settings.workspace_root),
            "operations_enabled": settings.operations_enabled,
            "llm": llm.settings(),
            "knowledge": knowledge_metrics,
            "projects": projects,
            "deliveries": deliveries,
        }

    @app.get("/api/system/config")
    def system_config() -> dict[str, Any]:
        return {
            "paths": {
                "raw": str(settings.raw_root),
                "knowledge": str(settings.knowledge_root),
                "data": str(settings.data_root),
                "delivery": str(settings.delivery_root),
            },
            "knowledge_directories": {key: str(value) for key, value in settings.knowledge_directories.items()},
            "operations_enabled": settings.operations_enabled,
            "llm": llm.settings(),
        }

    @app.get("/api/templates/assets")
    def template_assets() -> dict[str, Any]:
        root = settings.knowledge_directories["assets"]
        items = [
            {
                "name": path.name,
                "path": str(path),
                "kind": "directory" if path.is_dir() else path.suffix.lower().lstrip("."),
                "size": path.stat().st_size if path.is_file() else 0,
            }
            for path in root.iterdir()
        ]
        return {"root": str(root), "items": items}

    app.include_router(build_knowledge_router(knowledge))
    app.include_router(build_production_router(production))

    frontend_dist = settings.app_root / "frontend" / "dist"
    assets_dir = frontend_dist / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="frontend-assets")

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str = ""):
        requested = frontend_dist / path
        if path and requested.exists() and requested.is_file():
            return FileResponse(requested)
        index = frontend_dist / "index.html"
        if index.exists():
            return FileResponse(index)
        return JSONResponse(status_code=503, content={"error": "React 前端尚未构建，请运行 npm install 和 npm run build。"})

    return app


app = create_app()
