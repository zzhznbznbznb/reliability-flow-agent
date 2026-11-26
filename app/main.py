"""FastAPI application entry point."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.agent.session import AgentSessionManager
from app.api.agent_routes import router as agent_router
from app.api.evaluation_routes import router as evaluation_router
from app.api.experiment_routes import router as experiment_router
from app.api.process_routes import router as process_router
from app.api.reliability_routes import router as reliability_router
from app.api.schema_routes import router as schema_router
from app.api.simulation_routes import router as simulation_router
from app.config import Settings, get_settings
from app.experiments.store import ExperimentStore
from app.processes.store import (
    ProcessNotFound,
    ProcessStore,
    ProcessStoreError,
    VersionConflict,
)
from app.reliability.store import ReliabilityStore, ReliabilityStoreError


def create_app(
    *,
    settings: Settings | None = None,
    process_store: ProcessStore | None = None,
    reliability_store: ReliabilityStore | None = None,
    experiment_store: ExperimentStore | None = None,
    agent_manager: AgentSessionManager | None = None,
) -> FastAPI:
    app_settings = settings or get_settings()
    app = FastAPI(
        title=app_settings.app_name,
        version=app_settings.version,
        description="Natural-language process modeling and equipment reliability simulation.",
    )
    app.state.settings = app_settings
    app.state.process_store = process_store or ProcessStore(
        app_settings.data_dir / "processes"
    )
    app.state.reliability_store = reliability_store or ReliabilityStore(
        app_settings.data_dir / "reliability"
    )
    app.state.experiment_store = experiment_store or ExperimentStore(
        app_settings.experiments_dir
    )
    app.state.agent_manager = agent_manager or AgentSessionManager(app_settings)

    @app.on_event("startup")
    async def _start_agent_manager() -> None:
        await app.state.agent_manager.start()

    @app.on_event("shutdown")
    async def _shutdown_agent_manager() -> None:
        await app.state.agent_manager.shutdown()

    app.include_router(process_router)
    app.include_router(reliability_router)
    app.include_router(simulation_router)
    app.include_router(evaluation_router)
    app.include_router(experiment_router)
    app.include_router(schema_router)
    app.include_router(agent_router)

    @app.get("/health")
    def health() -> dict:
        return {
            "status": "ok",
            "service": app_settings.app_name,
            "version": app_settings.version,
            "phase": app_settings.phase,
        }

    @app.get("/api/meta")
    def meta() -> dict:
        return {
            "service": app_settings.app_name,
            "version": app_settings.version,
            "phase": app_settings.phase,
            "offline_capable": True,
            "llm": {
                "enabled": app_settings.llm_enabled,
                "provider": app_settings.llm_provider,
                "model": app_settings.llm_model,
                "base_url": app_settings.llm_base_url,
                "auth_mode": app_settings.llm_auth_mode,
                "required_for_simulation": False,
            },
        }

    @app.exception_handler(RequestValidationError)
    async def schema_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        issues = []
        for error in exc.errors():
            location = ".".join(str(part) for part in error.get("loc", []))
            issues.append(
                {
                    "severity": "error",
                    "code": "schema_invalid",
                    "message": f"{location}: {error.get('msg', '数据不合法')}",
                    "node_id": None,
                    "edge_id": None,
                    "field": location or None,
                }
            )
        return JSONResponse(
            status_code=422,
            content={
                "detail": "请求数据不符合 Schema",
                "valid": False,
                "issues": issues,
            },
        )

    @app.exception_handler(ProcessNotFound)
    async def process_not_found_handler(
        request: Request, exc: ProcessNotFound
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"detail": str(exc), "process_id": exc.process_id},
        )

    @app.exception_handler(VersionConflict)
    async def version_conflict_handler(
        request: Request, exc: VersionConflict
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={
                "detail": str(exc),
                "expected_version": exc.expected,
                "current_version": exc.actual,
            },
        )

    @app.exception_handler(ProcessStoreError)
    async def process_store_error_handler(
        request: Request, exc: ProcessStoreError
    ) -> JSONResponse:
        return JSONResponse(status_code=500, content={"detail": str(exc)})

    @app.exception_handler(ReliabilityStoreError)
    async def reliability_store_error_handler(
        request: Request, exc: ReliabilityStoreError
    ) -> JSONResponse:
        return JSONResponse(status_code=500, content={"detail": str(exc)})

    web_index = app_settings.web_dir / "index.html"
    if app_settings.web_dir.is_dir() and web_index.is_file():
        app.mount(
            "/",
            StaticFiles(directory=Path(app_settings.web_dir), html=True),
            name="web",
        )
    else:

        @app.get("/")
        def root() -> dict:
            return {
                "service": app_settings.app_name,
                "version": app_settings.version,
                "phase": app_settings.phase,
                "frontend_built": False,
                "message": "前端尚未构建。请执行 cd frontend && npm install && npm run build。",
            }

    return app


app = create_app()
