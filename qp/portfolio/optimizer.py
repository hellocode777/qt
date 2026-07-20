"""MeanVarianceOptimizer — max Sharpe ratio portfolio optimization.

Uses scipy SLSQP with Ledoit-Wolf covariance shrinkage for robust
weight estimation.  Falls back to analytical risk-parity when scipy
is not available or optimization fails.

Constraints:
  - Σwᵢ = 1 - cash_buffer
  - 0 ≤ wᵢ ≤ w_max (default 8%)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np
import polars as pl

if TYPE_CHECKING:
    from scipy.optimize import OptimizeResult

DEFAULT_CASH_BUFFER = 0.05
DEFAULT_MAX_WEIGHT = 0.08
DEFAULT_LOOKBACK = 60
MIN_OBSERVATIONS = 30


@dataclass
class OptimizationResult:
    """Output of portfolio optimization."""

    weights: dict[str, float]
    expected_return: float
    expected_volatility: float
    sharpe_ratio: float
    converged: bool = True
    message: str = ""
    iterations: int = 0
    fallback_used: bool = False
    diagnostics: dict = field(default_factory=dict)


class MeanVarianceOptimizer:
    """Max Sharpe ratio portfolio optimizer.

    Objective: max (w^T μ - rf) / sqrt(w^T Σ w)
    Subject to: Σwᵢ = 1 - cash_buffer, 0 ≤ wᵢ ≤ w_max

    Uses Ledoit-Wolf covariance shrinkage for robust estimation.

    Usage:
        opt = MeanVarianceOptimizer(cash_buffer=0.05, max_weight=0.08)
        result = opt.optimize(prices_df, symbols, total_capital)
    """

    def __init__(
        self,
        cash_buffer: float = DEFAULT_CASH_BUFFER,
        max_weight: float = DEFAULT_MAX_WEIGHT,
        lookback: int = DEFAULT_LOOKBACK,
        risk_free_rate: float = 0.02,  # 2% annual
    ) -> None:
        self._cash_buffer = cash_buffer
        self._max_weight = max_weight
        self._lookback = lookback
        self._risk_free_rate = risk_free_rate

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def optimize(
        self,
        prices: pl.DataFrame,
        symbols: list[str],
        total_capital: float = 1_000_000,
    ) -> OptimizationResult:
        """Find max Sharpe weights for the given symbols.

        Args:
            prices: DataFrame with [trade_date, symbol, close].
            symbols: List of symbols to include.
            total_capital: Total portfolio capital (for amount calculation).

        Returns:
            OptimizationResult with weights and diagnostics.
        """
        if len(symbols) == 0:
            return OptimizationResult(
                weights={},
                expected_return=0.0,
                expected_volatility=0.0,
                sharpe_ratio=0.0,
                converged=False,
                message="No symbols provided",
            )

        # Special case: single asset
        if len(symbols) == 1:
            wt = 1.0 - self._cash_buffer
            return OptimizationResult(
                weights={symbols[0]: wt},
                expected_return=0.0,
                expected_volatility=0.0,
                sharpe_ratio=0.0,
                message="Single asset — weight = 1 - cash_buffer",
            )

        # Get return matrix
        returns_matrix, valid_symbols = self._build_return_matrix(prices, symbols)
        if len(valid_symbols) < 2:
            return self._equal_weight_fallback(
                symbols,
                msg=f"Only {len(valid_symbols)} symbols with sufficient data",
            )

        # Estimate expected returns (annualized) and covariance
        mu = returns_matrix.mean(axis=0) * 252
        sigma = self._ledoit_wolf_shrinkage(returns_matrix) * 252

        n = len(valid_symbols)

        try:
            from scipy.optimize import Bounds, LinearConstraint, minimize

            # Objective: negative Sharpe (minimize)
            def neg_sharpe(w: np.ndarray) -> float:
                port_ret = float(np.dot(w, mu))
                port_vol = float(np.sqrt(np.dot(w.T, np.dot(sigma, w))))
                if port_vol < 1e-10:
                    return 1e10  # Penalty for zero-vol
                return float(-(port_ret - self._risk_free_rate) / port_vol)

            # Initial guess: equal weight
            w0 = np.full(n, (1.0 - self._cash_buffer) / n)

            # Constraints
            constraints = LinearConstraint(
                np.ones(n),  # sum of weights
                lb=1.0 - self._cash_buffer,
                ub=1.0 - self._cash_buffer,
            )

            bounds = Bounds(lb=0.0, ub=self._max_weight)

            result: OptimizeResult = minimize(
                neg_sharpe,
                w0,
                method="SLSQP",
                bounds=bounds,
                constraints=constraints,
                options={"maxiter": 500, "ftol": 1e-10},
            )

            if result.success:
                weights_raw = result.x
                weights_raw = np.maximum(weights_raw, 0.0)  # Clip negatives
                weights_raw /= weights_raw.sum()  # Renormalize
                weights_raw *= (1.0 - self._cash_buffer)

                w_dict = {
                    sym: round(float(weights_raw[i]), 6)
                    for i, sym in enumerate(valid_symbols)
                }

                port_ret = float(np.dot(weights_raw, mu))
                port_vol = float(np.sqrt(np.dot(weights_raw.T, np.dot(sigma, weights_raw))))
                sharpe = float((port_ret - self._risk_free_rate) / port_vol) if port_vol > 0 else 0.0

                return OptimizationResult(
                    weights=w_dict,
                    expected_return=round(port_ret, 6),
                    expected_volatility=round(port_vol, 6),
                    sharpe_ratio=round(sharpe, 4),
                    converged=True,
                    message=result.message,
                    iterations=result.nit,
                    diagnostics={"method": "SLSQP"},
                )
            else:
                return self._equal_weight_fallback(
                    valid_symbols,
                    msg=f"Optimization failed: {result.message}",
                )

        except ImportError:
            return self._equal_weight_fallback(
                valid_symbols,
                msg="scipy not available — using equal weight",
            )
        except Exception as e:
            return self._equal_weight_fallback(
                valid_symbols,
                msg=f"Optimization error: {e}",
            )

    # ------------------------------------------------------------------
    # Return matrix construction
    # ------------------------------------------------------------------

    def _build_return_matrix(
        self,
        prices: pl.DataFrame,
        symbols: list[str],
    ) -> tuple[np.ndarray, list[str]]:
        """Build T×N return matrix from price data.

        Returns:
            (returns_array, valid_symbols) where array has shape (T, N).
        """
        px = prices.filter(pl.col("symbol").is_in(symbols))
        if px.is_empty():
            return np.array([]), []

        px = px.sort(["symbol", "trade_date"])
        px = px.with_columns(
            (pl.col("close") / pl.col("close").shift(1).over("symbol") - 1).alias(
                "daily_return"
            )
        )
        px = px.drop_nulls(subset=["daily_return"])
        px = px.group_by("symbol").tail(self._lookback)

        # Pivot: dates × symbols
        try:
            wide = px.pivot(
                values="daily_return",
                index="trade_date",
                on="symbol",
            )
        except Exception:
            return np.array([]), []

        # Keep only columns with sufficient data
        return_cols = [c for c in wide.columns if c != "trade_date"]
        valid_cols = [
            c for c in return_cols
            if wide[c].drop_nulls().len() >= MIN_OBSERVATIONS
        ]

        if len(valid_cols) < 2:
            return np.array([]), valid_cols

        # Drop rows with any null (align across symbols)
        wide = wide.select(["trade_date"] + valid_cols).drop_nulls()
        if wide.height < MIN_OBSERVATIONS:
            return np.array([]), valid_cols

        returns = wide.select(valid_cols).to_numpy()
        return np.array(returns, dtype=np.float64), valid_cols

    # ------------------------------------------------------------------
    # Covariance estimation
    # ------------------------------------------------------------------

    def _ledoit_wolf_shrinkage(self, returns: np.ndarray) -> np.ndarray:
        """Ledoit-Wolf shrinkage covariance estimator.

        Shrinks the sample covariance toward a structured target (constant
        correlation), reducing estimation error for small samples.
        """
        n_samples, n_features = returns.shape

        if n_samples < n_features:
            # Not enough samples — use sample covariance
            return np.cov(returns, rowvar=False)

        # Sample covariance
        S = np.cov(returns, rowvar=False)

        # Shrinkage target: constant correlation
        # Compute mean correlation
        stds = np.sqrt(np.diag(S))
        with np.errstate(divide="ignore", invalid="ignore"):
            corr = S / np.outer(stds, stds)
        corr = np.nan_to_num(corr, nan=0.0)

        # Target: constant correlation matrix
        triu_idx = np.triu_indices(n_features, k=1)
        mean_corr = np.mean(corr[triu_idx])

        target = np.outer(stds, stds) * mean_corr
        np.fill_diagonal(target, np.diag(S))

        # Shrinkage intensity (Ledoit-Wolf analytical formula)
        # Simplified: use sample-size-based shrinkage
        shrinkage = min(1.0, n_features / (n_samples * 2))

        return (1.0 - shrinkage) * S + shrinkage * target

    # ------------------------------------------------------------------
    # Fallback
    # ------------------------------------------------------------------

    def _equal_weight_fallback(
        self,
        symbols: list[str],
        msg: str = "",
    ) -> OptimizationResult:
        """Equal weight fallback when optimization fails."""
        n = len(symbols)
        wt = (1.0 - self._cash_buffer) / n if n > 0 else 0.0
        weights = dict.fromkeys(symbols, wt)

        return OptimizationResult(
            weights=weights,
            expected_return=0.0,
            expected_volatility=0.0,
            sharpe_ratio=0.0,
            converged=False,
            message=msg,
            fallback_used=True,
            diagnostics={"method": "equal_weight_fallback"},
        )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def max_weight(self) -> float:
        return self._max_weight

    @property
    def cash_buffer(self) -> float:
        return self._cash_buffer
