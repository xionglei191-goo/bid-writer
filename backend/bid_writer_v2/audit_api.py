from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from .audit import AuditService


def build_router(service: AuditService) -> APIRouter:
    router = APIRouter(prefix="/api/audit", tags=["audit"])

    @router.get("/events")
    def events(
        limit: int = Query(default=200, ge=1, le=1000),
        target_type: str = "",
        target_id: str = "",
    ) -> list[dict[str, Any]]:
        return service.list_events(limit, target_type, target_id)

    @router.get("/verify")
    def verify() -> dict[str, Any]:
        return service.verify_chain()

    return router
