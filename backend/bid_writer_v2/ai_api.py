from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from .ai_runtime import AiRuntime


def build_router(runtime: AiRuntime) -> APIRouter:
    router = APIRouter(prefix="/api/ai", tags=["ai-runtime"])

    @router.get("/metrics")
    def metrics() -> dict[str, Any]:
        return runtime.metrics()

    @router.get("/runs")
    def runs(
        status: str = "",
        task_type: str = "",
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return runtime.list_runs(limit=limit, status=status, task_type=task_type)

    @router.get("/prompts")
    def prompts() -> list[dict[str, Any]]:
        return runtime.list_prompts()

    return router
