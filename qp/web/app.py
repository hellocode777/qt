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

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from loguru import logger

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

# Template and static directories (relative to package root)
_TEMPLATES_DIR = Path(__file__).parent / "templates"
_STATIC_DIR = Path(__file__).parent / "static"


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
    from qp.web.routers.portfolio import router as portfolio_router
    from qp.web.routers.proposals import router as proposals_router
    from qp.web.routers.simulation import router as simulation_router
    from qp.web.routers.strategies import router as strategies_router

    app.include_router(dashboard_router)
    app.include_router(decisions_router)
    app.include_router(experiments_router)
    app.include_router(health_router)
    app.include_router(models_router)
    app.include_router(portfolio_router)
    app.include_router(proposals_router)
    app.include_router(simulation_router)
    # Factor health router (L9 monitoring)
    from qp.web.routers.factors import router as factors_router
    app.include_router(factors_router)
    app.include_router(strategies_router)


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
