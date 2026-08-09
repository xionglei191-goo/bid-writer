from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .service import KnowledgeService
from ..utils import public_payload


class ScanRequest(BaseModel):
    limit: int | None = Field(default=None, ge=1)
    expand_archives: bool = True


class JobCreateRequest(BaseModel):
    source_ids: list[int] = Field(default_factory=list)
    limit: int = Field(default=100, ge=1, le=1000)


class RewriteRequest(BaseModel):
    related_unit_ids: list[int] = Field(default_factory=list)


class ReviewRequest(BaseModel):
    version_id: int
    action: str
    reviewer: str
    notes: str = ""


class PublishRequest(BaseModel):
    version_id: int
    publisher: str


class RetireRequest(BaseModel):
    reviewer: str


class BatchRunRequest(BaseModel):
    limit: int = Field(default=20, ge=1, le=200)


class SearchRequest(BaseModel):
    query: str
    industry: str = ""
    unit_type: str = ""
    limit: int = Field(default=12, ge=1, le=50)


def build_router(service: KnowledgeService) -> APIRouter:
    router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])

    @router.get("/metrics")
    def metrics() -> dict[str, Any]:
        return service.metrics()

    @router.post("/sources/scan")
    def scan_sources(payload: ScanRequest) -> dict[str, Any]:
        return public_payload(service.scan_sources(limit=payload.limit, expand_archives=payload.expand_archives))

    @router.get("/sources")
    def list_sources(
        status: str = "",
        query: str = "",
        limit: int = Query(default=100, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        return public_payload(service.list_sources(status=status, query=query, limit=limit, offset=offset))

    @router.post("/jobs")
    def create_jobs(payload: JobCreateRequest) -> dict[str, Any]:
        return service.create_jobs(payload.source_ids or None, payload.limit)

    @router.get("/jobs")
    def list_jobs(status: str = "", limit: int = Query(default=100, ge=1, le=500)) -> list[dict[str, Any]]:
        return public_payload(service.list_jobs(status=status, limit=limit))

    @router.post("/jobs/{job_id}/run")
    def run_job(job_id: int) -> dict[str, Any]:
        try:
            return public_payload(service.run_job(job_id))
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/jobs/{job_id}/ocr")
    def run_ocr(job_id: int) -> dict[str, Any]:
        try:
            return public_payload(service.run_ocr(job_id))
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/jobs/{job_id}/retry")
    def retry_job(job_id: int) -> dict[str, Any]:
        try:
            return service.retry_job(job_id)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/jobs/{job_id}/pause")
    def pause_job(job_id: int) -> dict[str, Any]:
        try:
            return service.pause_job(job_id)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/jobs/{job_id}/resume")
    def resume_job(job_id: int) -> dict[str, Any]:
        try:
            return service.resume_job(job_id)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/jobs/run-batch")
    def run_batch(payload: BatchRunRequest) -> dict[str, Any]:
        return service.run_pending_jobs(payload.limit)

    @router.get("/documents")
    def list_documents(limit: int = Query(default=100, ge=1, le=500), offset: int = Query(default=0, ge=0)) -> dict[str, Any]:
        return public_payload(service.list_documents(limit=limit, offset=offset))

    @router.get("/units")
    def list_units(
        status: str = "",
        unit_type: str = "",
        query: str = "",
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return service.list_units(status=status, unit_type=unit_type, query=query, limit=limit)

    @router.get("/units/{unit_id}")
    def get_unit(unit_id: int) -> dict[str, Any]:
        try:
            return service.get_unit(unit_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/units/{unit_id}/rewrite")
    def rewrite_unit(unit_id: int, payload: RewriteRequest) -> dict[str, Any]:
        try:
            return service.rewrite_unit(unit_id, payload.related_unit_ids)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/units/cluster")
    def cluster_units(limit: int = Query(default=2000, ge=1, le=10000)) -> dict[str, Any]:
        return service.cluster_units(limit)

    @router.post("/reviews/{unit_id}")
    def review_unit(unit_id: int, payload: ReviewRequest) -> dict[str, Any]:
        try:
            return service.review_unit(unit_id, payload.version_id, payload.action, payload.reviewer, payload.notes)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/publications")
    def publications(limit: int = Query(default=100, ge=1, le=500)) -> list[dict[str, Any]]:
        return public_payload(service.list_publications(limit))

    @router.post("/publications/{unit_id}")
    def publish(unit_id: int, payload: PublishRequest) -> dict[str, Any]:
        try:
            return public_payload(service.publish_unit(unit_id, payload.version_id, payload.publisher))
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/publications/{publication_id}/retire")
    def retire(publication_id: int, payload: RetireRequest) -> dict[str, Any]:
        try:
            return service.retire_publication(publication_id, payload.reviewer)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/publications/{publication_id}/restore")
    def restore(publication_id: int, payload: RetireRequest) -> dict[str, Any]:
        try:
            return service.restore_publication(publication_id, payload.reviewer)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/search")
    def search(payload: SearchRequest) -> list[dict[str, Any]]:
        return public_payload(service.search(payload.query, payload.industry, payload.unit_type, payload.limit))

    return router
