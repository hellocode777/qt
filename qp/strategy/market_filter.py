"""Market Environment Filter — block buy signals in bearish/sideways markets.

Inspired by the reference QuantTrading pipeline. Uses index data to determine
whether the broad market supports going long. In bear/neutral-bearish conditions,
buy signals are suppressed to avoid fighting the tide.

Features:
  - MA-based bull/bear detection (price vs MA20/MA60)
  - Confirmation days (must stay above MA for N consecutive days)
  - Dual-MA golden cross filter (MA20 > MA60)
  - Volume confirmation (no shrinking volume)
  - Regime gating (bear/crisis → block all buys; sideways_down → allow only low-vol picks)

Usage:
    from qp.strategy.market_filter import check_market_environment, filter_signals

    env = check_market_environment(index_df)
    if env["allow_trading"]:
        signals = filter_signals(signals_df, index_df)
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

import polars as pl


class MarketStatus(StrEnum):
    BULL = "bull"
    BEAR = "bear"
    NEUTRAL = "neutral"


# ------------------------------------------------------------------
# Index MA computation
# ------------------------------------------------------------------


def _normalize_index_date_col(index_df: pl.DataFrame) -> pl.DataFrame:
    """Accept both 'date' (legacy strategy convention) and 'trade_date' (data-layer convention).

    ``data/dataset/index_csi300.parquet`` uses ``trade_date`` like all other
    Gold datasets; older strategy callers passed ``date``. Normalize once here
    so downstream logic can rely on ``trade_date``.
    """
    if index_df is None or index_df.is_empty():
        return index_df
    if "date" in index_df.columns and "trade_date" not in index_df.columns:
        return index_df.rename({"date": "trade_date"})
    return index_df


def _compute_ma(close: pl.Series, period: int) -> pl.Series:
    """Simple moving average of close prices."""
    return close.rolling_mean(period)


# ------------------------------------------------------------------
# Market environment check
# ------------------------------------------------------------------


def check_market_environment(
    index_df: pl.DataFrame,
    ma_period: int = 20,
    confirmation_days: int = 1,
    ma_slow: int | None = None,
) -> dict[str, Any]:
    """Check current market environment for trading suitability.

    Args:
        index_df: Index daily data with [date, close] (and optionally [volume]).
        ma_period: Fast MA period (default 20).
        confirmation_days: Must stay above MA for N consecutive days.
        ma_slow: Optional slow MA (e.g. 60) for golden cross filter.

    Returns:
        {
            "status": "bull" | "bear" | "neutral",
            "allow_trading": True | False,
            "reason": str,
            "index_close": float,
            "index_ma": float,
            "index_ma_slow": float | None,
        }
    """
    if index_df is None or index_df.is_empty():
        return {
            "status": MarketStatus.NEUTRAL,
            "allow_trading": True,
            "reason": "无指数数据，默认允许交易",
            "index_close": 0.0,
            "index_ma": 0.0,
            "index_ma_slow": None,
        }

    index_df = _normalize_index_date_col(index_df)
    df = index_df.sort("trade_date")
    close = df["close"]

    df = df.with_columns(
        _compute_ma(close, ma_period).alias("_ma"),
    )

    latest = df.tail(1)
    current_price = float(latest["close"].item())
    current_ma = float(latest["_ma"].item())

    # Basic MA check
    above_ma = close >= df["_ma"]

    # Confirmation days
    if confirmation_days > 1:
        confirmed = pl.Series("confirmed", [False] * df.height)
        for i in range(df.height):
            if i >= confirmation_days - 1:
                confirmed[i] = above_ma.slice(i - confirmation_days + 1, confirmation_days).all()
        above_ma = confirmed

    is_above = bool(above_ma.tail(1).item() or False)

    # Golden cross (MA20 > MA60)
    golden_cross_ok = True
    if ma_slow and ma_slow > ma_period:
        df = df.with_columns(_compute_ma(close, ma_slow).alias("_ma_slow"))
        golden_cross = df["_ma"] >= df["_ma_slow"]
        golden_cross_ok = bool(golden_cross.tail(1).item() or False)
        current_ma_slow = float(df["_ma_slow"].tail(1).item() or 0.0)
    else:
        current_ma_slow = None

    # Determine status
    if current_price > current_ma * 1.03 and golden_cross_ok:
        status = MarketStatus.BULL
        allow = True
        reason = f"大盘在MA{ma_period}上方3%以上，多头市场 ✅"
    elif current_price < current_ma * 0.97 or not is_above:
        status = MarketStatus.BEAR
        allow = False
        reason = f"大盘在MA{ma_period}下方，空头环境 ⛔"
    else:
        status = MarketStatus.NEUTRAL
        allow = is_above and golden_cross_ok
        reason = f"大盘在MA{ma_period}附近偏{'多' if allow else '弱'}，谨慎交易 ⚠️"

    # Volume check (avoid shrinking volume markets)
    if allow and "volume" in df.columns:
        vol = df["volume"]
        avg_vol = vol.rolling_mean(20)
        if df.height >= 20:
            latest_vol_ratio = float(vol.tail(1).item() / avg_vol.tail(1).item())
            if latest_vol_ratio < 0.70:
                allow = False
                reason += f" | 缩量: 量比={latest_vol_ratio:.2f}"

    return {
        "status": str(status),
        "allow_trading": allow,
        "reason": reason,
        "index_close": current_price,
        "index_ma": current_ma,
        "index_ma_slow": current_ma_slow,
    }


# ------------------------------------------------------------------
# Signal filtering
# ------------------------------------------------------------------


def filter_signals(
    signals_df: pl.DataFrame,
    index_df: pl.DataFrame,
    ma_period: int = 20,
    confirmation_days: int = 1,
    ma_slow: int | None = None,
) -> pl.DataFrame:
    """Remove buy signals that occur in bearish market conditions.

    Sell signals are never filtered — you should always be able to exit.

    Args:
        signals_df: Strategy signals with [date, symbol, signal, score].
        index_df: Index daily data with [date, close].
        ma_period: Fast MA period.
        confirmation_days: Consecutive days above MA required.
        ma_slow: Slow MA (e.g. 60) for golden cross filter.

    Returns:
        Filtered signals DataFrame (same schema, fewer rows).
    """
    if signals_df.is_empty():
        return signals_df

    if index_df is None or index_df.is_empty():
        return signals_df

    index_df = _normalize_index_date_col(index_df)
    df_idx = index_df.sort("trade_date")
    close = df_idx["close"]
    df_idx = df_idx.with_columns(_compute_ma(close, ma_period).alias("_ma"))

    above_ma = close >= df_idx["_ma"]

    if confirmation_days > 1:
        confirmed = pl.Series("confirmed", [False] * df_idx.height)
        above_ma_list = above_ma.to_list()
        for i in range(df_idx.height):
            if i >= confirmation_days - 1:
                confirmed[i] = all(above_ma_list[i - confirmation_days + 1 : i + 1])
        above_ma = confirmed

    if ma_slow and ma_slow > ma_period:
        df_idx = df_idx.with_columns(_compute_ma(close, ma_slow).alias("_ma_slow"))
        golden_cross = df_idx["_ma"] >= df_idx["_ma_slow"]
        above_ma = above_ma & golden_cross

    # Build date → market_ok lookup
    dates_arr = df_idx["trade_date"].to_list()
    above_arr = above_ma.to_list()
    date_ok_map = dict(zip(dates_arr, above_arr, strict=True))

    # Filter: remove buy signals on bad market days
    return signals_df.filter(
        pl.when(pl.col("signal") == "buy")
        .then(
            pl.col("date").replace_strict(date_ok_map, default=False)  # type: ignore[arg-type]
        )
        .otherwise(True)
    )


# ------------------------------------------------------------------
# Regime-based gating
# ------------------------------------------------------------------


def apply_regime_gating(
    signals_df: pl.DataFrame,
    regime_map: dict[str, str],
) -> pl.DataFrame:
    """Block buy signals in bear/crisis regimes.

    Regime mapping:
      - bull / sideways_up: allow buys
      - sideways_down / neutral: allow buys (factor model handles defense)
      - bear / crisis: block all buys

    Args:
        signals_df: Signals with [date, symbol, signal].
        regime_map: {date_str: regime}.

    Returns:
        Filtered signals.
    """
    if signals_df.is_empty():
        return signals_df

    blocked_regimes = {"bear", "crisis"}

    def _allow(row_date: str, row_signal: str) -> bool:
        if row_signal != "buy":
            return True
        regime = regime_map.get(str(row_date), "sideways_up")
        return regime not in blocked_regimes

    return signals_df.filter(
        pl.struct(["date", "signal"]).map_elements(
            lambda s: _allow(s["date"], s["signal"]),
            return_dtype=pl.Boolean,
        )
    )
