r"""Data repair functions for the ETL cleaning pipeline.

Provides 5 categories of repair (detect → fix → mark metadata):

  1. OHLC boundary repair: swap high<low, clip open/close to [low, high]
  2. Zero/negative price repair: NaN → ffill/bfill
  3. Amount validation: verify amount ≈ volume × avg(OHLC), fix >5% deviation
  4. Missing trading date filling: insert calendar gaps with ffill prices
  5. Board-aware price limits: 10% main, 20% GEM/STAR, 5% ST

All repairs add audit metadata columns (``_repaired``, ``_amount_fixed``,
``_inserted``, ``_limit_flag``) for downstream traceability.

Implements rule.md §2 Rule 5: "停牌(volume=0)、涨跌停(无法成交)、
除权除息(复权因子)与ST/退市状态必须在底层处理完毕".
"""

from __future__ import annotations

from typing import Any

import polars as pl
from loguru import logger

# ------------------------------------------------------------------
# Board-aware price limits
# ------------------------------------------------------------------

PRICE_LIMITS: dict[str, float] = {
    "main": 0.10,  # 主板 ±10%
    "gem": 0.20,  # 创业板 ±20%
    "star": 0.20,  # 科创板 ±20%
    "st": 0.05,  # ST股票 ±5%
}


def get_price_limit(code: str = "", name: str = "") -> float:
    """Determine daily price limit for a stock based on board and status.

    Args:
        code: 6-digit stock code.
        name: Stock name (used for ST detection).

    Returns:
        Daily limit fraction (e.g. 0.10 = ±10%).
    """
    if name and "ST" in name.upper():
        return PRICE_LIMITS["st"]
    if code.startswith(("688", "689")):
        return PRICE_LIMITS["star"]
    if code.startswith(("300", "301")):
        return PRICE_LIMITS["gem"]
    return PRICE_LIMITS["main"]


def get_board_type(code: str, name: str = "") -> str:
    """Get board type string for a stock.

    Returns:
        One of: 'main', 'gem', 'star', 'st'.
    """
    if name and "ST" in name.upper():
        return "st"
    if code.startswith(("688", "689")):
        return "star"
    if code.startswith(("300", "301")):
        return "gem"
    return "main"


# ------------------------------------------------------------------
# 1. OHLC Boundary Repair
# ------------------------------------------------------------------


def repair_ohlc_boundaries(df: pl.DataFrame) -> pl.DataFrame:
    """Detect and repair OHLC consistency violations.

    Repairs applied (non-destructive — marks metadata, never drops rows):
      - Zero/negative prices → NaN
      - NaN prices → ffill (or bfill if at start)
      - high < low → swap values
      - open/close outside [low, high] → clip to range

    Args:
        df: DataFrame with [open, high, low, close] columns.

    Returns:
        DataFrame with added ``_repaired`` column (struct of repair metadata).
    """
    price_cols = ["open", "high", "low", "close"]
    available = [c for c in price_cols if c in df.columns]
    if not available:
        return df.with_columns(pl.lit({}).alias("_repaired"))

    n = df.height
    repaired_list: list[dict[str, str]] = [{} for _ in range(n)]

    # Ensure numeric types
    for col in available:
        if df[col].dtype not in (pl.Float64, pl.Float32, pl.Int64, pl.Int32):
            df = df.with_columns(pl.col(col).cast(pl.Float64, strict=False))

    # ── Step 1: Zero/negative prices → NaN ──
    for col in available:
        bad_mask = df[col].is_not_null() & (df[col] <= 0)
        if bad_mask.any():
            bad_indices = [i for i, v in enumerate(bad_mask.to_list()) if v]
            for i in bad_indices:
                old_val = df[col][i]
                repaired_list[i][col] = f"zero_or_neg({old_val})"
            df = df.with_columns(
                pl.when(bad_mask).then(None).otherwise(pl.col(col)).alias(col)
            )

    # ── Step 2: NaN → ffill (then bfill for leading NaN) ──
    for col in available:
        null_mask = df[col].is_null()
        if null_mask.any():
            df = df.with_columns(pl.col(col).forward_fill().alias(col))
            # bfill for any remaining leading NaN
            df = df.with_columns(pl.col(col).backward_fill().alias(col))

    # ── Step 3: high < low → swap ──
    if "high" in available and "low" in available:
        hl_bad = df["high"] < df["low"]
        if hl_bad.any():
            high_vals = df["high"].to_list()
            low_vals = df["low"].to_list()
            for i, bad in enumerate(hl_bad.to_list()):
                if bad:
                    high_vals[i], low_vals[i] = low_vals[i], high_vals[i]
                    repaired_list[i]["ohlc"] = "swapped_high_low"
            df = df.with_columns(
                pl.Series("high", high_vals, dtype=pl.Float64),
                pl.Series("low", low_vals, dtype=pl.Float64),
            )

    # ── Step 4: open/close outside [low, high] → clip ──
    for col in ["open", "close"]:
        if col not in available or "low" not in available or "high" not in available:
            continue
        oob = (df[col] < df["low"]) | (df[col] > df["high"])
        if oob.any():
            df = df.with_columns(
                pl.when(oob)
                .then(pl.col(col).clip(pl.col("low"), pl.col("high")))
                .otherwise(pl.col(col))
                .alias(col)
            )
            for i, bad in enumerate(oob.to_list()):
                if bad:
                    repaired_list[i][col] = "clipped_to_range"

    # Attach metadata
    return df.with_columns(pl.Series("_repaired", repaired_list))


# ------------------------------------------------------------------
# 2. Amount Validation
# ------------------------------------------------------------------


def validate_and_fix_amount(
    df: pl.DataFrame,
    tolerance: float = 0.05,
) -> pl.DataFrame:
    """Validate and correct trading amount (成交额).

    Checks that amount ≈ volume × avg(OHLC). Deviations > tolerance
    are replaced with the expected value.

    Args:
        df: DataFrame with [open, high, low, close, volume, amount].
        tolerance: Maximum allowed deviation ratio (default 5%).

    Returns:
        DataFrame with added ``_amount_fixed`` boolean column.
    """
    if "amount" not in df.columns or "volume" not in df.columns:
        return df.with_columns(pl.lit(False).alias("_amount_fixed"))

    ohlc_cols = ["open", "high", "low", "close"]
    available = [c for c in ohlc_cols if c in df.columns]

    if len(available) < 4:
        return df.with_columns(pl.lit(False).alias("_amount_fixed"))

    # Average price from OHLC
    df = df.with_columns(
        (
            (pl.col("open") + pl.col("high") + pl.col("low") + pl.col("close")) / 4.0
        ).alias("_avg_price")
    )
    df = df.with_columns(
        (pl.col("volume") * pl.col("_avg_price")).alias("_expected_amount")
    )

    # Detect bad rows (volume > 0, deviation > tolerance)
    has_trade = df["volume"] > 0
    df = df.with_columns(
        pl.when(has_trade & (df["_expected_amount"] > 0))
        .then(
            (pl.col("amount") - pl.col("_expected_amount")).abs()
            / pl.col("_expected_amount")
        )
        .otherwise(0.0)
        .alias("_amount_deviation")
    )

    bad = has_trade & (df["_amount_deviation"] > tolerance)
    bad_count = bad.sum()
    if bad_count > 0:
        max_dev = df.filter(bad)["_amount_deviation"].max()
        logger.debug(
            "成交额异常: {} 行 (最大偏差 {:.1f}%) — 已修正",
            bad_count,
            float(max_dev) * 100 if max_dev is not None else 0,  # type: ignore[arg-type]
        )
        df = df.with_columns(
            pl.when(bad)
            .then(pl.col("_expected_amount").round(2))
            .otherwise(pl.col("amount"))
            .alias("amount")
        )

    df = df.with_columns(bad.alias("_amount_fixed"))
    return df.drop(["_avg_price", "_expected_amount", "_amount_deviation"])


# ------------------------------------------------------------------
# 3. Missing Trading Date Filling
# ------------------------------------------------------------------


def fill_missing_trading_dates(
    df: pl.DataFrame,
    trading_dates: list[str],
    code: str = "",
) -> pl.DataFrame:
    """Insert rows for missing trading dates (停牌/节假日补齐).

    Missing dates get:
      - OHLC = last available close price
      - volume = 0, amount = 0
      - _inserted = True

    Args:
        df: DataFrame with [trade_date, open, high, low, close, volume,
            amount] + optional [code/symbol].
        trading_dates: Complete list of trading dates (YYYY-MM-DD)
                       covering the stock's date range.
        code: Stock code (for logging only).

    Returns:
        DataFrame sorted by trade_date with inserted rows marked ``_inserted=True``.
    """
    if df.is_empty() or not trading_dates:
        return df.with_columns(pl.lit(False).alias("_inserted"))

    existing = set(df["trade_date"].cast(pl.Utf8).to_list())
    missing = [d for d in trading_dates if d not in existing]

    if not missing:
        return df.with_columns(pl.lit(False).alias("_inserted"))

    # Sort both for correct ffill
    df = df.sort("trade_date")
    closes = df["close"].to_list()
    dates_existing = df["trade_date"].cast(pl.Utf8).to_list()

    # Build new rows
    new_rows: list[dict[str, Any]] = []
    for d in sorted(missing):
        # Find last close on or before d
        last_close = 0.0
        for ed, ec in zip(dates_existing, closes, strict=True):
            if ed <= d:
                last_close = ec if ec is not None else last_close

        new_rows.append(
            {
                "trade_date": d,
                "open": last_close,
                "high": last_close,
                "low": last_close,
                "close": last_close,
                "volume": 0.0,
                "amount": 0.0 if "amount" in df.columns else None,
                "_inserted": True,
            }
        )

    # Merge
    df = df.with_columns(pl.lit(False).alias("_inserted"))
    new_df = pl.DataFrame(new_rows, schema=df.columns)
    result = pl.concat([df, new_df], how="diagonal_relaxed").sort("trade_date")

    logger.debug("  {}: 补齐 {} 个缺失交易日", code or "?", len(missing))
    return result


# ------------------------------------------------------------------
# 4. Suspension vs Limit-up Classification
# ------------------------------------------------------------------


def classify_suspension_type(df: pl.DataFrame) -> pl.DataFrame:
    """Classify zero-volume rows as suspension (停牌) or limit-up/down (一字板).

    Rules:
      - Consecutive zero-volume >= 3 days → ``suspension``
      - Consecutive zero-volume 1-2 days, previous day has volume → ``limit``
      - Consecutive zero-volume 1-2 days, previous day also zero-volume → ``suspension``

    Args:
        df: DataFrame with [volume] column, sorted by trade_date.

    Returns:
        DataFrame with added ``_halt_type`` column ('normal' | 'suspension' | 'limit').
    """
    if df.is_empty() or "volume" not in df.columns:
        return df.with_columns(pl.lit("normal").alias("_halt_type"))

    volumes = df["volume"].to_list()
    n = len(volumes)
    halt_types = ["normal"] * n

    i = 0
    while i < n:
        if volumes[i] is not None and volumes[i] <= 0 and i > 0:
            # Count consecutive zero-volume days
            j = i
            while j < n and (volumes[j] is not None and volumes[j] <= 0):
                j += 1
            consecutive = j - i

            # Check previous day's volume
            prev_vol = volumes[i - 1] if i > 0 else 0
            if consecutive >= 3 or (prev_vol is not None and prev_vol <= 0):
                for k in range(i, j):
                    halt_types[k] = "suspension"
            else:
                for k in range(i, j):
                    halt_types[k] = "limit"
            i = j
        else:
            i += 1

    return df.with_columns(pl.Series("_halt_type", halt_types))


# ------------------------------------------------------------------
# 5. Price Limit Anomaly Detection
# ------------------------------------------------------------------


def detect_price_limit_anomalies(
    df: pl.DataFrame,
    code: str = "",
    name: str = "",
) -> pl.DataFrame:
    """Flag daily returns that exceed the board-specific price limit.

    Distinguishes between:
      - ``normal``: within expected range
      - ``adj_jump``: large move caused by adjustment (ex-dividend) — safe
      - ``ex_limit``: exceeds limit without adjustment explanation — suspect

    Args:
        df: DataFrame with [close] column, sorted by trade_date.
        code: Stock code (for board detection).
        name: Stock name (for ST detection).

    Returns:
        DataFrame with added ``_limit_flag`` column.
    """
    if df.height < 2:
        return df.with_columns(pl.lit("normal").alias("_limit_flag"))

    # Compute daily return
    df = df.with_columns(pl.col("close").pct_change().alias("_daily_ret"))

    limit = get_price_limit(code, name)
    buffer = 1.2  # 20% buffer: main=12%, GEM/STAR=24%, ST=6%
    threshold = limit * buffer

    # Identify extreme returns
    rets = df["_daily_ret"].to_list()
    flags = ["normal"] * df.height

    for i in range(1, df.height):
        r = rets[i]
        if r is None:
            continue
        if abs(r) > threshold:
            # Check adjacent days for similar extremes (adjustment pattern)
            prev_r = abs(rets[i - 1]) if i > 1 and rets[i - 1] is not None else 0
            next_r = (
                abs(rets[i + 1]) if i < df.height - 2 and rets[i + 1] is not None else 0
            )
            is_adj_jump = (prev_r > threshold) or (next_r > threshold)
            flags[i] = "adj_jump" if is_adj_jump else "ex_limit"

    df = df.with_columns(pl.Series("_limit_flag", flags))
    return df.drop("_daily_ret")


# ------------------------------------------------------------------
# 6. Combined repair pipeline (single-pass for efficiency)
# ------------------------------------------------------------------


def repair_all(
    df: pl.DataFrame,
    code: str = "",
    name: str = "",
    trading_dates: list[str] | None = None,
    validate_amount: bool = True,
) -> pl.DataFrame:
    """Run all repair stages in a single pass.

    Stages applied in order:
      1. OHLC boundary repair
      2. Amount validation
      3. Missing date filling (if trading_dates provided)
      4. Suspension type classification
      5. Price limit anomaly detection

    Args:
        df: Raw daily OHLCV DataFrame.
        code: Stock code.
        name: Stock name.
        trading_dates: Optional complete trading date list.
        validate_amount: Enable amount validation.

    Returns:
        Repaired DataFrame with all audit metadata columns.
    """
    if df.is_empty():
        return df

    total_in = df.height

    # Stage 1: OHLC repair
    df = repair_ohlc_boundaries(df)

    # Stage 2: Amount validation
    if validate_amount:
        df = validate_and_fix_amount(df)
    else:
        df = df.with_columns(pl.lit(False).alias("_amount_fixed"))

    # Stage 3: Missing date filling
    if trading_dates:
        df = fill_missing_trading_dates(df, trading_dates, code)
    else:
        df = df.with_columns(pl.lit(False).alias("_inserted"))

    # Stage 4: Suspension classification
    df = classify_suspension_type(df)

    # Stage 5: Limit anomaly detection
    df = detect_price_limit_anomalies(df, code, name)

    # Summary
    repaired_count = sum(1 for r in df["_repaired"].to_list() if r and len(r) > 0)
    fixed_amt = df["_amount_fixed"].sum()
    inserted = df["_inserted"].sum()
    ex_limit = df.filter(pl.col("_limit_flag") == "ex_limit").height

    if repaired_count or fixed_amt or inserted or ex_limit:
        logger.info(
            "  {:<10s} 修复: OHLC={}, 成交额={}, 补齐={}, 超限={} (共{}行→{}行)",
            code,
            repaired_count,
            fixed_amt,
            inserted,
            ex_limit,
            total_in,
            df.height,
        )

    return df
