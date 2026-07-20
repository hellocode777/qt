"""SimulationResult — structured output for broker-based backtests.

Replaces the flat dict from SimpleVectorBacktest with a typed result
including trade log, daily NAV, and benchmark comparison.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import polars as pl


@dataclass
class SimulationResult:
    """Complete result of a broker-based backtest simulation."""

    # Core metrics
    total_return_pct: float = 0.0
    annual_return_pct: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown_pct: float = 0.0
    annual_volatility_pct: float = 0.0
    calmar_ratio: float = 0.0

    # Trading statistics
    n_days: int = 0
    n_trades: int = 0
    n_buys: int = 0
    n_sells: int = 0
    turnover_pct: float = 0.0
    total_commission: float = 0.0
    total_stamp_tax: float = 0.0
    total_slippage: float = 0.0
    total_market_impact: float = 0.0
    total_cost: float = 0.0

    # Portfolio
    initial_capital: float = 1_000_000
    final_equity: float = 1_000_000
    max_equity: float = 1_000_000
    min_equity: float = 1_000_000

    # Benchmark comparison
    benchmark_return_pct: float = 0.0
    alpha_pct: float = 0.0
    information_ratio: float = 0.0

    # Diagnostics
    strategy_id: str = ""
    start_date: str = ""
    end_date: str = ""
    converged: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    # Detailed data
    daily_nav: pl.DataFrame | None = None
    trade_log: pl.DataFrame | None = None
    positions_log: pl.DataFrame | None = None

    def to_dict(self) -> dict:
        return {
            "total_return_pct": round(self.total_return_pct, 2),
            "annual_return_pct": round(self.annual_return_pct, 2),
            "sharpe_ratio": round(self.sharpe_ratio, 2),
            "max_drawdown_pct": round(self.max_drawdown_pct, 2),
            "annual_volatility_pct": round(self.annual_volatility_pct, 2),
            "calmar_ratio": round(self.calmar_ratio, 2),
            "n_days": self.n_days,
            "n_trades": self.n_trades,
            "total_cost": round(self.total_cost, 2),
            "initial_capital": self.initial_capital,
            "final_equity": round(self.final_equity, 2),
            "alpha_pct": round(self.alpha_pct, 2),
            "strategy_id": self.strategy_id,
            "start_date": self.start_date,
            "end_date": self.end_date,
        }

    def summary(self) -> str:
        """One-line summary."""
        return (
            f"[{self.strategy_id}] "
            f"Ret={self.total_return_pct:.1f}% "
            f"Sharpe={self.sharpe_ratio:.2f} "
            f"MaxDD={self.max_drawdown_pct:.1f}% "
            f"Trades={self.n_trades} "
            f"Cost={self.total_cost:.0f}"
        )
