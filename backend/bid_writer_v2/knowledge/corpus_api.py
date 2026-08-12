from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from .corpus import CorpusCompletionService


class ResolveTaskRequest(BaseModel):
    action: Literal["approve", "exclude"]
    resolution: str = Field(min_length=1, max_length=2000)


def _admin(request: Request) -> dict[str, Any]:
    user = getattr(request.state, "user", None) or {}
    if "admin" not in (user.get("roles") or []):
        raise HTTPException(status_code=403, detail="全库收口与法律/授权事项仅允许管理员操作")
    return user


def build_router(service: CorpusCompletionService) -> APIRouter:
    router = APIRouter(prefix="/api/knowledge", tags=["knowledge-corpus"])

    @router.post("/corpus-runs", status_code=202)
    def create_run(request: Request) -> dict[str, Any]:
        user = _admin(request)
        return service.create_run(user.get("id"))

    @router.get("/corpus-runs/{run_id}")
    def get_run(run_id: int, request: Request) -> dict[str, Any]:
        _admin(request)
        try:
            return service.get_run(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/corpus-runs/{run_id}/pause")
    def pause(run_id: int, request: Request) -> dict[str, Any]:
        _admin(request)
        return service.pause(run_id)

    @router.post("/corpus-runs/{run_id}/resume")
    def resume(run_id: int, request: Request) -> dict[str, Any]:
        _admin(request)
        return service.resume(run_id)

    @router.post("/corpus-runs/{run_id}/cancel")
    def cancel(run_id: int, request: Request) -> dict[str, Any]:
        _admin(request)
        return service.cancel(run_id)

    @router.get("/completion")
    def completion(run_id: int | None = None) -> dict[str, Any]:
        return service.completion(run_id)

    @router.get("/manual-tasks")
    def manual_tasks(request: Request, status: str = "open", limit: int = Query(default=500, ge=1, le=500)) -> list[dict[str, Any]]:
        _admin(request)
        return service.list_manual_tasks(status, limit)

    @router.post("/manual-tasks/{task_id}/resolve")
    def resolve_manual_task(task_id: int, payload: ResolveTaskRequest, request: Request) -> dict[str, Any]:
        user = _admin(request)
        try:
            return service.resolve_manual_task(task_id, payload.action, payload.resolution, user.get("id"))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router
