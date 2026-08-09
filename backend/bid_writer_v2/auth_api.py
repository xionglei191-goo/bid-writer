from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

from .auth import AuthService


class LoginPayload(BaseModel):
    username: str
    password: str


class CreateUserPayload(BaseModel):
    username: str
    display_name: str
    password: str
    roles: list[str]


class RolesPayload(BaseModel):
    roles: list[str]


class ActivePayload(BaseModel):
    active: bool


def _set_session(response: JSONResponse | RedirectResponse, session: dict[str, Any], secure: bool) -> None:
    response.set_cookie(AuthService.session_cookie, session["token"], httponly=True, secure=secure, samesite="lax", max_age=43200)
    response.set_cookie(AuthService.csrf_cookie, session["csrf"], httponly=False, secure=secure, samesite="lax", max_age=43200)


def build_router(service: AuthService) -> APIRouter:
    router = APIRouter(prefix="/api/auth", tags=["auth"])

    @router.get("/config")
    def config() -> dict[str, Any]:
        return service.config

    @router.post("/login")
    def login(payload: LoginPayload, request: Request) -> JSONResponse:
        try:
            session = service.login(payload.username, payload.password, request.client.host if request.client else "")
        except PermissionError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        response = JSONResponse({"user": session["user"], "expires_at": session["expires_at"]})
        _set_session(response, session, request.url.scheme == "https")
        return response

    @router.post("/logout")
    def logout(request: Request) -> JSONResponse:
        service.logout(request.cookies.get(AuthService.session_cookie, ""))
        response = JSONResponse({"status": "logged_out"})
        response.delete_cookie(AuthService.session_cookie)
        response.delete_cookie(AuthService.csrf_cookie)
        return response

    @router.get("/me")
    def me(request: Request) -> dict[str, Any]:
        user = getattr(request.state, "user", None)
        if not user:
            raise HTTPException(status_code=401, detail="未登录")
        return {"user": user}

    def require_admin(request: Request) -> dict[str, Any]:
        user = getattr(request.state, "user", None)
        if not user or not service.allowed(user, "*"):
            raise HTTPException(status_code=403, detail="只有管理员可以管理用户")
        return user

    @router.get("/users")
    def users(request: Request) -> list[dict[str, Any]]:
        require_admin(request)
        return service.list_users()

    @router.post("/users")
    def create_user(payload: CreateUserPayload, request: Request) -> dict[str, Any]:
        actor = require_admin(request)
        try:
            user_id = service.create_local_user(payload.username, payload.display_name, payload.password, payload.roles)
            service.audit.record("auth.user.create", "user", user_id, actor_user_id=actor.get("id"), details={"roles": payload.roles})
            return service.get_user(user_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.put("/users/{user_id}/roles")
    def set_roles(user_id: int, payload: RolesPayload, request: Request) -> dict[str, Any]:
        actor = require_admin(request)
        try:
            return service.set_roles(user_id, payload.roles, actor.get("id"))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.put("/users/{user_id}/active")
    def set_active(user_id: int, payload: ActivePayload, request: Request) -> dict[str, Any]:
        actor = require_admin(request)
        try:
            return service.set_active(user_id, payload.active, actor.get("id"))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/oidc/start")
    def oidc_start() -> RedirectResponse:
        try:
            return RedirectResponse(service.oidc_start())
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/oidc/callback")
    def oidc_callback(code: str, state: str, request: Request) -> RedirectResponse:
        try:
            session = service.oidc_callback(code, state)
        except (PermissionError, ValueError, httpx.HTTPError) as exc:
            raise HTTPException(status_code=401, detail="OIDC登录失败") from exc
        response = RedirectResponse("/#/")
        _set_session(response, session, request.url.scheme == "https")
        return response

    return router
