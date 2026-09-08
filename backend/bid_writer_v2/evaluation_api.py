from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from .evaluation import RetrievalEvaluationService
from .jobs import JobService


class GenerateSilverPayload(BaseModel):
    unit_id: int
    count: int = Field(default=8, ge=4, le=12)
    dataset_name: str = Field(default="default", min_length=1, max_length=100)


class ReviewCasePayload(BaseModel):
    action: str
    reviewer: str


class RunEvaluationPayload(BaseModel):
    dataset_name: str = Field(default="default", min_length=1, max_length=100)
    source_type: str = "silver"
    top_k: int = Field(default=10, ge=1, le=50)


class AiReviewPayload(BaseModel):
    dataset_name: str = Field(default="default", min_length=1, max_length=100)
    case_ids: list[int] = Field(default_factory=list, max_length=100)


class BatchReviewPayload(BaseModel):
    case_ids: list[int] = Field(min_length=1, max_length=500)
    action: str
    reviewer: str = Field(min_length=1, max_length=100)


def build_router(service: RetrievalEvaluationService, jobs: JobService | None = None) -> APIRouter:
    router = APIRouter(prefix="/api/evaluation", tags=["evaluation"])

    @router.get("/cases")
    def cases(dataset_name: str = "default", status: str = "", source_type: str = "") -> list[dict[str, Any]]:
        return service.list_cases(dataset_name, status, source_type)

    @router.get("/datasets")
    def datasets() -> list[dict[str, Any]]:
        return service.list_datasets()

    @router.post("/cases/generate-silver")
    def generate_silver(payload: GenerateSilverPayload) -> dict[str, Any]:
        try:
            return service.generate_silver_cases(payload.unit_id, payload.count, payload.dataset_name)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/cases/{case_id}/review")
    def review(case_id: int, payload: ReviewCasePayload) -> dict[str, Any]:
        try:
            return service.review_case(case_id, payload.action, payload.reviewer)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/cases/batch-review")
    def batch_review(payload: BatchReviewPayload) -> dict[str, Any]:
        try:
            return service.batch_review_cases(payload.case_ids, payload.action, payload.reviewer)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/cases/review-silver-ai", status_code=202)
    def review_silver_ai(payload: AiReviewPayload, request: Request) -> dict[str, Any]:
        if jobs is None:
            raise HTTPException(status_code=503, detail="后台任务服务不可用")
        user = getattr(request.state, "user", None) or {}
        return jobs.enqueue(
            "evaluation.review_silver",
            "retrieval_dataset",
            payload.dataset_name,
            {"dataset_name": payload.dataset_name, "case_ids": payload.case_ids},
            user.get("id"),
        )

    @router.post("/runs")
    def run(payload: RunEvaluationPayload) -> dict[str, Any]:
        if payload.source_type not in {"silver", "gold"}:
            raise HTTPException(status_code=400, detail="source_type必须为silver或gold")
        try:
            return service.run(payload.dataset_name, payload.source_type, payload.top_k)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/runs")
    def runs(limit: int = Query(default=20, ge=1, le=100)) -> list[dict[str, Any]]:
        return service.list_runs(limit)

    return router
