from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from pydantic import BaseModel, Field

from .pipeline import KnowledgePipelineService
from ..jobs import JobService


class ProcessDocumentRequest(BaseModel):
    document_id: int
    max_candidates: int = Field(default=12, ge=1, le=20)
    background: bool = True


class CandidateReviewRequest(BaseModel):
    action: str
    reviewer: str
    notes: str = ""


class AcceptReadyRequest(BaseModel):
    reviewer: str
    limit: int = Field(default=100, ge=1, le=500)


class SampleReviewRequest(BaseModel):
    candidate_id: int
    passed: bool
    reviewer: str
    notes: str = ""


def build_router(service: KnowledgePipelineService, jobs: JobService | None = None) -> APIRouter:
    router = APIRouter(prefix="/api/knowledge-ai", tags=["knowledge-ai"])

    @router.get("/metrics")
    def metrics() -> dict[str, int]:
        return service.metrics()

    @router.get("/runs")
    def runs(limit: int = Query(default=50, ge=1, le=200)) -> list[dict[str, Any]]:
        return service.list_runs(limit)

    @router.post("/runs", status_code=202)
    def process(payload: ProcessDocumentRequest, request: Request, background_tasks: BackgroundTasks) -> dict[str, Any]:
        try:
            if payload.background and jobs:
                user = getattr(request.state, "user", None) or {}
                job = jobs.enqueue(
                    "knowledge.ai.process",
                    "standard_document",
                    payload.document_id,
                    {"document_id": payload.document_id, "max_candidates": payload.max_candidates},
                    user.get("id"),
                )
                if not jobs.settings.background_jobs_enabled:
                    background_tasks.add_task(jobs.run, int(job["id"]))
                return job
            return service.process_document(payload.document_id, payload.max_candidates)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/candidates")
    def candidates(
        status: str = "",
        limit: int = Query(default=200, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return service.list_candidates(status=status, limit=limit)

    @router.post("/runs/{run_id}/auto-publish", status_code=202)
    def auto_publish(run_id: int, request: Request, background_tasks: BackgroundTasks) -> dict[str, Any]:
        if not jobs:
            raise HTTPException(status_code=503, detail="后台任务服务不可用")
        user = getattr(request.state, "user", None) or {}
        try:
            job = jobs.enqueue(
                "knowledge.auto_publish",
                "knowledge_pipeline_run",
                run_id,
                {"run_id": run_id},
                user.get("id"),
            )
            if not jobs.settings.background_jobs_enabled:
                background_tasks.add_task(jobs.run, int(job["id"]))
            return job
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/candidates/accept-ready")
    def accept_ready(payload: AcceptReadyRequest) -> dict[str, Any]:
        try:
            return service.accept_ready(payload.reviewer, payload.limit)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/candidates/{candidate_id}/review")
    def review(candidate_id: int, payload: CandidateReviewRequest) -> dict[str, Any]:
        try:
            return service.review_candidate(candidate_id, payload.action, payload.reviewer, payload.notes)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/tasks")
    def tasks(
        status: str = "open",
        limit: int = Query(default=200, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return service.list_tasks(status=status, limit=limit)

    @router.get("/documents/{document_id}/chunks")
    def chunks(document_id: int) -> list[dict[str, Any]]:
        return service.list_chunks(document_id)

    @router.get("/auto-publish-batches")
    def auto_publish_batches(limit: int = Query(default=100, ge=1, le=500)) -> list[dict[str, Any]]:
        return service.list_auto_publish_batches(limit)

    @router.post("/auto-publish-batches/{batch_id}/review")
    def review_auto_publish_batch(batch_id: int, payload: SampleReviewRequest) -> dict[str, Any]:
        try:
            return service.review_auto_publish_sample(batch_id, payload.candidate_id, payload.passed, payload.reviewer, payload.notes)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router
