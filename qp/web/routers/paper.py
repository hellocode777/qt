"""Paper trading router — 30-day strategy validation dashboard.

GET "/paper" — paper trading runs overview with:
  - Per-run status cards (progress, equity, evaluation gates)
  - Equity curve for each run
  - Daily record table (date / equity / positions / trades / costs)

Data source: data/paper_trading/*_paper.json (PaperTradingTracker state).
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from loguru import logger

from qp.web.routers._templates import templates

router = APIRouter(tags=["paper"])

# Evaluation gates — must stay in sync with PaperTradingTracker.evaluate()
GATES = {
    "sharpe": {"label": "Sharpe", "metric": "sharpe", "ok": lambda v: v >= 0.5},
    "max_drawdown": {
        "label": "最大回撤",
        "metric": "max_drawdown",
        "ok": lambda v: v <= 20.0,
    },
    "signals": {
        "label": "日均信号数",
        "metric": "avg_signals",
        "ok": lambda v: 3 <= v <= 30,
    },
}


def _compute_metrics(run: Any) -> dict[str, Any]:
    """Compute current metrics from daily records (same formulas as evaluate()).

    Returns metrics even for in-progress runs so the UI can show live gate
    status. The final PASS/FAIL always comes from run.result (30 days done).
    """
    import numpy as np

    n = len(run.daily_records)
    if n == 0:
        return {
            "sharpe": None,
            "max_drawdown": None,
            "avg_signals": None,
            "has_data": False,
        }

    returns = np.array([r.daily_return for r in run.daily_records])
    sharpe = float(np.sqrt(252) * returns.mean() / returns.std()) if returns.std() > 0 else 0.0
    cum = np.cumprod(1 + returns)
    running_max = np.maximum.accumulate(cum)
    max_dd = float(np.abs(((cum - running_max) / running_max).min()) * 100) if len(cum) > 0 else 0.0
    avg_signals = float(np.mean([r.n_signals for r in run.daily_records]))
    return {
        "sharpe": sharpe,
        "max_drawdown": max_dd,
        "avg_signals": avg_signals,
        "has_data": True,
    }


def _build_run_view(strategy_id: str, run: Any) -> dict[str, Any]:
    """Build the template context for one paper trading run."""
    metrics = _compute_metrics(run)
    total_return = (run.current_equity / run.capital - 1) * 100 if run.capital > 0 else 0.0

    # Gate status: final verdict from run.result if present, else live snapshot
    gate_status: dict[str, dict[str, Any]] = {}
    for key, gate in GATES.items():
        value = metrics[gate["metric"]]
        if value is None:
            gate_status[key] = {
                "label": gate["label"],
                "value": None,
                "passed": None,
                "final": False,
                "has_data": False,
            }
        else:
            gate_status[key] = {
                "label": gate["label"],
                "value": value,
                "passed": gate["ok"](value),
                "final": bool(run.result),  # result only set when 30 days complete
                "has_data": True,
            }

    equity_data = [{"date": r.date, "equity": r.equity} for r in run.daily_records]

    status = "running"
    if run.is_complete and run.result:
        status = "passed" if run.result.passed else "failed"

    return {
        "strategy_id": strategy_id,
        "run_id": run.run_id,
        "capital": run.capital,
        "start_date": run.start_date,
        "elapsed_days": run.elapsed_days,
        "current_equity": run.current_equity,
        "total_return_pct": total_return,
        "total_return_fmt": f"{total_return:+.2f}%",
        "metrics": metrics,
        "gate_status": gate_status,
        "equity_data": json.dumps(equity_data),
        "daily_records": [
            {
                "date": r.date,
                "equity": r.equity,
                "cash": r.cash,
                "n_positions": r.n_positions,
                "n_signals": r.n_signals,
                "n_trades": r.n_trades,
                "daily_return_pct": r.daily_return * 100,
                "total_cost": r.total_cost,
            }
            for r in run.daily_records
        ],
        "result": (
            {
                "passed": run.result.passed,
                "total_return_pct": run.result.total_return_pct,
                "sharpe": run.result.sharpe_ratio,
                "max_drawdown": run.result.max_drawdown_pct,
                "recommendation": run.result.recommendation,
            }
            if run.result
            else None
        ),
        "status": status,
    }


@router.get("/paper", response_class=HTMLResponse)
async def paper_dashboard(request: Request) -> Any:
    """Paper trading overview — all active/completed runs."""
    from qp.simulation.paper_trading import PaperTradingTracker

    tracker = PaperTradingTracker()
    state_dir = tracker._data_dir

    runs: list[dict[str, Any]] = []
    if state_dir.exists():
        for state_file in sorted(state_dir.glob("*_paper.json")):
            strategy_id = state_file.name[: -len("_paper.json")]
            run = tracker.load(strategy_id)
            if run is not None:
                runs.append(_build_run_view(strategy_id, run))

    logger.info("Paper dashboard: {} run(s)", len(runs))

    return templates.TemplateResponse(
        request=request,
        name="paper.html",
        context={
            "runs": runs,
            "has_data": len(runs) > 0,
            "page_title": "模拟交易 Paper Trading — QP Decision Center",
        },
    )
