"""PortfolioMetrics — portfolio-level performance metrics calculator.

Computes standard portfolio KPIs from a NAV time series:
  - Sharpe Ratio (annualized)
  - Max Drawdown (%)
  - Annualized Return
  - Annualized Volatility
  - Calmar Ratio
  - Alpha (vs benchmark, naive CAPM-style regression)

Usage:
    from qp.portfolio.nav_ledger import NAVLedger
    from qp.portfolio.metrics import PortfolioMetrics

    ledger = NAVLedger()
    nav_df = ledger.load_history()
    metrics = PortfolioMetrics.from_nav(nav_df)
    print(f"Sharpe: {metrics.sharpe_ratio:.2f}")
"""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl


@dataclass
class PortfolioMetrics:
    """Aggregated portfolio performance metrics."""

    sharpe_ratio: float
    max_drawdown_pct: float
    annualized_return_pct: float
    annualized_volatility_pct: float
    calmar_ratio: float
    alpha_pct: float
    total_return_pct: float
    n_days: int
    best_day_pct: float = 0.0
    worst_day_pct: float = 0.0
    positive_day_pct: float = 0.0
    benchmark_total_return_pct: float | None = None

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @staticmethod
    def from_nav(
        nav_df: pl.DataFrame,
        benchmark_df: pl.DataFrame | None = None,
        risk_free_rate: float = 0.03,
    ) -> PortfolioMetrics:
        """Compute all metrics from a NAV time-series DataFrame.

        Args:
            nav_df: Polars DataFrame with columns ``date`` and ``total_nav``
                    (sorted by date ascending).
            benchmark_df: Optional benchmark NAV with same columns.
            risk_free_rate: Annual risk-free rate (default 3% for China).

        Returns:
            PortfolioMetrics with all fields populated.

        If fewer than 5 rows of data exist, returns zero-valued metrics.
        """
        if nav_df.is_empty() or nav_df.height < 5:
            return PortfolioMetrics(
                sharpe_ratio=0.0,
                max_drawdown_pct=0.0,
                annualized_return_pct=0.0,
                annualized_volatility_pct=0.0,
                calmar_ratio=0.0,
                alpha_pct=0.0,
                total_return_pct=0.0,
                n_days=nav_df.height,
            )

        # Ensure sorted
        nav_sorted = nav_df.sort("date")
        nav_series = nav_sorted["total_nav"].to_list()

        # Daily log returns
        daily_returns: list[float] = []
        for i in range(1, len(nav_series)):
            if nav_series[i - 1] > 0:
                r = (nav_series[i] - nav_series[i - 1]) / nav_series[i - 1]
            else:
                r = 0.0
            daily_returns.append(r)

        n = len(daily_returns)
        if n == 0:
            return PortfolioMetrics(
                sharpe_ratio=0.0,
                max_drawdown_pct=0.0,
                annualized_return_pct=0.0,
                annualized_volatility_pct=0.0,
                calmar_ratio=0.0,
                alpha_pct=0.0,
                total_return_pct=0.0,
                n_days=0,
            )

        # Mean & std of daily returns
        import statistics

        mean_ret = statistics.mean(daily_returns)
        std_ret = statistics.stdev(daily_returns) if n > 1 else 0.0

        # Annualize (252 trading days)
        ann_ret = mean_ret * 252
        ann_vol = std_ret * (252**0.5)

        # Sharpe
        sharpe = (ann_ret - risk_free_rate) / ann_vol if ann_vol > 0 else 0.0

        # Max Drawdown
        peak = nav_series[0]
        max_dd = 0.0
        for v in nav_series:
            if v > peak:
                peak = v
            dd = (peak - v) / peak if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd

        # Calmar
        calmar = ann_ret / max_dd if max_dd > 0 else 0.0

        # Total return
        first_nav = nav_series[0]
        last_nav = nav_series[-1]
        total_ret = (last_nav - first_nav) / first_nav if first_nav > 0 else 0.0

        # Daily stats
        best_day = max(daily_returns)
        worst_day = min(daily_returns)
        pos_days = sum(1 for r in daily_returns if r > 0)
        pos_pct = pos_days / n if n > 0 else 0.0

        # Alpha (vs benchmark, simple CAPM-style)
        alpha = 0.0
        benchmark_ret = None
        if benchmark_df is not None and not benchmark_df.is_empty():
            bench_sorted = benchmark_df.sort("date")
            bench_nav = bench_sorted["total_nav"].to_list()
            bench_returns: list[float] = []
            for i in range(1, len(bench_nav)):
                if bench_nav[i - 1] > 0:
                    bench_returns.append(
                        (bench_nav[i] - bench_nav[i - 1]) / bench_nav[i - 1]
                    )
                else:
                    bench_returns.append(0.0)
            # Align lengths
            common_n = min(n, len(bench_returns))
            if common_n > 1:
                # portfolio_return = alpha + beta * benchmark_return
                port_slice = daily_returns[-common_n:]
                bench_slice = bench_returns[-common_n:]
                mean_p = statistics.mean(port_slice)
                mean_b = statistics.mean(bench_slice)
                # beta via covariance
                cov = (
                    sum(
                        (port_slice[i] - mean_p) * (bench_slice[i] - mean_b)
                        for i in range(common_n)
                    )
                    / (common_n - 1)
                    if common_n > 1
                    else 0.0
                )
                var_b = statistics.variance(bench_slice) if common_n > 1 else 1.0
                beta = cov / var_b if var_b > 0 else 1.0
                alpha = (mean_p - risk_free_rate / 252) - beta * (
                    mean_b - risk_free_rate / 252
                )
                alpha = alpha * 252  # Annualize

                bench_first = bench_nav[0] if bench_nav else 1.0
                bench_last = bench_nav[-1] if bench_nav else 1.0
                benchmark_ret = (
                    (bench_last - bench_first) / bench_first if bench_first > 0 else 0.0
                )

        return PortfolioMetrics(
            sharpe_ratio=round(sharpe, 4),
            max_drawdown_pct=round(max_dd * 100, 2),
            annualized_return_pct=round(ann_ret * 100, 2),
            annualized_volatility_pct=round(ann_vol * 100, 2),
            calmar_ratio=round(calmar, 4),
            alpha_pct=round(alpha * 100, 2),
            total_return_pct=round(total_ret * 100, 2),
            n_days=n,
            best_day_pct=round(best_day * 100, 4),
            worst_day_pct=round(worst_day * 100, 4),
            positive_day_pct=round(pos_pct * 100, 1),
            benchmark_total_return_pct=(
                round(benchmark_ret * 100, 2) if benchmark_ret is not None else None
            ),
        )

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Convert to dict for JSON serialization / web context."""
        return {
            "sharpe_ratio": self.sharpe_ratio,
            "max_drawdown_pct": self.max_drawdown_pct,
            "annualized_return_pct": self.annualized_return_pct,
            "annualized_volatility_pct": self.annualized_volatility_pct,
            "calmar_ratio": self.calmar_ratio,
            "alpha_pct": self.alpha_pct,
            "total_return_pct": self.total_return_pct,
            "n_days": self.n_days,
            "best_day_pct": self.best_day_pct,
            "worst_day_pct": self.worst_day_pct,
            "positive_day_pct": self.positive_day_pct,
            "benchmark_total_return_pct": self.benchmark_total_return_pct,
        }

    def rating(self) -> str:
        """Qualitative rating based on Sharpe ratio."""
        if self.n_days < 20:
            return "数据不足 / Insufficient Data"
        if self.sharpe_ratio >= 2.0:
            return "优秀 / Excellent"
        if self.sharpe_ratio >= 1.2:
            return "良好 / Good"
        if self.sharpe_ratio >= 0.5:
            return "一般 / Fair"
        return "较差 / Poor"
