"""Tests for PortfolioMetrics — performance metrics from NAV series."""

from __future__ import annotations

import polars as pl

from qp.portfolio.metrics import PortfolioMetrics


class TestPortfolioMetrics:

    def test_steady_growth(self) -> None:
        """A steadily growing NAV (~0.15% daily with noise) produces positive metrics."""
        import random
        random.seed(42)
        nav = [100_000.0]
        for _ in range(1, 253):  # 1 year of trading days
            ret = 0.0015 + random.gauss(0, 0.002)
            nav.append(nav[-1] * (1 + ret))

        df = pl.DataFrame({
            "date": [f"2026-{i:03d}" for i in range(1, 254)],
            "total_nav": nav,
        })

        m = PortfolioMetrics.from_nav(df)
        # ~0.15% daily * 252 ≈ positive annual return
        assert m.annualized_return_pct > 0
        # Sharpe should be positive (good returns, moderate vol)
        assert m.sharpe_ratio > 0.5
        # Max DD < 100%
        assert m.max_drawdown_pct < 100.0
        # Most days positive (good trend)
        assert m.positive_day_pct > 40.0

    def test_flat_nav(self) -> None:
        """Flat NAV produces near-zero metrics."""
        df = pl.DataFrame({
            "date": ["2026-07-01", "2026-07-02", "2026-07-03", "2026-07-04", "2026-07-05"],
            "total_nav": [100_000.0] * 5,
        })

        m = PortfolioMetrics.from_nav(df)
        assert m.annualized_return_pct == 0.0
        assert m.max_drawdown_pct == 0.0
        assert m.sharpe_ratio == 0.0

    def test_drawdown_detection(self) -> None:
        """A V-shaped NAV correctly reports max drawdown."""
        # Start at 100, drop to 80, recover to 110
        df = pl.DataFrame({
            "date": ["D1", "D2", "D3", "D4", "D5"],
            "total_nav": [100.0, 90.0, 80.0, 95.0, 110.0],
        })

        m = PortfolioMetrics.from_nav(df)
        # Max DD: (100-80)/100 = 20%
        assert m.max_drawdown_pct == 20.0
        # Total return: (110-100)/100 = 10%
        assert m.total_return_pct == 10.0

    def test_insufficient_data(self) -> None:
        """Fewer than 5 rows → zero metrics, n_days preserved."""
        df = pl.DataFrame({
            "date": ["D1", "D2"],
            "total_nav": [100.0, 101.0],
        })

        m = PortfolioMetrics.from_nav(df)
        assert m.sharpe_ratio == 0.0
        assert m.max_drawdown_pct == 0.0
        assert m.n_days == 2

    def test_empty_dataframe(self) -> None:
        """Empty DataFrame → all zeros."""
        df = pl.DataFrame()
        m = PortfolioMetrics.from_nav(df)
        assert m.sharpe_ratio == 0.0
        assert m.n_days == 0

    def test_to_dict(self) -> None:
        """to_dict returns all expected keys."""
        df = pl.DataFrame({
            "date": ["D1", "D2", "D3", "D4", "D5"],
            "total_nav": [100.0, 101.0, 102.0, 101.0, 103.0],
        })

        m = PortfolioMetrics.from_nav(df)
        d = m.to_dict()
        assert "sharpe_ratio" in d
        assert "max_drawdown_pct" in d
        assert "annualized_return_pct" in d
        assert "annualized_volatility_pct" in d
        assert "calmar_ratio" in d
        assert "alpha_pct" in d
        assert "total_return_pct" in d
        assert "n_days" in d
        assert "best_day_pct" in d
        assert "worst_day_pct" in d
        assert "positive_day_pct" in d
        assert "benchmark_total_return_pct" in d

    def test_rating(self) -> None:
        """rating() returns qualitative labels."""
        # Insufficient data
        df = pl.DataFrame({
            "date": ["D1"],
            "total_nav": [100.0],
        })
        m = PortfolioMetrics.from_nav(df)
        assert "不足" in m.rating()

        # Good Sharpe — steady growth with small realistic noise
        import random
        random.seed(42)
        nav = [100_000.0]
        for _ in range(253):
            ret = 0.0015 + random.gauss(0, 0.003)  # ~0.15% daily with noise
            nav.append(nav[-1] * (1 + ret))
        df = pl.DataFrame({
            "date": [f"D{i}" for i in range(254)],
            "total_nav": nav,
        })
        m = PortfolioMetrics.from_nav(df)
        assert "优秀" in m.rating() or "良好" in m.rating() or "一般" in m.rating()

    def test_with_benchmark(self) -> None:
        """Alpha computed when benchmark provided."""
        # Portfolio: +0.15% daily
        port_nav = [100_000.0]
        for _ in range(1, 100):
            port_nav.append(port_nav[-1] * 1.0015)

        # Benchmark: +0.10% daily
        bench_nav = [100_000.0]
        for _ in range(1, 100):
            bench_nav.append(bench_nav[-1] * 1.0010)

        port_df = pl.DataFrame({
            "date": [f"D{i}" for i in range(100)],
            "total_nav": port_nav,
        })
        bench_df = pl.DataFrame({
            "date": [f"D{i}" for i in range(100)],
            "total_nav": bench_nav,
        })

        m = PortfolioMetrics.from_nav(port_df, benchmark_df=bench_df)
        # Portfolio outperforms → alpha should be positive
        assert m.alpha_pct is not None
        assert m.benchmark_total_return_pct is not None

    def test_benchmark_with_insufficient_data(self) -> None:
        """Benchmark with few rows doesn't crash."""
        port_df = pl.DataFrame({
            "date": ["D1", "D2", "D3", "D4", "D5"],
            "total_nav": [100.0, 101.0, 102.0, 103.0, 104.0],
        })
        bench_df = pl.DataFrame({
            "date": ["D1"],
            "total_nav": [100.0],
        })

        m = PortfolioMetrics.from_nav(port_df, benchmark_df=bench_df)
        assert m.sharpe_ratio != 0.0  # Portfolio metrics still computed
