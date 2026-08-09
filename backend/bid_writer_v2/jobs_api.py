from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .jobs import JobService


class JobPayload(BaseModel):
    job_type: str
    target_type: str
    target_id: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


def build_router(service: JobService) -> APIRouter:
    router = APIRouter(prefix="/api/jobs", tags=["jobs"])

    @router.get("")
    def list_jobs(status: str = "", limit: int = Query(default=100, ge=1, le=500)) -> list[dict[str, Any]]:
        return service.list(status, limit)

    @router.post("", status_code=202)
    def enqueue(payload: JobPayload, request: Request, background_tasks: BackgroundTasks) -> dict[str, Any]:
        user = getattr(request.state, "user", None) or {}
        try:
            job = service.enqueue(payload.job_type, payload.target_type, payload.target_id, payload.payload, user.get("id"))
            if not service.settings.background_jobs_enabled:
                background_tasks.add_task(service.run, int(job["id"]))
            return job
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/{job_id}")
    def get_job(job_id: int) -> dict[str, Any]:
        try:
            return service.get(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/{job_id}/cancel", status_code=202)
    def cancel(job_id: int) -> dict[str, Any]:
        try:
            return service.cancel(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/{job_id}/retry", status_code=202)
    def retry(job_id: int, background_tasks: BackgroundTasks) -> dict[str, Any]:
        try:
            job = service.retry(job_id)
            if not service.settings.background_jobs_enabled:
                background_tasks.add_task(service.run, job_id)
            return job
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/{job_id}/run")
    def run(job_id: int) -> dict[str, Any]:
        try:
            return service.run(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/{job_id}/events")
    async def events(job_id: int, after: int = 0) -> StreamingResponse:
        service.get(job_id)

        async def stream():
            cursor = after
            while True:
                items = service.events(job_id, after_id=cursor)
                for item in items:
                    cursor = int(item["id"])
                    yield f"id: {cursor}\nevent: progress\ndata: {json.dumps(item, ensure_ascii=False)}\n\n"
                job = service.get(job_id)
                if job["status"] in {"completed", "failed", "cancelled"}:
                    yield f"event: terminal\ndata: {json.dumps({'status': job['status']}, ensure_ascii=False)}\n\n"
                    break
                await asyncio.sleep(0.75)

        return StreamingResponse(stream(), media_type="text/event-stream")

    return router
