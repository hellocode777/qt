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
    """Market regime classifications.

    Aligned with docs/11_12.md design:
      BULL_TREND — strong uptrend, normal Alpha conditions
      HIGH_VOLATILITY — elevated uncertainty, reduce exposure
      LIQUIDITY_CRUNCH — extreme illiquidity, freeze new positions
      STYLE_REVERSAL — rapid sector/style rotation, pause ranking
    """

    TREND_UP = "TREND_UP"  # Strong uptrend (BULL_TREND)
    TREND_DOWN = "TREND_DOWN"  # Strong downtrend
    RANGING = "RANGING"  # Sideways / mean-reverting
    HIGH_VOL = "HIGH_VOL"  # Elevated volatility (HIGH_VOLATILITY)
    LOW_VOL = "LOW_VOL"  # Subdued, quiet market
    LIQUIDITY_CRUNCH = "LIQUIDITY_CRUNCH"  # Extreme illiquidity / limit-down cascade
    STYLE_REVERSAL = "STYLE_REVERSAL"  # Rapid sector/style rotation
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
        limit_up_down_ratio: Limit-up count / (limit-up + limit-down), 0-1.
        sector_rotation_speed: Cross-sectional std of sector returns (annualized).
        n_limit_down: Whole-market limit-down count (latest day), A-share panic gauge.
        details: Dict of raw indicator values.
        summary: Human-readable summary.
    """

    regime: Regime = Regime.UNKNOWN
    confidence: float = 0.0
    trend_strength: float = 0.0  # ADX
    trend_direction: int = 0  # +1, -1, 0
    volatility_percentile: float = 50.0
    annualized_vol: float = 0.0
    limit_up_down_ratio: float = 0.5  # 0.5 = balanced
    sector_rotation_speed: float = 0.0
    n_limit_down: int = 0  # whole-market limit-down count (latest day)
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

    @property
    def is_crisis(self) -> bool:
        """True if market is in crisis mode (liquidity crunch or style reversal)."""
        return self.regime in (Regime.LIQUIDITY_CRUNCH, Regime.STYLE_REVERSAL)


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

    # A-share panic threshold: number of limit-down stocks (whole market,
    # board-aware) that flags LIQUIDITY_CRUNCH. Calibrated on daily_price
    # history: normal days median 5-8 limit-downs; 2026-07 panic days had
    # 183/204/226; 2026-08-19 had 143. 100 gives wide margin both sides.
    PANIC_LIMIT_DOWN_COUNT: int = 100

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
    # Panel → single series
    # ------------------------------------------------------------------

    @staticmethod
    def market_proxy(prices: pl.DataFrame) -> pl.DataFrame:
        """把**横截面面板**压成**单条市场序列**（每个交易日均值 close，按日期升序）。

        与 ``daily_pipeline._build_index_df()`` 是同一套构造：市场状态是"整个市场"
        的属性，必须落在一条按日期排序的序列上。

        Args:
            prices: 面板数据，含 ``trade_date``/``date`` 与 ``close``（可选 ``high``/``low``）。

        Returns:
            单行/日 的 ``[date, close(, high, low)]``；列不全时返回空 DataFrame。
        """
        import polars as pl

        date_col = "trade_date" if "trade_date" in prices.columns else "date"
        if date_col not in prices.columns or "close" not in prices.columns:
            return pl.DataFrame()

        aggs = [pl.col("close").mean().alias("close")]
        for optional in ("high", "low"):
            if optional in prices.columns:
                aggs.append(pl.col(optional).mean().alias(optional))

        return prices.group_by(date_col).agg(aggs).sort(date_col).rename({date_col: "date"})

    def classify_panel(self, prices: pl.DataFrame, **kwargs: Any) -> RegimeResult:
        """从横截面面板判别市场状态（先压成市场序列，再交给 :meth:`classify`）。

        为什么需要它：:meth:`classify` 把入参当成**一条**时间序列（相邻行做差分）。
        直接喂多股票面板时，相邻两行的"收益"是**两只不同股票**的差，算出来的
        波动率纯属噪声 —— 2026-09-25 实测 ``qp monitor regime`` 输出
        "年化波动率 1849.8%"。凡是面板输入必须走本方法。

        Args:
            prices: 横截面面板（``trade_date`` + ``close``）。
            **kwargs: 透传给 :meth:`classify`（如 ``limit_up_down_ratio``）。

        Returns:
            RegimeResult；面板为空或列不全时返回 UNKNOWN。
        """
        series = self.market_proxy(prices)
        if series.is_empty():
            return RegimeResult(
                regime=Regime.UNKNOWN,
                confidence=0.0,
                summary="empty or malformed price panel (need trade_date + close)",
            )
        return self.classify(series, **kwargs)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def classify(
        self,
        prices: pl.DataFrame,
        limit_up_down_ratio: float | None = None,
        sector_rotation_speed: float | None = None,
        n_limit_down: int | None = None,
    ) -> RegimeResult:
        """Classify current market regime.

        Args:
            prices: Daily price data with [trade_date, close].
                Optionally [open, high, low] for ATR/ADX.
            limit_up_down_ratio: Pre-computed limit-up ratio (0-1).
                0 = all limit-down, 0.5 = balanced, 1 = all limit-up.
                Values < 0.2 or > 0.8 indicate extreme imbalance.
            sector_rotation_speed: Pre-computed sector rotation speed
                (annualized cross-sectional std of sector returns).
                Values > 0.50 suggest rapid style rotation.
            n_limit_down: Pre-computed number of limit-down stocks on the
                latest trading day (whole market, board-aware thresholds).
                Values >= PANIC_LIMIT_DOWN_COUNT indicate mass limit-down
                (liquidity crunch) — A-share specific: normal days have
                <10 limit-downs; 2026-07 panic days had 180-226.

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

        # 3. Compute liquidity / style indicators
        lud_ratio = limit_up_down_ratio if limit_up_down_ratio is not None else 0.5
        sector_rot = sector_rotation_speed if sector_rotation_speed is not None else 0.0
        n_ld = n_limit_down if n_limit_down is not None else 0

        # 4. Classify
        regime, confidence = self._classify(
            adx,
            trend_dir,
            ann_vol,
            vol_percentile,
            lud_ratio,
            sector_rot,
            n_ld,
        )

        details = {
            "adx": float(adx),
            "short_ma": float(closes[-self._short_ma :].mean())
            if len(closes) >= self._short_ma
            else 0.0,
            "long_ma": float(closes[-self._long_ma :].mean())
            if len(closes) >= self._long_ma
            else 0.0,
            "annualized_vol": ann_vol,
            "vol_percentile": vol_percentile,
            "close": float(closes[-1]),
            "limit_up_down_ratio": lud_ratio,
            "sector_rotation_speed": sector_rot,
            "n_limit_down": float(n_ld),
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
            f"涨跌停比={lud_ratio:.2f} | "
            f"跌停={n_ld}家 | "
            f"行业轮动={sector_rot:.2f} | "
            f"置信度={confidence:.0%}"
        )

        return RegimeResult(
            regime=regime,
            confidence=confidence,
            trend_strength=trend_strength,
            trend_direction=trend_dir,
            volatility_percentile=vol_percentile,
            annualized_vol=ann_vol,
            limit_up_down_ratio=lud_ratio,
            sector_rotation_speed=sector_rot,
            n_limit_down=n_ld,
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

        short_ma = float(closes[-self._short_ma :].mean())
        long_ma = float(closes[-self._long_ma :].mean())

        if short_ma > long_ma * 1.02:
            return 1  # Uptrend
        if short_ma < long_ma * 0.98:
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
        limit_up_down_ratio: float = 0.5,
        sector_rotation_speed: float = 0.0,
        n_limit_down: int = 0,
    ) -> tuple[Regime, float]:
        """Classify regime from indicators.

        Decision logic (priority order per docs/11_12.md + 2026-09 A-share
        calibration):
          1. LIQUIDITY_CRUNCH: n_limit_down >= PANIC_LIMIT_DOWN_COUNT (mass
             limit-down, A-share specific — primary panic gauge), OR
             limit_up_down_ratio < 0.15 (mass limit-down relative ratio)
             NOTE: limit_up_down_ratio > 0.85 (frenzy) branch removed from
             auto-trigger — A-share normal days sit at 0.85+ (median 0.88),
             so it fired on 57% of days and carried no signal.
          2. STYLE_REVERSAL: sector_rotation_speed > 0.50 (rapid rotation)
          3. HIGH_VOL: vol_percentile >= 80
          4. LOW_VOL: vol_percentile <= 20
          5. TREND_UP/DOWN: ADX >= 25 and trend_dir != 0
          6. Otherwise → RANGING

        Args:
            adx: ADX value (0-100).
            trend_dir: +1, -1, 0.
            ann_vol: Annualized volatility.
            vol_percentile: 0-100 percentile.
            limit_up_down_ratio: 0-1, extreme values = liquidity stress.
            sector_rotation_speed: Annualized std of sector returns.
            n_limit_down: Whole-market limit-down count.

        Returns:
            (Regime, confidence 0-1).
        """
        # Priority 1: Liquidity crunch — mass limit-down cascade
        if n_limit_down >= self.PANIC_LIMIT_DOWN_COUNT:
            conf = min(0.5 + n_limit_down / 500.0, 0.95)
            return Regime.LIQUIDITY_CRUNCH, max(conf, 0.75)
        if limit_up_down_ratio < 0.15:
            conf = min(1.0 - limit_up_down_ratio / 0.15, 0.95)
            return Regime.LIQUIDITY_CRUNCH, max(conf, 0.7)

        # Priority 2: Style reversal — rapid sector rotation
        if sector_rotation_speed > 0.50:
            conf = min(sector_rotation_speed / 1.0, 0.90)
            return Regime.STYLE_REVERSAL, max(conf, 0.5)

        # Priority 3-6: Standard classification
        if vol_percentile >= self._vol_high_pct:
            return Regime.HIGH_VOL, min(vol_percentile / 100, 0.95)

        if vol_percentile <= self._vol_low_pct:
            return Regime.LOW_VOL, max(1.0 - vol_percentile / 100, 0.5)

        if adx >= self._adx_threshold:
            if trend_dir > 0:
                conf = min(adx / 50, 0.9)
                return Regime.TREND_UP, conf
            if trend_dir < 0:
                conf = min(adx / 50, 0.9)
                return Regime.TREND_DOWN, conf

        # Ranging — confidence is inverse of ADX
        conf = max(1.0 - adx / 50, 0.3)
        return Regime.RANGING, conf

    # ------------------------------------------------------------------
    # Static helpers for LIQUIDITY_CRUNCH / STYLE_REVERSAL inputs
    # ------------------------------------------------------------------

    @staticmethod
    def compute_limit_up_down_ratio(
        daily_returns: pl.DataFrame,
        limit_up_pct: float = 0.098,
        limit_down_pct: float = -0.098,
    ) -> float:
        """Compute limit-up/down ratio from cross-sectional daily returns.

        Ratio = n_limit_up / (n_limit_up + n_limit_down), range 0-1.
        0 = all limit-down (panic), 0.5 = balanced, 1 = all limit-up (frenzy).
        Values < 0.15 or > 0.85 → potential LIQUIDITY_CRUNCH.

        For A-shares, ±10% (±9.8% for most stocks, ±19.6% for STAR/ChiNext).

        Args:
            daily_returns: DataFrame with a 'return' or 'pct_change' column,
                one row per stock for a single trading day.
            limit_up_pct: Upper bound for limit-up (e.g., 0.098 = 9.8%).
            limit_down_pct: Lower bound for limit-down (e.g., -0.098 = -9.8%).

        Returns:
            Ratio 0-1, or 0.5 if insufficient data.
        """
        if daily_returns.is_empty():
            return 0.5

        ret_col = "return" if "return" in daily_returns.columns else "pct_change"
        if ret_col not in daily_returns.columns:
            return 0.5

        returns = daily_returns[ret_col].drop_nulls()
        if len(returns) < 5:
            return 0.5

        # Convert to Python list for reliable summation
        ret_list = returns.to_list()
        n_up = sum(1 for r in ret_list if r >= limit_up_pct)
        n_down = sum(1 for r in ret_list if r <= limit_down_pct)
        total = n_up + n_down

        if total == 0:
            return 0.5

        return float(n_up / total)

    @staticmethod
    def compute_limit_down_count(
        daily_returns: pl.DataFrame,
        symbol_col: str = "symbol",
        ret_col: str = "return",
    ) -> int:
        """Count whole-market limit-down stocks for one trading day.

        Board-aware thresholds: main board ±10% (>= 9.8% move), ChiNext
        (300/301) and STAR (688) ±20% (>= 19.5% move). This mirrors actual
        A-share price limits — a flat 9.8% cut-off mislabels 20cm boards.

        Args:
            daily_returns: DataFrame with one row per stock for a single
                trading day, containing a symbol column and a return column.
            symbol_col: Symbol column name.
            ret_col: Return column name (fraction, e.g. -0.098 = -9.8%).

        Returns:
            Number of limit-down stocks, or 0 if insufficient data.
        """
        if daily_returns.is_empty():
            return 0
        if ret_col not in daily_returns.columns or symbol_col not in daily_returns.columns:
            return 0

        import polars as pl  # local import: module keeps polars optional

        returns = daily_returns.select(
            pl.col(symbol_col).cast(pl.Utf8).alias("_sym"),
            pl.col(ret_col).cast(pl.Float64).alias("_ret"),
        ).drop_nulls()
        if returns.height < 2:
            return 0

        # Board-aware limit-down threshold: 20cm boards use ±19.5%,
        # main board (600/601/603/605/000/001/002/003) uses ±9.8%.
        returns = returns.with_columns(
            pl.when(
                pl.col("_sym").str.starts_with("300")
                | pl.col("_sym").str.starts_with("301")
                | pl.col("_sym").str.starts_with("688")
            )
            .then(-0.195)
            .otherwise(-0.098)
            .alias("_limit_down_pct")
        )
        return int(returns.filter(pl.col("_ret") <= pl.col("_limit_down_pct")).height)

    @staticmethod
    def _cross_section_latest_returns(
        price_data: dict[str, pl.DataFrame],
    ) -> pl.DataFrame:
        """Build latest-day cross-sectional returns from {symbol: DataFrame}.

        Each symbol's daily return is its last close vs previous close,
        aligned to the market's latest COMMON trading day (symbols whose
        series ends years earlier — delisted / long-suspended — are
        excluded so stale rows cannot fabricate -60% limit-down moves).

        Args:
            price_data: {code: DataFrame with 'close' column (and optional
                'trade_date'/'date'), rows sorted ascending by date}.

        Returns:
            pl.DataFrame[symbol, return] — one row per symbol aligned to
            the latest common trading day, or empty.
        """
        date_col = (
            "trade_date"
            if price_data and "trade_date" in next(iter(price_data.values())).columns
            else "date"
        )
        import polars as pl  # local import: module keeps polars optional

        # 1. Collect each symbol's latest date + daily return
        day_rets: dict[str, tuple[object, float]] = {}
        for code, pdf in price_data.items():
            if pdf is None or pdf.is_empty() or "close" not in pdf.columns:
                continue
            if date_col not in pdf.columns or pdf.height < 2:
                continue
            try:
                pdf_sorted = pdf.sort(date_col).drop_nulls("close")
                if pdf_sorted.height < 2:
                    continue
                last_close = float(pdf_sorted["close"][-1])
                prev_close = float(pdf_sorted["close"][-2])
                if prev_close <= 0 or last_close <= 0:
                    continue
                day_rets[str(code)] = (
                    pdf_sorted[date_col][-1],
                    last_close / prev_close - 1.0,
                )
            except Exception:
                continue

        if len(day_rets) < 10:
            return pl.DataFrame(schema={"symbol": pl.Utf8, "return": pl.Float64})

        # 2. Latest common trading day = most common latest date
        from collections import Counter

        date_counts = Counter(d for d, _ in day_rets.values())
        if not date_counts:
            return pl.DataFrame(schema={"symbol": pl.Utf8, "return": pl.Float64})
        latest_day = date_counts.most_common(1)[0][0]

        # 3. Keep only symbols aligned to latest_day
        rows = [
            {"symbol": code, "return": ret}
            for code, (day, ret) in day_rets.items()
            if day == latest_day
        ]
        if not rows:
            return pl.DataFrame(schema={"symbol": pl.Utf8, "return": pl.Float64})
        return pl.DataFrame(rows)

    @staticmethod
    def compute_sector_rotation_speed(
        sector_returns: pl.DataFrame,
        window: int = 20,
        trading_days: int = 252,
    ) -> float:
        """Compute sector rotation speed from sector-level daily returns.

        Measures cross-sectional dispersion of sector returns over a rolling
        window. High values = rapid style/sector rotation (STYLE_REVERSAL).

        Formula: std(cross-sectional sector returns) over window, annualized.
        Threshold: > 0.50 suggests rapid rotation.

        Args:
            sector_returns: DataFrame with [trade_date, sector, return] columns.
            window: Rolling window for computing dispersion.
            trading_days: Days per year for annualization.

        Returns:
            Annualized sector rotation speed.
        """
        if sector_returns.is_empty():
            return 0.0

        required_cols = {"trade_date", "return"}
        if not required_cols.issubset(sector_returns.columns):
            return 0.0

        import polars as pl

        # Compute cross-sectional std per day
        daily_dispersion = (
            sector_returns.group_by("trade_date")
            .agg(pl.col("return").std().alias("cs_std"))
            .sort("trade_date")
        )

        if daily_dispersion.is_empty():
            return 0.0

        cs_std = daily_dispersion["cs_std"].tail(window).drop_nulls()
        if len(cs_std) < 5:
            return 0.0

        mean_cs_std = float(cs_std.mean())  # type: ignore[arg-type]
        return mean_cs_std * (trading_days**0.5)

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
