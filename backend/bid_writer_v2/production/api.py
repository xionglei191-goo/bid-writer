from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .service import ProductionService


class ProjectPayload(BaseModel):
    name: str
    industry: str = "通用"
    project_type: str = ""
    region: str = ""
    source_text: str = ""
    profile: dict[str, Any] = {}


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


class ConfirmPayload(BaseModel):
    reviewer: str


def build_router(service: ProductionService) -> APIRouter:
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
    def update_project(project_id: int, payload: ProjectUpdatePayload) -> dict[str, Any]:
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

    @router.post("/{project_id}/outline")
    def build_outline(project_id: int) -> dict[str, Any]:
        try:
            return service.build_outline(project_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/{project_id}/sections/{section_id}/generate")
    def generate_section(project_id: int, section_id: int) -> dict[str, Any]:
        try:
            return service.generate_section(project_id, section_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/{project_id}/generate-all")
    def generate_all(project_id: int) -> dict[str, Any]:
        try:
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
            return service.confirm_draft(draft_id, payload.reviewer)
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

    @router.post("/{project_id}/export")
    def export(project_id: int, payload: ExportPayload) -> dict[str, Any]:
        try:
            return service.export_project(project_id, payload.format)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    return router
