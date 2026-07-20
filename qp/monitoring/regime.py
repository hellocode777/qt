"""Market Regime Engine — classifies market state for strategy conditioning.

Detects the current market regime based on price action:
  - Trend: strong directional movement (up or down)
  - Ranging: sideways, mean-reverting behavior
  - High Volatility: elevated uncertainty
  - Low Volatility: subdued movement

Uses common indicators:
  - ADX (Average Directional Index) for trend strength
  - MA crossover (50 vs 200) for trend direction
  - ATR (Average True Range) for volatility regime
  - Returns-based realized volatility

Usage:
    engine = MarketRegimeEngine()
    regime = engine.classify(prices_df)
    # → RegimeResult(regime="TREND_UP", confidence=0.82, ...)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    import polars as pl


class Regime(StrEnum):
    """Market regime classifications."""
    TREND_UP = "TREND_UP"  # Strong uptrend
    TREND_DOWN = "TREND_DOWN"  # Strong downtrend
    RANGING = "RANGING"  # Sideways / mean-reverting
    HIGH_VOL = "HIGH_VOL"  # Elevated volatility (any direction)
    LOW_VOL = "LOW_VOL"  # Subdued, quiet market
    UNKNOWN = "UNKNOWN"  # Insufficient data


@dataclass
class RegimeResult:
    """Market regime classification result.

    Attributes:
        regime: Classified regime.
        confidence: 0-1 confidence score.
        trend_strength: ADX value (0-100).
        trend_direction: +1 uptrend, -1 downtrend, 0 neutral.
        volatility_percentile: Current vol vs historical (0-100).
        annualized_vol: Current annualized volatility.
        details: Dict of raw indicator values.
        summary: Human-readable summary.
    """

    regime: Regime = Regime.UNKNOWN
    confidence: float = 0.0
    trend_strength: float = 0.0  # ADX
    trend_direction: int = 0  # +1, -1, 0
    volatility_percentile: float = 50.0
    annualized_vol: float = 0.0
    details: dict[str, float] = field(default_factory=dict)
    summary: str = ""

    @property
    def is_trending(self) -> bool:
        """True if market is in a trend regime."""
        return self.regime in (Regime.TREND_UP, Regime.TREND_DOWN)

    @property
    def is_high_vol(self) -> bool:
        """True if volatility is elevated."""
        return self.regime == Regime.HIGH_VOL


class MarketRegimeEngine:
    """Classifies market regime from daily price data.

    Requires at least 60 trading days of OHLC data for reliable classification.
    Ideally 200+ days for historical volatility context.

    Usage:
        engine = MarketRegimeEngine()
        result = engine.classify(prices_df)
        if result.is_trending:
            # Use momentum strategies
        elif result.regime == Regime.RANGING:
            # Use mean-reversion strategies
    """

    def __init__(
        self,
        adx_trend_threshold: float = 25.0,
        short_ma_window: int = 50,
        long_ma_window: int = 200,
        vol_high_percentile: int = 80,
        vol_low_percentile: int = 20,
        atr_window: int = 14,
        min_days: int = 60,
        trading_days: int = 252,
    ) -> None:
        self._adx_threshold = adx_trend_threshold
        self._short_ma = short_ma_window
        self._long_ma = long_ma_window
        self._vol_high_pct = vol_high_percentile
        self._vol_low_pct = vol_low_percentile
        self._atr_window = atr_window
        self._min_days = min_days
        self._trading_days = trading_days

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def classify(
        self,
        prices: pl.DataFrame,
    ) -> RegimeResult:
        """Classify current market regime.

        Args:
            prices: Daily price data with [trade_date, close].
                Optionally [open, high, low] for ATR/ADX.

        Returns:
            RegimeResult with classification and indicators.
        """
        if prices.is_empty() or len(prices) < self._min_days:
            return RegimeResult(
                regime=Regime.UNKNOWN,
                confidence=0.0,
                summary=f"Insufficient data: {len(prices)} < {self._min_days} days",
            )

        closes = prices["close"].to_numpy()

        # 1. Compute trend indicators
        adx = self._compute_adx(prices)
        trend_dir = self._trend_direction(closes)
        trend_strength = float(adx)

        # 2. Compute volatility indicators
        returns = self._compute_returns(closes)
        ann_vol = float(returns.std() * (self._trading_days**0.5))

        # Historical vol percentile
        rolling_vol = self._rolling_volatility(returns, window=20)
        if len(rolling_vol) > 0:
            vol_percentile = float(
                (ann_vol - rolling_vol.min())
                / (rolling_vol.max() - rolling_vol.min() + 1e-10)
                * 100
            )
        else:
            vol_percentile = 50.0

        # 3. Classify
        regime, confidence = self._classify(adx, trend_dir, ann_vol, vol_percentile)

        details = {
            "adx": float(adx),
            "short_ma": float(closes[-self._short_ma:].mean()) if len(closes) >= self._short_ma else 0.0,
            "long_ma": float(closes[-self._long_ma:].mean()) if len(closes) >= self._long_ma else 0.0,
            "annualized_vol": ann_vol,
            "vol_percentile": vol_percentile,
            "close": float(closes[-1]),
        }

        # Generate summary
        direction_name = {
            1: "上升趋势 (Uptrend)",
            -1: "下降趋势 (Downtrend)",
            0: "中性 (Neutral)",
        }
        summary = (
            f"市场状态: {regime.value} | "
            f"ADX={adx:.1f} | "
            f"方向={direction_name.get(trend_dir, 'N/A')} | "
            f"年化波动={ann_vol:.1%} | "
            f"置信度={confidence:.0%}"
        )

        return RegimeResult(
            regime=regime,
            confidence=confidence,
            trend_strength=trend_strength,
            trend_direction=trend_dir,
            volatility_percentile=vol_percentile,
            annualized_vol=ann_vol,
            details=details,
            summary=summary,
        )

    def classify_simple(
        self,
        closes: list[float],
    ) -> RegimeResult:
        """Quick regime classification from a close price list.

        Uses simplified indicators (no OHLC needed).

        Args:
            closes: List of close prices, most recent last.

        Returns:
            RegimeResult.
        """
        import polars as pl

        df = pl.DataFrame({"close": closes})
        return self.classify(df)

    # ------------------------------------------------------------------
    # Indicator computations
    # ------------------------------------------------------------------

    def _compute_adx(self, prices: pl.DataFrame) -> float:
        """Compute Average Directional Index (trend strength, 0-100)."""
        import numpy as np

        closes = prices["close"].to_numpy()

        # Need high/low for proper ADX; approximate from close-only
        if "high" in prices.columns and "low" in prices.columns:
            high = prices["high"].to_numpy()
            low = prices["low"].to_numpy()
        else:
            # Approximate: use close ± atr-like range
            daily_range = np.abs(np.diff(closes, prepend=closes[0]))
            avg_range = np.convolve(daily_range, np.ones(14) / 14, mode="valid")
            if len(avg_range) < 1:
                avg_range = np.array([daily_range.mean()])
            atr_val = float(avg_range[-1])
            high = closes + atr_val / 2
            low = closes - atr_val / 2

        n = len(closes)
        if n < self._atr_window + 1:
            return 25.0  # Default: borderline trend

        # True Range
        tr = np.zeros(n)
        for i in range(1, n):
            tr[i] = max(
                high[i] - low[i],
                abs(high[i] - closes[i - 1]),
                abs(low[i] - closes[i - 1]),
            )
        atr = np.convolve(tr, np.ones(self._atr_window) / self._atr_window, mode="valid")

        # Directional Movement
        up_move = np.diff(high)
        down_move = -np.diff(low)

        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)

        # Smooth DM
        smooth_window = self._atr_window
        if len(atr) < 2:
            return 25.0

        atr_smooth = atr[-1]
        plus_di = 100 * np.mean(plus_dm[-smooth_window:]) / atr_smooth if atr_smooth > 0 else 0
        minus_di = 100 * np.mean(minus_dm[-smooth_window:]) / atr_smooth if atr_smooth > 0 else 0

        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10)
        return float(dx)

    def _trend_direction(self, closes: np.ndarray) -> int:
        """Determine trend direction from MA crossover.

        Returns +1 (uptrend), -1 (downtrend), 0 (neutral).
        """
        n = len(closes)

        if n < self._long_ma:
            return 0

        short_ma = float(closes[-self._short_ma:].mean())
        long_ma = float(closes[-self._long_ma:].mean())

        if short_ma > long_ma * 1.02:
            return 1  # Uptrend
        elif short_ma < long_ma * 0.98:
            return -1  # Downtrend
        return 0  # Neutral

    @staticmethod
    def _compute_returns(closes: np.ndarray) -> np.ndarray:
        """Compute daily log returns."""
        import numpy as np

        return np.diff(np.log(np.maximum(closes, 1e-10)))

    def _rolling_volatility(
        self,
        returns: np.ndarray,
        window: int = 20,
    ) -> np.ndarray:
        """Compute rolling annualized volatility."""
        import numpy as np

        if len(returns) < window:
            return np.array([np.std(returns) * np.sqrt(self._trading_days)])

        result = np.zeros(len(returns) - window + 1)
        for i in range(len(result)):
            result[i] = np.std(returns[i : i + window]) * np.sqrt(self._trading_days)
        return result

    def _classify(
        self,
        adx: float,
        trend_dir: int,
        ann_vol: float,
        vol_percentile: float,
    ) -> tuple[Regime, float]:
        """Classify regime from indicators.

        Decision logic:
          1. If vol_percentile >= 80 → HIGH_VOL
          2. If vol_percentile <= 20 → LOW_VOL
          3. If ADX >= 25 and trend_dir != 0 → TREND_UP/DOWN
          4. Otherwise → RANGING

        Args:
            adx: ADX value (0-100).
            trend_dir: +1, -1, 0.
            ann_vol: Annualized volatility.
            vol_percentile: 0-100 percentile.

        Returns:
            (Regime, confidence 0-1).
        """
        if vol_percentile >= self._vol_high_pct:
            return Regime.HIGH_VOL, min(vol_percentile / 100, 0.95)

        if vol_percentile <= self._vol_low_pct:
            return Regime.LOW_VOL, max(1.0 - vol_percentile / 100, 0.5)

        if adx >= self._adx_threshold:
            if trend_dir > 0:
                conf = min(adx / 50, 0.9)
                return Regime.TREND_UP, conf
            elif trend_dir < 0:
                conf = min(adx / 50, 0.9)
                return Regime.TREND_DOWN, conf

        # Ranging — confidence is inverse of ADX
        conf = max(1.0 - adx / 50, 0.3)
        return Regime.RANGING, conf

    # ------------------------------------------------------------------
    # Regime transition detection
    # ------------------------------------------------------------------

    def detect_transition(
        self,
        prices_history: pl.DataFrame,
        lookback: int = 10,
    ) -> dict[str, Any]:
        """Check if a regime transition is occurring.

        Compares current indicators to recent history to flag transitions.

        Args:
            prices_history: Full price history.
            lookback: Days to look back.

        Returns:
            Dict: {transition_detected, to_regime, confidence}.
        """
        if len(prices_history) < lookback + self._min_days:
            return {"transition_detected": False, "to_regime": "", "confidence": 0.0}

        # Current regime
        current = self.classify(prices_history)

        # Regime N days ago
        past_prices = prices_history.slice(0, len(prices_history) - lookback)
        past = self.classify(past_prices)

        transition_detected = current.regime != past.regime
        confidence = abs(current.confidence - past.confidence) if transition_detected else 0.0

        return {
            "transition_detected": transition_detected,
            "from_regime": past.regime.value,
            "to_regime": current.regime.value,
            "confidence": confidence,
        }
