"""Market Regime Detection — multi-dimensional market state classification.

Detects the current market regime across 4 dimensions:
  Trend:     MA50 vs MA200 position + short-term momentum
  Volatility: Recent vol vs historical vol percentile
  Breadth:    Percentage of stocks above their MA50
  Volume:    Volume ratio vs 20-day average

Outputs 6 regimes with adaptive position sizing:
  bull / sideways_up / sideways_down / bear / neutral / crisis

Complements ``market_filter.py``: market_filter decides *whether* to trade,
market_regime decides *how much* to trade and *which strategy* to use.

Usage:
    from qp.strategy.market_regime import MarketRegimeDetector

    detector = MarketRegimeDetector()
    regime = detector.detect(index_df, price_data)
    # → RegimeResult(regime="bull", suggested_position_pct=1.0, ...)

    # For backtesting:
    history = detector.detect_history(index_df, price_data)
    # → pl.DataFrame with per-date regime classifications
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import polars as pl

# ------------------------------------------------------------------
# Constants
# ------------------------------------------------------------------

# Regime → suggested position as fraction of total capital
REGIME_POSITION_MAP: dict[str, float] = {
    "bull": 1.0,
    "sideways_up": 0.70,
    "sideways_down": 0.30,
    "neutral": 0.50,
    "bear": 0.10,
    "crisis": 0.0,
}

# Regime → preferred strategy type
REGIME_STRATEGY_MAP: dict[str, str] = {
    "bull": "momentum",
    "sideways_up": "momentum",
    "sideways_down": "defensive",
    "neutral": "balanced",
    "bear": "defensive",
    "crisis": "cash",
}

# Default position counts per regime (for multi-factor strategy)
DEFAULT_REGIME_POSITIONS: dict[str, int] = {
    "bull": 10,
    "sideways_up": 8,
    "sideways_down": 5,
    "neutral": 7,
    "bear": 3,
    "crisis": 0,
}

# Default rebalance frequency per regime (trading days)
DEFAULT_REGIME_FREQUENCIES: dict[str, int] = {
    "bull": 20,
    "sideways_up": 20,
    "sideways_down": 30,
    "neutral": 25,
    "bear": 45,
    "crisis": 0,
}

# Blocked regimes for buy signals (others allow buys)
BLOCKED_BUY_REGIMES: frozenset[str] = frozenset({"bear", "crisis"})


# ------------------------------------------------------------------
# Data models
# ------------------------------------------------------------------


@dataclass
class RegimeResult:
    """Single-date market regime detection result."""

    regime: str  # bull / bear / sideways_up / sideways_down / neutral / crisis
    confidence: float = 0.0  # 0~1
    trend_score: float = 0.0  # -1~1
    volatility_score: float = 0.0  # 0~1 (higher = more volatile)
    breadth_score: float = 0.0  # 0~1 (higher = more stocks above MA)
    volume_score: float = 0.5  # 0~1
    reason: str = ""

    @property
    def suggested_position_pct(self) -> float:
        """Suggested position as fraction of total capital."""
        return REGIME_POSITION_MAP.get(self.regime, 0.5)

    @property
    def preferred_strategy(self) -> str:
        """Suggested strategy type for this regime."""
        return REGIME_STRATEGY_MAP.get(self.regime, "balanced")

    @property
    def suggested_position_count(self) -> int:
        """Suggested number of stocks to hold."""
        return DEFAULT_REGIME_POSITIONS.get(self.regime, 7)

    @property
    def suggested_rebalance_freq(self) -> int:
        """Suggested rebalance frequency in trading days."""
        return DEFAULT_REGIME_FREQUENCIES.get(self.regime, 20)

    @property
    def allow_buy(self) -> bool:
        """Whether buying is allowed in this regime."""
        return self.regime not in BLOCKED_BUY_REGIMES


# ------------------------------------------------------------------
# Detector
# ------------------------------------------------------------------


class MarketRegimeDetector:
    """Multi-dimensional market regime classifier.

    Detects regime from 4 dimensions:
      1. Trend — MA alignment + price position + short momentum
      2. Volatility — recent vs historical vol percentile
      3. Breadth — percentage of stocks above their MA50
      4. Volume — volume ratio vs recent average

    Usage:
        detector = MarketRegimeDetector(trend_fast=50, trend_slow=200)
        regime = detector.detect(index_df, price_data)
        print(regime.regime, f"仓位: {regime.suggested_position_pct:.0%}")
    """

    def __init__(
        self,
        trend_fast: int = 50,
        trend_slow: int = 200,
        vol_period: int = 20,
        vol_lookback: int = 252,
        breadth_ma: int = 50,
        min_history: int = 200,
    ) -> None:
        self.trend_fast = trend_fast
        self.trend_slow = trend_slow
        self.vol_period = vol_period
        self.vol_lookback = vol_lookback
        self.breadth_ma = breadth_ma
        self.min_history = min_history

    # ------------------------------------------------------------------
    # Single-date detection
    # ------------------------------------------------------------------

    def detect(
        self,
        index_df: pl.DataFrame,
        price_data: dict[str, pl.DataFrame] | None = None,
    ) -> RegimeResult:
        """Detect current market regime.

        Args:
            index_df: Index daily data [date, close] (+ optional [volume]).
            price_data: {symbol: pl.DataFrame(date, close)} for breadth.
                        None → breadth_score defaults to 0.5.

        Returns:
            RegimeResult for the most recent date.
        """
        if index_df is None or index_df.is_empty():
            return RegimeResult(
                regime="sideways_up",
                confidence=0.3,
                reason="无指数数据，默认偏多震荡",
            )

        close = index_df["close"].to_numpy().astype(np.float64)
        if len(close) < self.min_history:
            return RegimeResult(
                regime="neutral",
                confidence=0.3,
                reason=f"数据不足 (需要 {self.min_history} 条, 当前 {len(close)} 条)",
            )

        # ── 1. Trend dimension ──
        trend_score, trend_reason = self._compute_trend(close)

        # ── 2. Volatility dimension ──
        vol_score, vol_reason = self._compute_volatility(close)

        # ── 3. Breadth dimension ──
        breadth_score, breadth_reason = self._compute_breadth(
            index_df,
            price_data,
        )

        # ── 4. Volume dimension ──
        volume_score, volume_reason = self._compute_volume(index_df)

        # ── Classify regime ──
        regime, confidence = self._classify(
            trend_score,
            vol_score,
            breadth_score,
            volume_score,
        )

        reasons = [trend_reason, vol_reason, breadth_reason, volume_reason]
        non_empty = [r for r in reasons if r]

        return RegimeResult(
            regime=regime,
            confidence=round(confidence, 2),
            trend_score=round(float(trend_score), 3),
            volatility_score=round(float(vol_score), 3),
            breadth_score=round(float(breadth_score), 3),
            volume_score=round(float(volume_score), 3),
            reason=" | ".join(non_empty),
        )

    # ------------------------------------------------------------------
    # Historical detection (for backtesting)
    # ------------------------------------------------------------------

    def detect_history(
        self,
        index_df: pl.DataFrame,
        price_data: dict[str, pl.DataFrame] | None = None,
    ) -> pl.DataFrame:
        """Detect regime for every trading day (for backtesting).

        Args:
            index_df: Index daily data.
            price_data: {symbol: pl.DataFrame(date, close)}.

        Returns:
            Polars DataFrame [date, regime, trend_score, volatility_score,
            breadth_score, volume_score, suggested_position, preferred_strategy].
        """
        if index_df is None or index_df.is_empty():
            return pl.DataFrame()

        # Normalize column name (accept both "date" and "trade_date" — Gold
        # dataset uses trade_date, legacy strategy callers passed date)
        if "date" in index_df.columns and "trade_date" not in index_df.columns:
            index_df = index_df.rename({"date": "trade_date"})
        df = index_df.sort("trade_date")
        dates = df["trade_date"].cast(pl.Utf8).to_list()

        results: list[dict[str, Any]] = []

        for i in range(self.min_history, len(dates) + 1):
            sub_idx = df.slice(0, i)

            # Filter price_data to dates up to current
            sub_prices: dict[str, pl.DataFrame] | None = None
            if price_data is not None:
                sub_prices = {}
                for code, pdf in price_data.items():
                    if pdf is None or pdf.is_empty():
                        continue
                    sub = pdf.filter(
                        pl.col("trade_date")
                        .cast(pl.Utf8)
                        .is_in(
                            set(dates[:i]),
                        )
                    )
                    if not sub.is_empty() and sub.height >= self.breadth_ma:
                        sub_prices[code] = sub

            regime = self.detect(
                sub_idx,
                sub_prices if sub_prices else None,
            )
            results.append(
                {
                    "date": dates[i - 1],
                    "regime": regime.regime,
                    "trend_score": regime.trend_score,
                    "volatility_score": regime.volatility_score,
                    "breadth_score": regime.breadth_score,
                    "volume_score": regime.volume_score,
                    "suggested_position": regime.suggested_position_pct,
                    "suggested_positions": regime.suggested_position_count,
                    "preferred_strategy": regime.preferred_strategy,
                }
            )

        return pl.DataFrame(results)

    # ------------------------------------------------------------------
    # Dimension computations
    # ------------------------------------------------------------------

    def _compute_trend(self, close: np.ndarray) -> tuple[float, str]:
        """Trend score from MA alignment + price position."""
        ma_fast = _rolling_mean(close, self.trend_fast)
        ma_slow = _rolling_mean(close, self.trend_slow)

        current_price = close[-1]
        current_fast = ma_fast[-1]
        current_slow = ma_slow[-1]

        # Price position relative to MA200 (-1 to +1)
        if current_slow > 0:
            price_score = np.clip(
                (current_price - current_slow) / current_slow * 5,
                -1,
                1,
            )
        else:
            price_score = 0.0

        # MA alignment: fast > slow = +1, fast < slow = -1
        ma_alignment = 1.0 if current_fast > current_slow else -1.0

        # Short momentum (20-day)
        short_mom = close[-1] / close[-20] - 1 if len(close) >= 20 else 0.0

        combined = (
            float(price_score) * 0.4 + ma_alignment * 0.3 + np.clip(short_mom * 10, -1, 1) * 0.3
        )

        direction = "多头" if combined > 0.2 else "空头" if combined < -0.2 else "中性"
        return combined, f"趋势={direction}({combined:.2f})"

    def _compute_volatility(self, close: np.ndarray) -> tuple[float, str]:
        """Recent vol vs historical vol percentile."""
        if len(close) < self.vol_lookback:
            return 0.5, ""

        log_ret = np.diff(np.log(close))
        recent_vol = np.std(log_ret[-self.vol_period :]) * np.sqrt(252)
        hist_vol = np.std(log_ret[-self.vol_lookback :]) * np.sqrt(252)

        if hist_vol > 0:
            ratio = recent_vol / hist_vol
            vol_score = np.clip(float(ratio), 0.0, 2.0) / 2.0
        else:
            vol_score = 0.5

        level = "高波动" if vol_score > 0.7 else "平稳" if vol_score < 0.3 else "正常"
        return vol_score, f"波动={level}({vol_score:.2f})"

    def _compute_breadth(
        self,
        index_df: pl.DataFrame,
        price_data: dict[str, pl.DataFrame] | None,
    ) -> tuple[float, str]:
        """Percentage of stocks above their MA50."""
        if price_data is None or len(price_data) < 10:
            return 0.5, f"宽度=无数据(默认{0.5:.1f})"

        above_count = 0
        total = 0

        for _code, pdf in price_data.items():
            if pdf is None or pdf.is_empty():
                continue
            if pdf.height < self.breadth_ma:
                continue

            try:
                close_vals = pdf["close"].to_numpy()
                if len(close_vals) < self.breadth_ma:
                    continue

                ma_val = np.mean(close_vals[-self.breadth_ma :])
                current = close_vals[-1]
                total += 1
                if current > ma_val:
                    above_count += 1
            except (IndexError, KeyError, TypeError):
                continue

        breadth = above_count / total if total > 0 else 0.5
        level = "普涨" if breadth > 0.6 else "分化" if breadth < 0.4 else "中性"
        return breadth, f"宽度={level}({breadth:.2f}, {total}只)"

    @staticmethod
    def _compute_volume(index_df: pl.DataFrame) -> tuple[float, str]:
        """Volume ratio vs 20-day average."""
        if "volume" not in index_df.columns or index_df.height < 21:
            return 0.5, ""

        vol = index_df["volume"].to_numpy()[-21:]
        recent_avg = np.mean(vol[-5:])
        hist_avg = np.mean(vol[:-1])

        if hist_avg > 0:
            ratio = recent_avg / hist_avg
            vol_score = np.clip(float(ratio), 0.3, 2.0) / 2.0
        else:
            vol_score = 0.5

        level = "放量" if vol_score > 0.7 else "缩量" if vol_score < 0.35 else "正常"
        return vol_score, f"量={level}({vol_score:.2f})"

    # ------------------------------------------------------------------
    # Regime classification
    # ------------------------------------------------------------------

    @staticmethod
    def _classify(
        trend: float,
        volatility: float,
        breadth: float,
        volume: float,
    ) -> tuple[str, float]:
        """Classify regime from 4 dimension scores.

        Decision logic:
          - trend > 0.3 + vol not extreme → bull or sideways_up
          - trend < -0.3 + vol high → crisis or bear
          - otherwise → sideways or neutral
        """
        if trend > 0.3:
            if volatility > 0.7 and volume > 0.7:
                regime = "bull"
                confidence = min(1.0, (trend + breadth) / 2)
            else:
                regime = "sideways_up"
                confidence = 0.5 + 0.2 * trend

        elif trend < -0.3:
            if volatility > 0.7 and volume > 0.7:
                regime = "crisis"
                confidence = min(1.0, abs(trend))
            elif volatility > 0.5 or breadth < 0.4:
                regime = "bear"
                confidence = min(1.0, abs(trend) * 0.8)
            else:
                regime = "sideways_down"
                confidence = 0.5

        else:
            if breadth > 0.6:
                regime = "sideways_up"
                confidence = 0.4
            elif breadth < 0.4 and volatility > 0.5:
                regime = "sideways_down"
                confidence = 0.4
            else:
                regime = "neutral"
                confidence = 0.3

        return regime, confidence


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _rolling_mean(data: np.ndarray, window: int) -> np.ndarray:
    """Compute rolling mean (returns same-length array, NaN for early values)."""
    result = np.full_like(data, np.nan, dtype=np.float64)
    if len(data) < window:
        return result
    cumsum = np.cumsum(np.insert(data, 0, 0))
    result[window - 1 :] = (cumsum[window:] - cumsum[:-window]) / window
    return result


def regime_to_position_pct(regime: str) -> float:
    """Get suggested position percentage for a regime."""
    return REGIME_POSITION_MAP.get(regime, 0.5)


def regime_allows_buy(regime: str) -> bool:
    """Check if buying is allowed in this regime."""
    return regime not in BLOCKED_BUY_REGIMES
