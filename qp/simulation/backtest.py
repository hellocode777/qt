"""SimpleVectorBacktest — vectorized backtest for Walking Skeleton."""

from __future__ import annotations

import polars as pl


class SimpleVectorBacktest:
    """Minimal vectorized backtest using equal-weight daily rebalance."""

    def run(
        self,
        prices: pl.DataFrame,
        signals: pl.DataFrame,
        *,
        initial_capital: float = 1_000_000,
    ) -> dict:
        """Run a simple backtest.

        Args:
            prices: DataFrame with [trade_date, symbol, close].
            signals: DataFrame with [trade_date, symbol, feature_value].
            initial_capital: Starting capital.

        Returns:
            Dict with metrics: total_return, sharpe, max_drawdown, annual_vol.
        """
        if prices.is_empty() or signals.is_empty():
            return self._empty_result()

        # Get unique signal symbols
        signal_symbols = signals["symbol"].unique().to_list()

        # Filter prices to signal stocks only
        px = prices.filter(pl.col("symbol").is_in(signal_symbols))
        if px.is_empty():
            return self._empty_result()

        # Daily returns per symbol
        px = px.sort(["symbol", "trade_date"])
        px = px.with_columns(
            pl.col("close").pct_change().over("symbol").alias("daily_return")
        )
        px = px.drop_nulls(subset=["daily_return"])

        # Equal weight portfolio return (average across selected stocks)
        portfolio_returns = px.group_by("trade_date").agg(
            pl.col("daily_return").mean().alias("portfolio_return")
        )
        portfolio_returns = portfolio_returns.sort("trade_date")

        returns = portfolio_returns["portfolio_return"].to_numpy()
        if len(returns) < 2:
            return self._empty_result()

        import numpy as np

        # Metrics
        cumulative = (1 + returns).prod()
        total_return = float(cumulative - 1)
        sharpe = float(np.sqrt(252) * returns.mean() / returns.std()) if returns.std() > 0 else 0.0

        # Max drawdown
        cum_returns = (1 + returns).cumprod()
        running_max = np.maximum.accumulate(cum_returns)
        drawdowns = (cum_returns - running_max) / running_max
        max_drawdown = float(drawdowns.min())

        annual_vol = float(returns.std() * np.sqrt(252))

        n_days = len(returns)
        return {
            "total_return": round(total_return * 100, 2),
            "annual_return_pct": round(total_return * 252 / n_days * 100, 2),
            "sharpe_ratio": round(sharpe, 2),
            "max_drawdown_pct": round(max_drawdown * 100, 2),
            "annual_volatility_pct": round(annual_vol * 100, 2),
            "n_days": n_days,
        }

    def _empty_result(self) -> dict:
        return {
            "total_return": 0.0,
            "annual_return_pct": 0.0,
            "sharpe_ratio": 0.0,
            "max_drawdown_pct": 0.0,
            "annual_volatility_pct": 0.0,
            "n_days": 0,
        }
