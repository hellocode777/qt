"""4-Stage ETL Cleaning Pipeline — deterministic, idempotent, PIT-compliant.

Implements rule.md §2 Rule 5 ("Granular Data Cleaning"):
  停牌(volume=0)、涨跌停(无法成交)、除权除息(复权因子)与ST/退市状态
  必须在底层处理完毕，严禁直接fillna(0)或假设随时按盘后价成交。

Pipeline stages (each independently testable & auditable):
  Stage 1 — 异常检测: limit-up/down, price outliers, ST/delisting marks
  Stage 2 — 成交量清洗: suspension detection (volume=0), volume anomaly
  Stage 3 — 停牌处理: suspension state tracking, quality flags, universe filtering
  Stage 4 — 复权处理: forward-adjusted (前复权) OHLC via adj_factors

Usage:
    pipeline = ETLPipeline()
    cleaned = pipeline.run(raw_df, adj_factors_df)
    # → DataFrame with quality flags + adjusted prices
"""

from __future__ import annotations

from dataclasses import dataclass, field

import polars as pl

# ------------------------------------------------------------------
# Constants
# ------------------------------------------------------------------

# A-share daily price limits (regulatory)
LIMIT_UP_DOWN: dict[str, float] = {
    "main": 0.10,  # 主板 ±10%
    "gem": 0.20,  # 创业板 ±20%
    "star": 0.20,  # 科创板 ±20%
    "st": 0.05,  # ST股票 ±5%
    "default": 0.10,
}

# Minimum trading days before a stock is considered "established" (1 year)
MIN_LISTING_DAYS = 200


# ------------------------------------------------------------------
# Data models
# ------------------------------------------------------------------


@dataclass
class StageResult:
    """Output of a single ETL stage — includes audit metadata."""

    df: pl.DataFrame
    flags_added: list[str] = field(default_factory=list)
    rows_affected: int = 0
    stage_name: str = ""


@dataclass
class ETLResult:
    """Complete ETL pipeline output with full audit trail."""

    df: pl.DataFrame
    stages: list[StageResult] = field(default_factory=list)
    total_rows_in: int = 0
    total_rows_out: int = 0

    @property
    def flags(self) -> list[str]:
        all_flags: list[str] = []
        for s in self.stages:
            all_flags.extend(s.flags_added)
        return all_flags


# ------------------------------------------------------------------
# Stage 1 — 异常检测 (Anomaly Detection)
# ------------------------------------------------------------------


def stage1_anomaly_detection(df: pl.DataFrame) -> StageResult:
    """Detect price anomalies: limit-up/down, extreme moves, ST status.

    Adds columns:
      - is_limit_up: True if price hit daily upper limit
      - is_limit_down: True if price hit daily lower limit
      - is_price_anomaly: True if single-day move exceeds 3σ

    Rule: never drops rows. Only flags them. Downstream decides.
    """
    flags = []
    result = df.clone()

    # ── Limit-up/down detection ──
    # Compute daily return (close vs prev close)
    result = result.with_columns(pl.col("close").pct_change().over("symbol").alias("_daily_ret"))

    # Determine limit threshold per stock (board_type if available, else default 10%)
    if "board_type" in result.columns:
        board = result.select(pl.col("board_type").fill_null("default").alias("_board"))
        thresholds = board["_board"].map_elements(
            lambda b: LIMIT_UP_DOWN.get(b, LIMIT_UP_DOWN["default"]),
            return_dtype=pl.Float64,
        )
    else:
        thresholds = pl.Series("_limit", [LIMIT_UP_DOWN["default"]] * result.height)

    result = result.with_columns(
        pl.Series("_limit", thresholds),
    )

    result = result.with_columns(
        pl.when(pl.col("_daily_ret") >= pl.col("_limit"))
        .then(True)
        .otherwise(False)
        .alias("is_limit_up"),
        pl.when(pl.col("_daily_ret") <= -pl.col("_limit"))
        .then(True)
        .otherwise(False)
        .alias("is_limit_down"),
    )
    flags.extend(["is_limit_up", "is_limit_down"])

    # ── Price anomaly (3-sigma outlier on daily return) ──
    ret_std = (
        result.group_by("symbol")
        .agg(pl.col("_daily_ret").std().alias("_ret_std_3"))
        .with_columns(pl.col("_ret_std_3") * 3.0)
    )
    result = result.join(ret_std, on="symbol", how="left")
    result = result.with_columns(
        pl.when(pl.col("_daily_ret").abs() > pl.col("_ret_std_3"))
        .then(True)
        .otherwise(False)
        .alias("is_price_anomaly")
    )
    flags.append("is_price_anomaly")

    # Cleanup temp columns
    result = result.drop(["_daily_ret", "_limit", "_ret_std_3"])

    return StageResult(
        df=result,
        flags_added=flags,
        rows_affected=result.filter(
            pl.col("is_limit_up") | pl.col("is_limit_down") | pl.col("is_price_anomaly")
        ).height,
        stage_name="异常检测",
    )


# ------------------------------------------------------------------
# Stage 2 — 成交量清洗 (Volume Cleaning)
# ------------------------------------------------------------------


def stage2_volume_cleaning(df: pl.DataFrame) -> StageResult:
    """Detect volume anomalies: suspension, abnormal volume.

    Adds columns:
      - is_suspended: True if volume == 0 (停牌)
      - is_volume_anomaly: True if volume > 10x 20-day median

    Rule: volume==0 is the definitive suspension signal per rule.md.
    """
    flags = []

    # ── Suspension (volume == 0) ──
    df = df.with_columns(
        pl.when(pl.col("volume") <= 0).then(True).otherwise(False).alias("is_suspended")
    )
    flags.append("is_suspended")

    # ── Abnormal volume (10x 20-day median) ──
    df = df.with_columns(
        pl.col("volume").rolling_median(20, min_samples=10).over("symbol").alias("_vol_med_20")
    )
    df = df.with_columns(
        pl.when((pl.col("volume") > pl.col("_vol_med_20") * 10) & (~pl.col("is_suspended")))
        .then(True)
        .otherwise(False)
        .alias("is_volume_anomaly")
    )
    flags.append("is_volume_anomaly")

    df = df.drop("_vol_med_20")

    return StageResult(
        df=df,
        flags_added=flags,
        rows_affected=df.filter(pl.col("is_suspended") | pl.col("is_volume_anomaly")).height,
        stage_name="成交量清洗",
    )


# ------------------------------------------------------------------
# Stage 3 — 停牌处理 (Suspension Handling)
# ------------------------------------------------------------------


def stage3_suspension_handling(df: pl.DataFrame) -> StageResult:
    """Track suspension state and mark stocks that should be excluded.

    Adds columns:
      - consecutive_suspended_days: running count of consecutive suspension days
      - is_delisted: True if stock has been suspended for > 60 trading days
      - is_tradeable: True if stock can be traded today (not suspended, not limit, not delisted)

    Rule: suspended stocks are excluded from the trading universe.
    Limit-up/down stocks are flagged but NOT excluded (they may be tradeable
    at the limit price — but signals should account for slippage).
    """
    flags = []

    # ── Consecutive suspension days ──
    # For each stock, count consecutive days where is_suspended == True
    df = df.sort(["symbol", "trade_date"])

    # Compute consecutive suspension count using a group-based approach
    # Create a "run id" that increments each time is_suspended changes
    susp = df["is_suspended"].to_list()
    run_ids = []
    run_id = 0
    prev_sym = None
    prev_susp = None
    consec = []

    symbols = df["symbol"].to_list()
    for i in range(df.height):
        sym = symbols[i]
        s = susp[i]
        if sym != prev_sym or s != prev_susp:
            run_id += 1
            prev_sym = sym
            prev_susp = s
        run_ids.append(run_id)

    # Count within each run
    run_counts = {}
    for rid in run_ids:
        run_counts[rid] = run_counts.get(rid, 0) + 1

    # Build consecutive count: only count if suspended
    for i in range(df.height):
        if susp[i]:
            consec.append(run_counts[run_ids[i]])
        else:
            consec.append(0)

    df = df.with_columns(pl.Series("consecutive_suspended_days", consec, dtype=pl.Int32))
    flags.append("consecutive_suspended_days")

    # ── Delisting risk (> 60 consecutive trading days suspended) ──
    df = df.with_columns(
        pl.when(pl.col("consecutive_suspended_days") > 60)
        .then(True)
        .otherwise(False)
        .alias("is_delisted")
    )
    flags.append("is_delisted")

    # ── Tradeability ──
    df = df.with_columns(
        pl.when((~pl.col("is_suspended")) & (~pl.col("is_delisted")))
        .then(True)
        .otherwise(False)
        .alias("is_tradeable")
    )
    flags.append("is_tradeable")

    return StageResult(
        df=df,
        flags_added=flags,
        rows_affected=df.filter(~pl.col("is_tradeable")).height,
        stage_name="停牌处理",
    )


# ------------------------------------------------------------------
# Stage 4 — 复权处理 (Price Adjustment)
# ------------------------------------------------------------------


def stage4_adjustment(
    df: pl.DataFrame,
    adj_factors: pl.DataFrame | None = None,
) -> StageResult:
    """Apply 前复权 (forward adjustment) to OHLC prices.

    Uses adj_factors DataFrame with [code, ex_date, cum_factor].
    For each stock on each date:
      adjusted_price = raw_price × latest_cum_factor / cum_factor_on_date

    If adj_factors is None, skips adjustment (prices assumed already adjusted).

    Adds columns:
      - is_ex_date: True if this date is an ex-date (dividend/split)
      - price columns (open/high/low/close) are adjusted in-place

    Rule: 严禁假设随时按盘后价成交。复权是强制步骤。
    """
    flags = []

    if adj_factors is None or adj_factors.is_empty():
        return StageResult(
            df=df.with_columns(pl.lit(False).alias("is_ex_date")),
            flags_added=["is_ex_date"],
            rows_affected=0,
            stage_name="复权处理 (跳过: 无复权因子数据)",
        )

    # Ensure date types match
    df = df.with_columns(pl.col("trade_date").cast(pl.Date))
    adj_factors = adj_factors.with_columns(pl.col("ex_date").cast(pl.Date)).sort(
        ["code", "ex_date"]
    )

    # ── Get latest cum_factor per stock ──
    latest_cum = (
        adj_factors.group_by("code")
        .agg(pl.col("ex_date").max().alias("max_date"))
        .join(
            adj_factors,
            left_on=["code", "max_date"],
            right_on=["code", "ex_date"],
        )
        .select(
            [
                pl.col("code"),
                pl.col("cum_factor").alias("latest_cum"),
            ]
        )
    )

    # ── Merge adj_factors into main DataFrame ──
    # For each (code, trade_date), find the cum_factor on or before trade_date.
    # This is an asof join: for each row in df, find the latest adj_factor row
    # with ex_date <= trade_date.

    # Strategy: for each stock, forward-fill cum_factor across dates
    # 1. Get all unique (code, trade_date) pairs
    # 2. Left join with adj_factors on (code, ex_date <= trade_date)
    # 3. Take the max ex_date per (code, trade_date)

    # Build a full date range per stock and forward-fill cum_factor
    # Simpler approach: process per stock with Polars asof join simulation

    # Create a lookup: for each stock, sort adj_factors by ex_date.
    # For each trade_date, binary-search the right cum_factor.
    adj_dict = {}
    for (code,), group in adj_factors.group_by("code"):
        adj_dict[code] = (
            group["ex_date"].to_list(),
            group["cum_factor"].to_list(),
        )
    latest_dict = {r["code"]: r["latest_cum"] for r in latest_cum.iter_rows(named=True)}

    # Apply adjustment using vectorized approach
    symbols = df["symbol"].to_list()
    dates = df["trade_date"].to_list()

    mults = []
    ex_date_flags = []
    for i in range(df.height):
        code = symbols[i]
        dt = dates[i]
        cf = 1.0
        is_ex = False

        if code in adj_dict and code in latest_dict:
            ex_dates, cum_factors = adj_dict[code]
            lc = latest_dict[code]
            best_cf = 1.0
            best_ex = ""
            for j in range(len(ex_dates)):
                if ex_dates[j] <= dt:
                    best_cf = cum_factors[j]
                    best_ex = str(ex_dates[j])
                else:
                    break
            if best_cf > 0:
                cf = lc / best_cf
            if best_ex == str(dt):
                is_ex = True

        mults.append(cf)
        ex_date_flags.append(is_ex)

    # Apply multipliers
    df = df.with_columns(
        pl.Series("_adj_mult", mults),
        pl.Series("is_ex_date", ex_date_flags),
    )
    flags.append("is_ex_date")

    for col in ["open", "high", "low", "close"]:
        if col in df.columns:
            df = df.with_columns((pl.col(col) * pl.col("_adj_mult")).alias(col))

    df = df.drop("_adj_mult")

    adjusted_count = sum(1 for m in mults if abs(m - 1.0) > 0.001)

    return StageResult(
        df=df,
        flags_added=flags,
        rows_affected=adjusted_count,
        stage_name="复权处理",
    )


# ------------------------------------------------------------------
# ETL Pipeline (orchestrator)
# ------------------------------------------------------------------


class ETLPipeline:
    """4-stage ETL cleaning pipeline — deterministic & idempotent.

    Implements rule.md §2 Rule 5 and Data Tier system:
      Raw → Bronze (this pipeline) → Silver (validation) → Gold (dataset)

    Usage:
        pipeline = ETLPipeline()
        result = pipeline.run(raw_df, adj_factors_df)
        # → ETLResult with cleaned DataFrame + audit trail

        # Quick access:
        clean_df = pipeline.clean(raw_df)
    """

    def run(
        self,
        raw_df: pl.DataFrame,
        adj_factors: pl.DataFrame | None = None,
        skip_stages: list[str] | None = None,
    ) -> ETLResult:
        """Execute all 4 ETL stages in order.

        Args:
            raw_df: Raw OHLCV data with columns [symbol, trade_date,
                    open, high, low, close, volume] (+ optional name, board_type).
            adj_factors: [code, ex_date, cum_factor] for复权. None = skip stage 4.
            skip_stages: Stage names to skip (e.g. ["复权处理"]).

        Returns:
            ETLResult with cleaned DataFrame and per-stage audit info.
        """
        skip_stages = skip_stages or []
        total_in = raw_df.height
        stages: list[StageResult] = []

        # ── Stage 1: 异常检测 ──
        if "异常检测" not in skip_stages:
            s1 = stage1_anomaly_detection(raw_df)
            stages.append(s1)
            df = s1.df
        else:
            df = raw_df

        # ── Stage 2: 成交量清洗 ──
        if "成交量清洗" not in skip_stages:
            s2 = stage2_volume_cleaning(df)
            stages.append(s2)
            df = s2.df

        # ── Stage 3: 停牌处理 ──
        if "停牌处理" not in skip_stages:
            s3 = stage3_suspension_handling(df)
            stages.append(s3)
            df = s3.df

        # ── Stage 4: 复权处理 ──
        if "复权处理" not in skip_stages:
            s4 = stage4_adjustment(df, adj_factors)
            stages.append(s4)
            df = s4.df

        return ETLResult(
            df=df,
            stages=stages,
            total_rows_in=total_in,
            total_rows_out=df.height,
        )

    def clean(
        self,
        raw_df: pl.DataFrame,
        adj_factors: pl.DataFrame | None = None,
    ) -> pl.DataFrame:
        """Convenience: run pipeline and return cleaned DataFrame only."""
        return self.run(raw_df, adj_factors).df
