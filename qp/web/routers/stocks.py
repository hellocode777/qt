"""Stocks router — Individual stock K-line charts and search.

GET "/stocks"          — Stock search/browse page
GET "/stocks/{code}"   — Single stock detail page with candlestick chart
GET "/api/stocks/{code}/kline" — JSON API for OHLCV data
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request
from loguru import logger

from qp.web.routers._templates import templates
from qp.web.services.stock_service import StockService

router = APIRouter(tags=["stocks"])


def _get_service(request: Request) -> StockService:
    """Get or lazily create StockService on app.state."""
    svc = getattr(request.app.state, "stock_service", None)
    if svc is None:
        svc = StockService()
        request.app.state.stock_service = svc  # type: ignore[attr-defined]
    return svc


@router.get("/stocks")
async def stock_list(request: Request, q: str = Query(default="", max_length=50)) -> Any:
    """Stock search/browse page."""
    svc = _get_service(request)
    results = svc.search_stocks(q, limit=50) if q else svc.search_stocks("", limit=50)

    logger.info("Stock search: q={!r} → {} results", q, len(results))

    return templates.TemplateResponse(
        request=request,
        name="stocks.html",
        context={
            "query": q,
            "results": results,
            "has_results": len(results) > 0,
            "page_title": "个股分析 Stocks — QP Decision Center",
        },
    )


@router.get("/stocks/{code}")
async def stock_detail(request: Request, code: str) -> Any:
    """Single stock detail page with K-line chart."""
    svc = _get_service(request)
    info = svc.get_stock_info(code)

    if info is None:
        logger.warning("Stock not found: {}", code)
        return templates.TemplateResponse(
            request=request,
            name="stock_detail.html",
            context={
                "stock": None,
                "code": code,
                "error": f"未找到股票代码: {code}",
                "page_title": f"{code} — QP Decision Center",
            },
            status_code=404,
        )

    logger.info("Stock detail: {} {}", code, info.get("name", "?"))

    return templates.TemplateResponse(
        request=request,
        name="stock_detail.html",
        context={
            "stock": info,
            "code": code,
            "error": None,
            "page_title": f"{info['name']} ({code}) — QP Decision Center",
        },
    )


@router.get("/api/stocks/{code}/kline")
async def stock_kline_api(
    request: Request,
    code: str,
    days: int = Query(default=365, ge=30, le=3650),
) -> Any:
    """JSON API returning OHLCV data for candlestick chart rendering."""
    svc = _get_service(request)
    kline = svc.get_kline(code, days=days)

    logger.info("K-line API: code={} days={} → {} rows", code, days, len(kline))

    return {"code": code, "days": days, "count": len(kline), "data": kline}
