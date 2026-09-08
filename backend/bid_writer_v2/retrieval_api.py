from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .jobs import JobService
from .retrieval import HybridRetrievalService


class SearchPayload(BaseModel):
    query: str
    industry: str = ""
    unit_type: str = ""
    limit: int = Field(default=12, ge=1, le=50)
    project_id: int | None = None


class FeedbackPayload(BaseModel):
    retrieval_run_id: int
    unit_id: int | None = None
    action: str
    notes: str = ""


def build_router(service: HybridRetrievalService, jobs: JobService) -> APIRouter:
    router = APIRouter(prefix="/api/search", tags=["retrieval"])

    @router.get("/status")
    def status() -> dict[str, Any]:
        return service.status()

    @router.post("/hybrid")
    def search(payload: SearchPayload, request: Request) -> dict[str, Any]:
        user = getattr(request.state, "user", None) or {}
        results = service.search(
            payload.query,
            payload.industry,
            payload.unit_type,
            payload.limit,
            project_id=payload.project_id,
            created_by=user.get("id"),
        )
        return {"items": results, "count": len(results), "index_version": results[0]["index_version"] if results else ""}

    @router.post("/indexes/rebuild", status_code=202)
    def rebuild(request: Request) -> dict[str, Any]:
        user = getattr(request.state, "user", None) or {}
        return jobs.enqueue("retrieval.rebuild", "knowledge_index", "active", {}, user.get("id"))

    @router.post("/feedback")
    def feedback(payload: FeedbackPayload, request: Request) -> dict[str, Any]:
        user = getattr(request.state, "user", None) or {}
        try:
            return service.feedback(payload.retrieval_run_id, payload.action, payload.unit_id, payload.notes, user.get("id"))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router
