"""FastAPI application factory for the QP Decision Center.

Creates and configures the FastAPI app with:
  - Jinja2 templates
  - Static file serving
  - Router registration
  - Service initialization on startup
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

# Template and static directories (relative to package root)
_TEMPLATES_DIR = Path(__file__).parent / "templates"
_STATIC_DIR = Path(__file__).parent / "static"
_SPA_DIR = Path(__file__).parent / "static" / "spa"


def _register_spa_routes(app: FastAPI) -> None:
    """SPA 构建产物 → http://host/proto/*（含 history 路由 fallback）。

    注意: 新版 Starlette StaticFiles 对 not-found 是 raise HTTPException，
    在 FastAPI 下会被转成 JSON 404、且无法 override —— 故用手动路由 + FileResponse，
    并做目录穿越防护（resolved 必须位于 _SPA_DIR 内）。
    """

    async def spa_entry(request: Request) -> Response:
        raw = request.path_params.get("path", "")
        if raw:
            candidate = (_SPA_DIR / raw).resolve()
            if candidate.is_file() and candidate.is_relative_to(_SPA_DIR.resolve()):
                return FileResponse(candidate)
        # SPA history fallback / 未匹配资源 → index.html
        index = _SPA_DIR / "index.html"
        return (
            HTMLResponse(index.read_bytes(), media_type="text/html")
            if index.exists()
            else HTMLResponse("", status_code=404)
        )

    app.get("/proto", include_in_schema=False)(spa_entry)
    app.get("/proto/", include_in_schema=False)(spa_entry)
    app.get("/proto/{path:path}", include_in_schema=False)(spa_entry)


def create_app() -> FastAPI:
    """Create and configure the QP Web Decision Center application.

    Returns:
        A configured FastAPI app ready to serve with uvicorn.
    """
    # Ensure static dir exists
    _STATIC_DIR.mkdir(parents=True, exist_ok=True)

    app = FastAPI(
        title="QP Decision Center",
        description="Investment Decision Cockpit — Human-in-the-loop Decision Support",
        version="0.1.0",
        lifespan=_lifespan,
    )

    # Mount static files
    if _STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    # Mount SPA prototype (构建产物 qp/web/static/spa → http://host/proto/)
    if _SPA_DIR.exists():
        _register_spa_routes(app)
        logger.info("SPA prototype mounted at /proto ({})", _SPA_DIR)

    # Register routers
    _register_routers(app)

    # Store services on app state for router access
    logger.info("QP Decision Center app created")
    return app


def _register_routers(app: FastAPI) -> None:
    """Register all route modules."""
    from qp.web.routers.dashboard import router as dashboard_router
    from qp.web.routers.decisions import router as decisions_router
    from qp.web.routers.experiments import router as experiments_router
    from qp.web.routers.health import router as health_router
    from qp.web.routers.models import router as models_router
    from qp.web.routers.paper import router as paper_router
    from qp.web.routers.portfolio import router as portfolio_router
    from qp.web.routers.proposals import router as proposals_router
    from qp.web.routers.simulation import router as simulation_router
    from qp.web.routers.stocks import router as stocks_router
    from qp.web.routers.strategies import router as strategies_router

    app.include_router(dashboard_router)
    app.include_router(decisions_router)
    app.include_router(experiments_router)
    app.include_router(health_router)
    app.include_router(models_router)
    app.include_router(paper_router)
    app.include_router(portfolio_router)
    app.include_router(proposals_router)
    app.include_router(simulation_router)
    app.include_router(stocks_router)
    # Factor health router (L9 monitoring)
    from qp.web.routers.factors import router as factors_router

    app.include_router(factors_router)
    app.include_router(strategies_router)
    # API v1 (只读 JSON 端点，供 SPA 原型/外部工具)
    from qp.web.routers.api_v1 import router as api_v1_router

    app.include_router(api_v1_router)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: initialize services on startup."""
    from qp.web.services import (
        DataQualityService,
        DecisionService,
        ExperimentService,
        HealthService,
    )

    logger.info("QP Decision Center starting up...")

    # Initialize services
    app.state.decision_service = DecisionService()
    app.state.health_service = HealthService()
    app.state.experiment_service = ExperimentService()
    app.state.data_quality_service = DataQualityService()

    logger.info("QP Decision Center ready — services initialized")

    yield

    logger.info("QP Decision Center shutting down")
