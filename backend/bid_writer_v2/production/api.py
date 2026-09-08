from __future__ import annotations

from typing import Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from .service import ProductionService
from ..auth import AuthService
from ..jobs import JobService
from ..utils import public_payload


class ProjectPayload(BaseModel):
    name: str
    industry: str = "通用"
    project_type: str = ""
    region: str = ""
    source_text: str = ""
    profile: dict[str, Any] = Field(default_factory=dict)


class ProjectUpdatePayload(BaseModel):
    name: str | None = None
    industry: str | None = None
    project_type: str | None = None
    region: str | None = None
    source_text: str | None = None
    profile: dict[str, Any] | None = None


class DraftUpdatePayload(BaseModel):
    content: str


class ExportPayload(BaseModel):
    format: str
    mode: Literal["review", "formal"] = "formal"
    background: bool = True


class GeneratePayload(BaseModel):
    background: bool = True


class ClaimResolutionPayload(BaseModel):
    action: str
    resolution: str


class QualityResolutionPayload(BaseModel):
    resolution: str


class ConfirmationResolutionPayload(BaseModel):
    index: int
    resolution: str


class ConfirmPayload(BaseModel):
    reviewer: str
    target_hash: str | None = None
    notes: str = ""
    resolutions: list[ConfirmationResolutionPayload] = Field(default_factory=list)


class FinalReviewPayload(BaseModel):
    project_hash: str = Field(min_length=1)
    professional_reviewer: str = Field(min_length=1)
    compliance_confirmed: bool
    manual_finalized: bool


def build_router(service: ProductionService, jobs: JobService | None = None) -> APIRouter:
    router = APIRouter(prefix="/api/projects", tags=["production"])

    @router.get("")
    def list_projects() -> list[dict[str, Any]]:
        return service.list_projects()

    @router.post("")
    def create_project(payload: ProjectPayload) -> dict[str, Any]:
        try:
            return service.create_project(payload.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/{project_id}")
    def get_project(project_id: int) -> dict[str, Any]:
        try:
            return service.get_project(project_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.patch("/{project_id}")
    def update_project(project_id: int, payload: ProjectUpdatePayload, request: Request) -> dict[str, Any]:
        if any((payload.profile or {}).get(key) is True for key in ("compliance_confirmed", "manual_finalized", "final_approved")):
            user = getattr(request.state, "user", None)
            if user and not AuthService.allowed(user, "review"):
                raise HTTPException(status_code=403, detail="只有复核人员可以确认合规和人工定稿")
        try:
            return service.update_project(project_id, payload.model_dump(exclude_none=True))
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/{project_id}/requirements/parse")
    def parse_requirements(project_id: int) -> dict[str, Any]:
        try:
            return service.parse_requirements(project_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/{project_id}/outline")
    def build_outline(project_id: int) -> dict[str, Any]:
        try:
            return service.build_outline(project_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/{project_id}/coverage")
    def coverage(project_id: int) -> dict[str, Any]:
        try:
            return service.coverage_matrix(project_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/{project_id}/sections/{section_id}/generate")
    def generate_section(project_id: int, section_id: int, payload: GeneratePayload, request: Request, background_tasks: BackgroundTasks) -> dict[str, Any]:
        try:
            if payload.background and jobs:
                user = getattr(request.state, "user", None) or {}
                job = jobs.enqueue(
                    "production.generate_section",
                    "project_section",
                    section_id,
                    {"project_id": project_id, "section_id": section_id},
                    user.get("id"),
                )
                if not jobs.settings.background_jobs_enabled:
                    background_tasks.add_task(jobs.run, int(job["id"]))
                return job
            return service.generate_section(project_id, section_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/{project_id}/generate-all")
    def generate_all(project_id: int, payload: GeneratePayload, request: Request, background_tasks: BackgroundTasks) -> dict[str, Any]:
        try:
            if payload.background and jobs:
                user = getattr(request.state, "user", None) or {}
                job = jobs.enqueue("production.generate_all", "project", project_id, {"project_id": project_id}, user.get("id"))
                if not jobs.settings.background_jobs_enabled:
                    background_tasks.add_task(jobs.run, int(job["id"]))
                return job
            return service.generate_all(project_id)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.patch("/drafts/{draft_id}")
    def update_draft(draft_id: int, payload: DraftUpdatePayload) -> dict[str, Any]:
        try:
            return service.update_draft(draft_id, payload.content)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/drafts/{draft_id}/confirm")
    def confirm_draft(draft_id: int, payload: ConfirmPayload) -> dict[str, Any]:
        try:
            return service.confirm_draft(
                draft_id,
                payload.reviewer,
                [item.model_dump() for item in payload.resolutions],
                payload.notes,
                payload.target_hash,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/{project_id}/quality")
    def quality(project_id: int) -> dict[str, Any]:
        try:
            return service.quality_gate(project_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/quality-issues/{issue_id}/resolve")
    def resolve_quality_issue(issue_id: int, payload: QualityResolutionPayload, request: Request) -> dict[str, Any]:
        user = getattr(request.state, "user", None) or {}
        try:
            return service.resolve_quality_issue(issue_id, payload.resolution, user.get("id"))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/drafts/{draft_id}/claims")
    def claims(draft_id: int) -> list[dict[str, Any]]:
        return service.evidence.list_claims(draft_id)

    @router.post("/claims/{claim_id}/resolve")
    def resolve_claim(claim_id: int, payload: ClaimResolutionPayload) -> dict[str, Any]:
        try:
            return service.evidence.resolve_claim(claim_id, payload.action, payload.resolution)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/{project_id}/manifests")
    def manifests(project_id: int) -> list[dict[str, Any]]:
        return service.list_manifests(project_id)

    @router.get("/{project_id}/preview")
    def preview(project_id: int) -> dict[str, Any]:
        try:
            return service.preview_project(project_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/{project_id}/final-review")
    def final_review(project_id: int, payload: FinalReviewPayload) -> dict[str, Any]:
        try:
            return service.confirm_final_review(project_id, **payload.model_dump())
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/{project_id}/deliveries")
    def deliveries(project_id: int) -> list[dict[str, Any]]:
        try:
            return service.list_deliveries(project_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/{project_id}/deliveries/{delivery_id}/download")
    def download(project_id: int, delivery_id: int) -> Response:
        try:
            artifact = service.download_delivery(project_id, delivery_id)
            return Response(content=artifact["data"], media_type=artifact["media_type"], headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{quote(artifact['file_name'])}",
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            })
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/{project_id}/export")
    def export(project_id: int, payload: ExportPayload, request: Request, background_tasks: BackgroundTasks) -> dict[str, Any]:
        try:
            if payload.background and jobs:
                user = getattr(request.state, "user", None) or {}
                job = jobs.enqueue(
                    "production.export",
                    "project",
                    project_id,
                    {"project_id": project_id, "format": payload.format, "mode": payload.mode},
                    user.get("id"),
                )
                if not jobs.settings.background_jobs_enabled:
                    background_tasks.add_task(jobs.run, int(job["id"]))
                return job
            return public_payload(service.export_project(project_id, payload.format, payload.mode))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    return router
