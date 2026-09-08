from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..auth import AuthService
from .requirements_workflow import RequirementsWorkflow


class RequirementReviewItem(BaseModel):
    requirement_id: int
    expected_fingerprint: str = Field(min_length=1)
    category: Literal["technical", "qualification", "commercial", "contract", "reference", "unclassified"]
    reason: str = Field(min_length=1)
    applicability: Literal["applicable", "not_applicable"] = "applicable"
    response_text: str = ""
    basis_text: str = ""


class RequirementReviewPayload(BaseModel):
    reviewer: str = Field(min_length=1)
    expected_project_hash: str | None = None
    items: list[RequirementReviewItem] = Field(min_length=1, max_length=1000)


class RequirementMappingPayload(BaseModel):
    reviewer: str = Field(min_length=1)
    expected_fingerprint: str = Field(min_length=1)
    section_ids: list[int] = Field(default_factory=list, max_length=1000)


class RequirementResponsePayload(BaseModel):
    draft_id: int
    reviewer: str = Field(min_length=1)
    target_hash: str = Field(min_length=1)
    requirement_fingerprint: str = Field(min_length=1)
    evidence_text: str = Field(min_length=12, max_length=500)


def build_router(workflow: RequirementsWorkflow) -> APIRouter:
    router = APIRouter(prefix="/api/projects", tags=["requirements-workflow"])

    def reviewer_name(request: Request, supplied: str) -> str:
        user = getattr(request.state, "user", None)
        if user:
            if not AuthService.allowed(user, "review"):
                raise HTTPException(status_code=403, detail="只有复核人员可以确认条款分类和章节映射")
        # The authenticated actor is audited separately. A disabled-auth local
        # administrator must not silently replace the actual named reviewer.
        return supplied.strip()

    @router.get("/{project_id}/requirements/workflow")
    def get_workflow(project_id: int) -> dict:
        try:
            return workflow.snapshot(project_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/{project_id}/requirements/suggestions")
    def suggest(project_id: int) -> dict:
        try:
            return workflow.refresh_suggestions(project_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/{project_id}/requirements/review")
    def review(project_id: int, payload: RequirementReviewPayload, request: Request) -> dict:
        reviewer = reviewer_name(request, payload.reviewer)
        try:
            return workflow.review(project_id, reviewer, [item.model_dump() for item in payload.items], payload.expected_project_hash)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.put("/{project_id}/requirements/{requirement_id}/mapping")
    def map_requirement(project_id: int, requirement_id: int, payload: RequirementMappingPayload, request: Request) -> dict:
        reviewer = reviewer_name(request, payload.reviewer)
        try:
            return workflow.map_requirement(project_id, requirement_id, reviewer, payload.expected_fingerprint, payload.section_ids)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/{project_id}/requirements/{requirement_id}/response")
    def bind_response(project_id: int, requirement_id: int, payload: RequirementResponsePayload, request: Request) -> dict:
        reviewer = reviewer_name(request, payload.reviewer)
        try:
            return workflow.bind_response(project_id, requirement_id, payload.draft_id, reviewer,
                                          payload.target_hash, payload.requirement_fingerprint, payload.evidence_text)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    return router
