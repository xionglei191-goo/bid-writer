from __future__ import annotations

from contextlib import asynccontextmanager
import logging
import secrets
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from .ai_api import build_router as build_ai_router
from .audit import AuditService
from .audit_api import build_router as build_audit_router
from .auth import AuthService
from .auth_api import build_router as build_auth_router
from .ai_runtime import (
    AiRuntime,
    KNOWLEDGE_ADJUDICATION_PROMPT,
    KNOWLEDGE_EXTRACTION_PROMPT,
    KNOWLEDGE_FORMAL_REVIEW_PROMPT,
    KNOWLEDGE_REVIEW_PROMPT,
    KNOWLEDGE_REWRITE_PROMPT,
    SECTION_DRAFT_PROMPT,
    SILVER_QUERY_PROMPT,
    SILVER_REVIEW_PROMPT,
)
from .database import Database
from .evaluation import RetrievalEvaluationService
from .evaluation_api import build_router as build_evaluation_router
from .knowledge.api import build_router as build_knowledge_router
from .knowledge.pipeline import KnowledgePipelineService
from .knowledge.corpus import CorpusCompletionService
from .knowledge.corpus_api import build_router as build_corpus_router
from .knowledge.pipeline_api import build_router as build_knowledge_pipeline_router
from .knowledge.service import KnowledgeService
from .jobs import JobService
from .jobs_api import build_router as build_jobs_router
from .llm import LlmClient
from .production.api import build_router as build_production_router
from .production.service import ProductionService
from .retrieval import HybridRetrievalService
from .retrieval_api import build_router as build_retrieval_router
from .settings import Settings
from .storage import ObjectStorage


logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.ensure_directories()
    db = Database(settings.db_path, database_url=settings.database_url)
    migrations = db.migrate()
    audit = AuditService(db)
    auth = AuthService(db, settings, audit)
    storage = ObjectStorage(db, settings)
    jobs = JobService(db, settings, audit)
    llm = LlmClient()
    ai_runtime = AiRuntime(db, llm)
    ai_runtime.register_prompts(
        KNOWLEDGE_REWRITE_PROMPT,
        SECTION_DRAFT_PROMPT,
        SILVER_QUERY_PROMPT,
        SILVER_REVIEW_PROMPT,
        KNOWLEDGE_EXTRACTION_PROMPT,
        KNOWLEDGE_REVIEW_PROMPT,
        KNOWLEDGE_ADJUDICATION_PROMPT,
        KNOWLEDGE_FORMAL_REVIEW_PROMPT,
    )
    knowledge = KnowledgeService(db, settings, llm, ai_runtime)
    knowledge_pipeline = KnowledgePipelineService(db, knowledge, ai_runtime)
    production = ProductionService(db, settings, knowledge, llm, ai_runtime, storage=storage, audit=audit)
    evaluation = RetrievalEvaluationService(db, knowledge, ai_runtime, audit)
    retrieval = HybridRetrievalService(db, settings, storage)
    corpus = CorpusCompletionService(db, knowledge, knowledge_pipeline, retrieval, ai_runtime, evaluation)
    knowledge.hybrid_search = retrieval.search

    jobs.register(
        "knowledge.ai.process",
        lambda payload, report, cancelled: knowledge_pipeline.process_document(
            int(payload["document_id"]), int(payload.get("max_candidates", 12)), progress=report, cancelled=cancelled
        ),
    )
    jobs.register(
        "knowledge.auto_publish",
        lambda payload, report, _cancelled: (
            report("adjudicating", 10, "开始低风险知识独立裁决", {"run_id": payload["run_id"]}),
            knowledge_pipeline.auto_publish_low_risk(int(payload["run_id"])),
        )[1],
    )
    jobs.register(
        "knowledge.corpus.tick",
        lambda payload, report, cancelled: corpus.run_tick(
            int(payload["run_id"]),
            progress=report,
            cancelled=cancelled,
            preferred_stage=str(payload.get("stage") or ""),
        ),
    )
    jobs.register("retrieval.rebuild", lambda _payload, report, cancelled: retrieval.build_index(report, cancelled))
    jobs.register(
        "evaluation.review_silver",
        lambda payload, report, _cancelled: (
            report("reviewing", 10, "开始独立复核白银评测问题", {"dataset_name": payload["dataset_name"]}),
            evaluation.review_silver_cases_ai(str(payload["dataset_name"]), payload.get("case_ids") or []),
        )[1],
    )
    jobs.register(
        "production.generate_section",
        lambda payload, report, _cancelled: (
            report("generating", 10, "开始生成章节", {"section_id": payload["section_id"]}),
            production.generate_section(int(payload["project_id"]), int(payload["section_id"])),
            report("completed", 100, "章节生成完成"),
        )[1],
    )
    jobs.register(
        "production.generate_all",
        lambda payload, report, cancelled: production.generate_all(
            int(payload["project_id"]), progress=report, cancelled=cancelled
        ),
    )
    jobs.register(
        "production.export",
        lambda payload, report, _cancelled: production.export_project(
            int(payload["project_id"]),
            str(payload.get("format", "docx")),
            str(payload.get("mode", "formal")),
            progress=report,
        ),
    )

    def schedule_index(_action: str, _payload: dict[str, Any]) -> None:
        active = db.row("SELECT id FROM app_jobs WHERE job_type='retrieval.rebuild' AND status IN ('pending','running','retrying') LIMIT 1")
        if not active:
            jobs.enqueue("retrieval.rebuild", "knowledge_index", "active")

    knowledge.on_publication_changed = schedule_index

    def dispatch_corpus(run_id: int, delay_ms: int = 0, desired: int = 1, stage: str = "") -> None:
        target_id = f"{run_id}:{stage or 'any'}"
        active = db.row(
            "SELECT COUNT(*) AS count FROM app_jobs WHERE job_type='knowledge.corpus.tick' AND target_id=? AND status IN ('pending','retrying','running')",
            (target_id,),
        )
        missing = max(0, int(desired) - int((active or {}).get("count", 0)))
        for _index in range(missing):
            jobs.enqueue("knowledge.corpus.tick", "corpus_run", target_id, {"run_id": run_id, "stage": stage}, delay_ms=delay_ms)

    corpus.dispatch = dispatch_corpus

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        settings.ensure_directories()
        db.migrate()
        jobs.redispatch_unfinished()
        yield

    app = FastAPI(title="技术标生产与知识工程系统", version="2.0.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.db = db
    app.state.knowledge = knowledge
    app.state.knowledge_pipeline = knowledge_pipeline
    app.state.production = production
    app.state.ai_runtime = ai_runtime
    app.state.evaluation = evaluation
    app.state.audit = audit
    app.state.auth = auth
    app.state.storage = storage
    app.state.jobs = jobs
    app.state.retrieval = retrieval
    app.state.corpus = corpus
    app.state.initial_migrations = migrations

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None) or request.headers.get("X-Request-ID") or uuid4().hex
        detail = exc.detail if isinstance(exc.detail, str) else "请求未完成"
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": detail, "code": f"http_{exc.status_code}", "request_id": request_id},
            headers={"X-Request-ID": request_id},
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None) or request.headers.get("X-Request-ID") or uuid4().hex
        return JSONResponse(
            status_code=422,
            content={"error": "请求参数无效", "code": "validation_error", "request_id": request_id, "fields": exc.errors()},
            headers={"X-Request-ID": request_id},
        )

    @app.exception_handler(Exception)
    async def handle_error(request: Request, exc: Exception) -> JSONResponse:
        request_id = request.headers.get("X-Request-ID") or uuid4().hex
        logger.exception("Unhandled request error request_id=%s path=%s", request_id, request.url.path, exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={"error": "服务器内部错误", "code": "internal_error", "request_id": request_id},
            headers={"X-Request-ID": request_id},
        )

    @app.middleware("http")
    async def security_and_audit(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or uuid4().hex
        request.state.request_id = request_id
        user: dict[str, Any] | None
        if settings.auth_enabled:
            public = (
                request.url.path in {"/api/status", "/api/health/live", "/api/health/ready", "/api/auth/config", "/api/auth/login"}
                or request.url.path.startswith("/api/auth/oidc/")
                or not request.url.path.startswith("/api/")
            )
            user = auth.authenticate(request.cookies.get(AuthService.session_cookie, ""))
            if not public and not user:
                return JSONResponse(status_code=401, content={"error": "请先登录", "code": "authentication_required", "request_id": request_id})
            if user and request.method not in {"GET", "HEAD", "OPTIONS"} and request.url.path != "/api/auth/login":
                csrf_header = request.headers.get("X-CSRF-Token", "")
                csrf_cookie = request.cookies.get(AuthService.csrf_cookie, "")
                if not csrf_header or not secrets.compare_digest(csrf_header, csrf_cookie) or csrf_header != user.get("csrf_token"):
                    return JSONResponse(status_code=403, content={"error": "CSRF校验失败", "code": "csrf_failed", "request_id": request_id})
            permission = "read" if request.method in {"GET", "HEAD", "OPTIONS"} else "write"
            if "/publish" in request.url.path or "/publications" in request.url.path:
                permission = "publish"
            elif "/confirm" in request.url.path or "/review" in request.url.path:
                permission = "review"
            elif "/export" in request.url.path:
                permission = "export"
            elif request.url.path.startswith("/api/audit") or request.url.path.startswith("/api/system"):
                permission = "*"
            if user and not public and not auth.allowed(user, permission):
                return JSONResponse(status_code=403, content={"error": "权限不足", "code": "permission_denied", "request_id": request_id})
        else:
            user = {"id": None, "username": "local", "display_name": "本地管理员", "roles": ["admin"]}
        request.state.user = user
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        if request.method not in {"GET", "HEAD", "OPTIONS"} and request.url.path.startswith("/api/"):
            audit.record(
                "http.mutation",
                "api",
                request.url.path,
                actor_user_id=user.get("id") if user else None,
                actor_name=user.get("username", "anonymous") if user else "anonymous",
                outcome="success" if response.status_code < 400 else "failed",
                details={"method": request.method, "status": response.status_code},
                request_id=request_id,
            )
        return response

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        knowledge_metrics = knowledge.metrics()
        with db.connect() as conn:
            projects = int(conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0])
            deliveries = int(conn.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0])
            latest_ai_run = conn.execute(
                "SELECT status,error_code,completed_at FROM ai_runs ORDER BY id DESC LIMIT 1"
            ).fetchone()
        llm_status = {key: value for key, value in llm.settings().items() if key not in {"base_url", "api_key"}}
        llm_status.update(
            {
                "operational": bool(latest_ai_run and latest_ai_run["status"] in {"succeeded", "cached"}),
                "last_status": str(latest_ai_run["status"] if latest_ai_run else "unknown"),
                "last_error_code": str(latest_ai_run["error_code"] if latest_ai_run else ""),
                "last_completed_at": str(latest_ai_run["completed_at"] if latest_ai_run else ""),
            }
        )
        return {
            "version": "2.0.0",
            "architecture": "knowledge-engineering-first",
            "database": db.backend,
            "operations_enabled": settings.operations_enabled,
            "llm": llm_status,
            "ai": ai_runtime.metrics(),
            "knowledge": knowledge_metrics,
            "projects": projects,
            "deliveries": deliveries,
            "jobs": jobs.metrics(),
            "retrieval": retrieval.status(),
        }

    @app.get("/api/health/live")
    def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/health/ready")
    def ready() -> dict[str, Any]:
        database_ok = False
        try:
            database_ok = bool(db.row("SELECT 1 AS ok"))
        except Exception:
            database_ok = False
        storage_health = storage.health()
        payload = {"status": "ok" if database_ok and storage_health["status"] == "ok" else "degraded", "database": database_ok, "storage": storage_health}
        return payload

    @app.get("/metrics", include_in_schema=False)
    def prometheus_metrics() -> Response:
        try:
            from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Gauge, generate_latest

            registry = CollectorRegistry()
            gauge = Gauge("bid_writer_jobs", "Bid writer jobs by status", ["status"], registry=registry)
            for job_status, count in jobs.metrics().items():
                gauge.labels(status=job_status).set(count)
            ai_status = Gauge("bid_writer_ai_runs", "AI runs by status", ["status"], registry=registry)
            for row in db.rows("SELECT status,COUNT(*) AS count FROM ai_runs GROUP BY status"):
                ai_status.labels(status=row["status"]).set(int(row["count"]))
            ai_totals = db.row(
                "SELECT COALESCE(SUM(input_tokens),0) AS input_tokens,COALESCE(SUM(output_tokens),0) AS output_tokens,COALESCE(AVG(latency_ms),0) AS latency_ms FROM ai_runs"
            ) or {}
            ai_tokens = Gauge("bid_writer_ai_tokens_total", "Recorded AI tokens", ["direction"], registry=registry)
            ai_tokens.labels(direction="input").set(int(ai_totals.get("input_tokens") or 0))
            ai_tokens.labels(direction="output").set(int(ai_totals.get("output_tokens") or 0))
            Gauge("bid_writer_ai_latency_ms", "Average AI latency in milliseconds", registry=registry).set(float(ai_totals.get("latency_ms") or 0))
            retrieval_metrics = db.row(
                "SELECT COUNT(*) AS count,COALESCE(AVG(latency_ms),0) AS latency_ms FROM retrieval_runs_v2"
            ) or {}
            Gauge("bid_writer_retrieval_runs_total", "Recorded retrieval runs", registry=registry).set(int(retrieval_metrics.get("count") or 0))
            Gauge("bid_writer_retrieval_latency_ms", "Average retrieval latency in milliseconds", registry=registry).set(float(retrieval_metrics.get("latency_ms") or 0))
            published = db.row("SELECT COUNT(*) AS count FROM knowledge_publications WHERE status='published'") or {}
            Gauge("bid_writer_published_knowledge", "Currently published knowledge units", registry=registry).set(int(published.get("count") or 0))
            Gauge("bid_writer_storage_healthy", "Object storage health", registry=registry).set(1 if storage.health()["status"] == "ok" else 0)
            Gauge("bid_writer_audit_chain_valid", "Audit hash chain validity", registry=registry).set(1 if audit.verify_chain()["valid"] else 0)
            return Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)
        except Exception:
            return Response("# metrics unavailable\n", media_type="text/plain")

    @app.get("/api/system/config")
    def system_config() -> dict[str, Any]:
        return {
            "paths": {
                "raw": "原始标书库（只读）",
                "knowledge": "知识库",
                "data": "运行数据",
                "delivery": "交付与报告",
            },
            "knowledge_directories": {key: value.name for key, value in settings.knowledge_directories.items()},
            "operations_enabled": settings.operations_enabled,
            "llm": {key: value for key, value in llm.settings().items() if key not in {"base_url", "api_key"}},
            "database": db.backend,
            "storage": storage.mode,
            "auth": auth.config,
        }

    @app.get("/api/templates/assets")
    def template_assets() -> dict[str, Any]:
        root = settings.knowledge_directories["assets"]
        items = [
            {
                "name": path.name,
                "path_name": path.name,
                "kind": "directory" if path.is_dir() else path.suffix.lower().lstrip("."),
                "size": path.stat().st_size if path.is_file() else 0,
            }
            for path in root.iterdir()
        ]
        return {"root_name": root.name, "items": items}

    app.include_router(build_knowledge_router(knowledge))
    app.include_router(build_corpus_router(corpus))
    app.include_router(build_knowledge_pipeline_router(knowledge_pipeline, jobs))
    app.include_router(build_production_router(production, jobs))
    app.include_router(build_ai_router(ai_runtime))
    app.include_router(build_evaluation_router(evaluation, jobs))
    app.include_router(build_auth_router(auth))
    app.include_router(build_jobs_router(jobs))
    app.include_router(build_retrieval_router(retrieval, jobs))
    app.include_router(build_audit_router(audit))

    frontend_dist = settings.app_root / "frontend" / "dist"
    assets_dir = frontend_dist / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="frontend-assets")

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(request: Request, path: str = ""):
        if path == "api" or path.startswith("api/"):
            request_id = getattr(request.state, "request_id", None) or uuid4().hex
            return JSONResponse(
                status_code=404,
                content={"error": "接口不存在", "code": "http_404", "request_id": request_id},
                headers={"X-Request-ID": request_id},
            )
        requested = frontend_dist / path
        if path and requested.exists() and requested.is_file():
            return FileResponse(requested)
        index = frontend_dist / "index.html"
        if index.exists():
            return FileResponse(index)
        return JSONResponse(status_code=503, content={"error": "React 前端尚未构建，请运行 npm install 和 npm run build。"})

    return app


app = create_app()
