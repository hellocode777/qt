"""FactorHealthPipeline — daily per-factor health monitoring pipeline.

Runs factor-level health checks and persists results. Designed to be:
  1. Run standalone for ad-hoc factor analysis.
  2. Called as a sub-step from KillSwitchPipeline for daily monitoring.

Extends BasePipeline so it can be scheduled via the scheduler.

Usage:
    pipeline = FactorHealthPipeline()
    result = pipeline.run(context)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import polars as pl

from qp.monitoring.factor_health import (
    FactorHealthMonitor,
    FactorHealthStage,
    FactorHealthStatus,
    FactorLifecycle,
)
from qp.monitoring.factor_health_logger import FactorHealthLogger
from qp.platform.pipeline.result import PipelineResult
from qp.shared.paths import FACTOR_VALUES_DAILY, FUNDAMENTALS_LATEST
from qp.shared.protocols.base_pipeline import BasePipeline
from qp.shared.time import fmt_date
from qp.shared.types import PipelineStatus

# ── Fundamental factors tracked by the health monitor ──
# Valuation ratios are derived per share (EPS/NAV/cashflow) × close, PIT-aligned.
FUNDAMENTAL_HEALTH_FACTORS: list[str] = [
    "PE_TTM",
    "PB",
    "PCF_OCF",
    "ROE",
    "gross_margin",
    "revenue_growth",
    "net_margin",
    "debt_ratio",
    "net_profit_growth",
]

# Valuation factor → fundamental per-share field it is derived from
_VALUATION_BY_FIELD: dict[str, str] = {
    "PE_TTM": "EPS",
    "PB": "NAV",
    "PCF_OCF": "cashflow_per_share",
}

# Quality factors read directly from the latest visible report
_QUALITY_FACTORS: list[str] = [
    "ROE",
    "gross_margin",
    "revenue_growth",
    "net_margin",
    "debt_ratio",
    "net_profit_growth",
]

# Lookback window for fundamental score frames (trading days).
# 420 ≈ 1.6 years — enough for IC_252d and matches the historical update.
_FUND_LOOKBACK_DAYS = 420


@dataclass
class FactorHealthReport:
    """Aggregated factor health report from a single pipeline run.

    Attributes:
        run_id: Pipeline run identifier.
        timestamp: When the check was performed.
        factors: Per-factor health statuses.
        n_healthy: Count of HEALTHY factors.
        n_warning: Count of WARNING factors.
        n_degraded: Count of DEGRADED factors.
        n_stale: Count of STALE factors.
        overall_stage: Worst stage across all factors.
        summary: One-line summary.
        alerts: Active alert messages.
    """

    run_id: str = ""
    timestamp: str = ""
    factors: list[FactorHealthStatus] = field(default_factory=list)
    n_healthy: int = 0
    n_warning: int = 0
    n_degraded: int = 0
    n_stale: int = 0
    overall_stage: FactorHealthStage = FactorLifecycle.PRODUCTION
    summary: str = ""
    alerts: list[str] = field(default_factory=list)

    @property
    def has_degradation(self) -> bool:
        """True if any factor is DEGRADED or STALE."""
        return self.overall_stage in (
            FactorHealthStage.DEGRADED,
            FactorLifecycle.RETIRED,
        )

    @property
    def degraded_factors(self) -> list[str]:
        """Names of DEGRADED or STALE factors."""
        return [
            f.factor_name
            for f in self.factors
            if f.stage in (FactorHealthStage.DEGRADED, FactorLifecycle.RETIRED)
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "n_healthy": self.n_healthy,
            "n_warning": self.n_warning,
            "n_degraded": self.n_degraded,
            "n_stale": self.n_stale,
            "overall_stage": str(self.overall_stage),
            "summary": self.summary,
            "alerts": self.alerts,
            "factors": [f.to_dict() for f in self.factors],
        }


class FactorHealthPipeline(BasePipeline):
    """Daily per-factor health monitoring pipeline.

    Computes per-factor IC from raw factor scores, evaluates rolling
    health metrics, and persists results to Parquet.

    Follows the same BasePipeline pattern as KillSwitchPipeline.

    Usage:
        pipeline = FactorHealthPipeline()
        result = pipeline.run(context)
        if result.status == PipelineStatus.SUCCESS:
            report = result.metadata.get("factor_health_report")
    """

    def __init__(
        self,
        monitor: FactorHealthMonitor | None = None,
        logger: FactorHealthLogger | None = None,
    ) -> None:
        self._monitor = monitor or FactorHealthMonitor()
        self._logger = logger or FactorHealthLogger()

    @property
    def name(self) -> str:
        return "factor_health_pipeline"

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def run(self, context: Any) -> PipelineResult:
        """Run factor health checks.

        Expects context.parameters to contain:
          - factor_daily_ics: dict[str, list[float]]
              {factor_name: [daily_ic, ...]} — per-factor daily IC series.
          - reference_ic_map: dict[str, float] (optional)
              {factor_name: reference_ic_mean} — training-period IC per factor.
          - date_str: str (optional)
              Trading date for the health snapshot.

        If factor_daily_ics is not in context, attempts to extract it
        from context.metadata or context parameters.

        Returns:
            PipelineResult with FactorHealthReport in metadata.
        """
        result = PipelineResult(status=PipelineStatus.SUCCESS)
        result.pipeline_name = self.name

        try:
            # Extract data from context
            params = self._get_params(context)
            factor_ics = params.get("factor_daily_ics", {})
            reference_map = params.get("reference_ic_map", {})
            date_str = params.get("date_str", "")

            if not factor_ics:
                result.status = PipelineStatus.PARTIAL
                result.errors.append("No factor_daily_ics provided — nothing to check")
                return result

            # ── Check each factor ──
            statuses: list[FactorHealthStatus] = []
            for fname, daily_ics in factor_ics.items():
                # Use factor-specific reference IC if available
                ref_ic = reference_map.get(fname, 0.0)
                if ref_ic:
                    self._monitor._reference_ic = abs(ref_ic)
                else:
                    self._monitor._reference_ic = None

                status = self._monitor.check_factor(fname, daily_ics)
                statuses.append(status)

            # ── Build report ──
            report = self._build_report(statuses, date_str)

            # ── Persist ──
            try:
                self._logger.log_batch(statuses, date_str=date_str)
            except Exception as e:
                result.errors.append(f"Failed to persist factor health: {e}")

            # ── Populate result ──
            result.metadata["factor_health_report"] = report
            result.metrics = {
                "n_healthy": float(report.n_healthy),
                "n_warning": float(report.n_warning),
                "n_degraded": float(report.n_degraded),
                "n_stale": float(report.n_stale),
                "n_factors_total": float(len(statuses)),
            }

        except Exception as e:
            result.status = PipelineStatus.FAILED
            result.errors.append(f"Factor health pipeline failed: {e}")

        return result

    # ------------------------------------------------------------------
    # Incremental daily update — called by daily_pipeline after factor calc
    # ------------------------------------------------------------------

    def run_incremental(
        self,
        factor_values: pl.DataFrame | None = None,
        price_df: pl.DataFrame | None = None,
        forward_days: int = 5,
        min_stocks_per_day: int = 10,
        include_fundamental: bool = True,
    ) -> PipelineResult:
        """Incrementally refresh factor health using the latest factor values.

        Designed to run after FactorCalcPipeline in the daily pipeline:
          1. Load factor_values_daily.parquet (if not passed in) — the
             latest computed factor scores per (date, symbol).
          2. For each factor, build a [trade_date, symbol, score] frame and
             compute the daily Rank IC series against price data.
          3. Append new IC days to factor_ic_series.parquet (dedup by
             (factor_name, date)) and log a fresh health snapshot to
             factor_health.parquet (dedup by (factor_name, date)).

        Forward returns are prepared **once per horizon** for all factors
        (see ``prepare_forward_returns``), not once per factor per horizon —
        that hoisting is what keeps this incremental pass affordable on a
        multi-year price history.  Only the dates present in ``factor_values``
        are evaluated; health is then re-classified from the accumulated IC
        history.

        Args:
            factor_values: Optional [trade_date, symbol, <factor cols>] frame.
                Defaults to reading data/dataset/factor_values_daily.parquet.
            price_df: Optional [trade_date, symbol, close] frame used for
                forward returns. Defaults to daily_price@latest.
            forward_days: Forward return horizon for IC.
            min_stocks_per_day: Minimum stocks per cross-section.

        Returns:
            PipelineResult with n_factors_updated in metrics.
        """
        result = PipelineResult(status=PipelineStatus.SUCCESS, pipeline_name=self.name)
        from datetime import UTC, datetime

        from qp.research.evaluation.rank_ic import (
            DEFAULT_DECAY_HORIZONS,
            compute_daily_ic_series_from_forward,
            compute_ic_decay_from_forward,
            prepare_forward_returns,
        )

        try:
            # ── 1. Load inputs ──
            if factor_values is None:
                from pathlib import Path

                p = Path(FACTOR_VALUES_DAILY)
                if not p.exists():
                    result.status = PipelineStatus.PARTIAL
                    result.errors.append("factor_values_daily.parquet not found")
                    return result
                factor_values = pl.read_parquet(p)

            if price_df is None:
                from qp.data.loader.loader import load_dataset

                price_df = load_dataset("daily_price")

            if factor_values.is_empty() or price_df is None or price_df.is_empty():
                result.status = PipelineStatus.PARTIAL
                result.errors.append("Empty factor_values or price data")
                return result

            fv = factor_values
            px = price_df
            assert fv is not None
            assert px is not None

            # ── 2. Identify factor columns (exclude keys) ──
            key_cols = {"trade_date", "symbol"}
            factor_cols = [c for c in fv.columns if c not in key_cols]
            if not factor_cols:
                result.status = PipelineStatus.PARTIAL
                result.errors.append("No factor columns in factor_values")
                return result

            # ── 2b. Fundamental factor score frames (PIT-aligned) ──
            # Valuation/quality factors live in fundamentals_latest.parquet, not in
            # factor_values_daily.parquet — build score frames here so the daily
            # incremental path also covers them (previously only the one-off
            # 2026-08-05 full check wrote them; nothing after that).
            fund_scores: dict[str, pl.DataFrame] = {}
            if include_fundamental:
                try:
                    fund_scores = self._build_fundamental_score_frames(px)
                except Exception as exc:
                    result.errors.append(f"fundamental score frames: {exc}")
                # merge into factor list (dedup, keep order)
                for fname in fund_scores:
                    if fname not in factor_cols:
                        factor_cols.append(fname)

            # ── 3. Build every factor's score frame ──
            # The union of their dates drives how much price history the
            # forward returns below need to keep.
            score_frames: dict[str, pl.DataFrame] = {}
            skipped: list[str] = []
            for fname in factor_cols:
                if fname in fund_scores:
                    score_df = fund_scores[fname]
                else:
                    score_df = fv.select(
                        pl.col("trade_date").cast(pl.Utf8).alias("trade_date"),
                        pl.col("symbol").cast(pl.Utf8).alias("symbol"),
                        pl.col(fname).alias("score"),
                    ).drop_nulls(subset=["score"])

                if score_df.is_empty():
                    skipped.append(fname)
                    continue
                score_frames[fname] = score_df

            # ── 3b. Prepare forward returns ONCE per horizon ──
            # Previously each factor paid the sort/shift over the price history
            # once per horizon (28 factors × 6 horizons = 168 full passes);
            # hoisting it out of the factor loop is the bulk of the speedup.
            decay_horizons = list(DEFAULT_DECAY_HORIZONS)
            horizons = sorted({forward_days, *decay_horizons})
            prepared: dict[int, pl.DataFrame] = {}
            if score_frames:
                query_dates = pl.concat(
                    [
                        frame.select(pl.col("trade_date").cast(pl.Utf8))
                        for frame in score_frames.values()
                    ]
                )["trade_date"].unique()
                prepared = {h: prepare_forward_returns(px, h, query_dates) for h in horizons}

            date_str = fmt_date(datetime.now(UTC))
            updated = 0

            # ── 3c. Per-factor IC + health ──
            for fname, score_df in score_frames.items():
                try:
                    daily_records = compute_daily_ic_series_from_forward(
                        score_df,
                        prepared[forward_days],
                        min_stocks_per_day=min_stocks_per_day,
                    )
                    if not daily_records:
                        skipped.append(fname)
                        continue

                    # Append only NEW IC days (dedup by factor_name+date)
                    self._logger.save_daily_ic_series(fname, daily_records)

                    # Re-classify health from accumulated IC series
                    ic_series = self._logger.load_ic_series(fname)
                    if ic_series.is_empty():
                        skipped.append(fname)
                        continue
                    ics = ic_series["ic"].to_list()
                    status = self._monitor.check_factor(fname, ics)

                    # Multi-horizon decay curve (1d/3d/5d/10d/20d) from the
                    # forward returns already prepared for this run.
                    multi_horizon: dict[int, float] = {}
                    try:
                        decay_records = compute_ic_decay_from_forward(
                            score_df,
                            prepared,
                            horizons=decay_horizons,
                            min_stocks_per_day=min_stocks_per_day,
                        )
                        for h, rec in decay_records.items():
                            multi_horizon[h] = rec.ic_mean
                    except Exception:
                        pass

                    self._logger.log(status, date_str=date_str, multi_horizon_ic=multi_horizon)
                    updated += 1
                except Exception as e:
                    result.errors.append(f"{fname}: {e}")
                    skipped.append(fname)

            result.metrics["n_factors_updated"] = float(updated)
            result.metrics["n_factors_skipped"] = float(len(skipped))
            result.metadata["date_str"] = date_str
            if skipped:
                result.metadata["skipped_factors"] = ",".join(skipped)
        except Exception as e:
            result.status = PipelineStatus.FAILED
            result.errors.append(str(e))

        return result

    def _build_fundamental_score_frames(
        self,
        price_df: pl.DataFrame,
        lookback_days: int = _FUND_LOOKBACK_DAYS,
    ) -> dict[str, pl.DataFrame]:
        """Build PIT-aligned score frames for fundamental factors.

        Fundamental factors (PE_TTM/PB/PCF_OCF/ROE/...) are NOT stored in
        factor_values_daily.parquet — they live in fundamentals_latest.parquet.
        This builds ``{factor_name: DataFrame[trade_date, symbol, score]}`` for
        the trailing ``lookback_days`` trading days, PIT-aligned on
        ``publish_date <= trade_date``:

          - Valuation factors (PE_TTM/PB/PCF_OCF): derived as close / per-share
            value from the latest visible report (same logic as
            qp.data.valuation.product.compute_valuation, but vectorized).
          - Quality factors (ROE/gross_margin/...): raw latest visible value.

        Returns:
            Empty dict when fundamentals are missing. Keys are factor names.
        """
        from pathlib import Path

        fund_path = Path(FUNDAMENTALS_LATEST)
        if not fund_path.exists():
            return {}

        try:
            fund = pl.read_parquet(fund_path)
        except Exception:
            return {}

        if fund.is_empty() or "symbol" not in fund.columns:
            return {}

        if "publish_date" not in fund.columns:
            return {}

        # ── Normalize dates to YYYY-MM-DD strings (publish_date may be datetime) ──
        fund = fund.with_columns(
            pl.col("publish_date").cast(pl.Utf8).str.slice(0, 10).alias("pub_date")
        )
        fund = fund.filter(pl.col("pub_date").is_not_null())

        # ── Restrict to recent trading dates (cheap + stable window) ──
        px = price_df.with_columns(pl.col("trade_date").cast(pl.Utf8).str.slice(0, 10).alias("td"))
        dates = sorted(px["td"].unique().to_list())
        if len(dates) > lookback_days:
            window_start = dates[-lookback_days]
            px = px.filter(pl.col("td") >= window_start)
            fund = fund.filter(pl.col("pub_date") <= dates[-1])

        px = px.select(["td", "symbol", "close"]).sort(["symbol", "td"])

        # ── PIT join: latest report with publish_date <= trade_date ──
        # Vectorized asof join — much faster than per-symbol compute_valuation.
        fund = fund.select(
            [
                "symbol",
                "pub_date",
                *_VALUATION_BY_FIELD.values(),
                *_QUALITY_FACTORS,
            ]
        ).sort(["symbol", "pub_date"])
        # Drop duplicate (symbol, pub_date) rows: keep the last (latest report_date)
        # NOTE: unique() does NOT preserve order — re-sort is REQUIRED for join_asof.
        fund = fund.unique(subset=["symbol", "pub_date"], keep="last").sort(["symbol", "pub_date"])

        merged = px.join_asof(
            fund,
            left_on="td",
            right_on="pub_date",
            by="symbol",
            strategy="backward",
        )

        result: dict[str, pl.DataFrame] = {}

        # ── Valuation factors: close / per-share value ──
        for fname, fund_field in _VALUATION_BY_FIELD.items():
            if fund_field not in merged.columns:
                continue
            df = merged.filter(
                pl.col(fund_field).is_not_null() & (pl.col(fund_field) > 0)
            ).with_columns((pl.col("close") / pl.col(fund_field)).alias("score"))
            result[fname] = df.select(
                pl.col("td").alias("trade_date"),
                pl.col("symbol"),
                pl.col("score"),
            )

        # ── Quality factors: latest visible report value ──
        for fname in _QUALITY_FACTORS:
            if fname not in merged.columns:
                continue
            df = merged.filter(pl.col(fname).is_not_null()).with_columns(
                pl.col(fname).alias("score")
            )
            result[fname] = df.select(
                pl.col("td").alias("trade_date"),
                pl.col("symbol"),
                pl.col("score"),
            )

        return result

    # ------------------------------------------------------------------
    # Convenience: run from raw factor scores
    # ------------------------------------------------------------------

    def run_from_scores(
        self,
        factor_scores: dict[str, pl.DataFrame],
        price_df: pl.DataFrame,
        forward_days: int = 5,
        min_stocks_per_day: int = 10,
        reference_ic_map: dict[str, float] | None = None,
        date_str: str = "",
    ) -> PipelineResult:
        """Run health checks directly from per-factor score DataFrames.

        Computes daily IC per factor, then delegates to the standard
        monitor/classify pipeline.

        Args:
            factor_scores: {factor_name: DataFrame[trade_date, symbol, score]}.
            price_df: DataFrame[trade_date, symbol, close] for forward returns.
            forward_days: Forward return horizon for IC.
            min_stocks_per_day: Minimum stocks per cross-section for IC.
            reference_ic_map: Optional per-factor reference IC values.
            date_str: Trading date.

        Returns:
            PipelineResult with FactorHealthReport.
        """
        from qp.research.evaluation.rank_ic import compute_daily_ic_series

        factor_ics: dict[str, list[float]] = {}
        computed_ref: dict[str, float] = {}

        for fname, score_df in factor_scores.items():
            daily = compute_daily_ic_series(
                score_df,
                price_df,
                forward_days=forward_days,
                min_stocks_per_day=min_stocks_per_day,
            )
            if daily:
                ics = [r["ic"] for r in daily]
                factor_ics[fname] = ics
                # Use mean as fallback reference
                import numpy as np

                arr = np.array(ics, dtype=float)
                computed_ref[fname] = float(np.mean(arr[~np.isnan(arr)]))

        # Merge reference maps (explicit > computed)
        ref_map = dict(computed_ref)
        if reference_ic_map:
            ref_map.update(reference_ic_map)

        # Build parameters and run
        params = {
            "factor_daily_ics": factor_ics,
            "reference_ic_map": ref_map,
            "date_str": date_str,
        }

        # Create a simple context-like object
        class _Ctx:
            parameters: dict[str, Any] = {}

        ctx = _Ctx()
        ctx.parameters = params

        return self.run(ctx)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_params(self, context: Any) -> dict[str, Any]:
        """Extract parameters from various context shapes."""
        # PipelineContext
        if hasattr(context, "parameters") and isinstance(context.parameters, dict):
            return context.parameters
        # Raw dict
        if isinstance(context, dict):
            return context
        # Fallback: try metadata
        if hasattr(context, "metadata") and isinstance(context.metadata, dict):
            return context.metadata
        return {}

    def _build_report(
        self,
        statuses: list[FactorHealthStatus],
        date_str: str = "",
    ) -> FactorHealthReport:
        """Aggregate per-factor statuses into a report."""
        counts: dict[FactorHealthStage, int] = {
            FactorLifecycle.PRODUCTION: 0,
            FactorLifecycle.VALIDATED: 0,
            FactorHealthStage.DEGRADED: 0,
            FactorLifecycle.RETIRED: 0,
        }
        for s in statuses:
            counts[s.stage] = counts.get(s.stage, 0) + 1

        # Overall stage = worst across all factors
        severity = {
            FactorLifecycle.PRODUCTION: 0,
            FactorLifecycle.VALIDATED: 1,
            FactorHealthStage.DEGRADED: 2,
            FactorLifecycle.RETIRED: 3,
        }
        overall = FactorLifecycle.PRODUCTION
        for s in statuses:
            if severity.get(s.stage, 0) > severity.get(overall, 0):
                overall = s.stage

        # Build alerts
        alerts: list[str] = []
        degraded = [
            s for s in statuses if s.stage in (FactorHealthStage.DEGRADED, FactorLifecycle.RETIRED)
        ]
        if degraded:
            names = ", ".join(s.factor_name for s in degraded)
            alerts.append(f"{len(degraded)} factor(s) degraded/stale: {names}")

        warning_only = [s for s in statuses if s.stage == FactorLifecycle.VALIDATED]
        if warning_only:
            names = ", ".join(s.factor_name for s in warning_only)
            alerts.append(f"{len(warning_only)} factor(s) in warning: {names}")

        total = len(statuses)
        summary = (
            f"Factor Health: {counts[FactorLifecycle.PRODUCTION]}H / "
            f"{counts[FactorLifecycle.VALIDATED]}W / "
            f"{counts[FactorHealthStage.DEGRADED]}D / "
            f"{counts[FactorLifecycle.RETIRED]}S "
            f"(total {total})"
        )

        return FactorHealthReport(
            run_id="",
            timestamp=datetime.now(UTC).isoformat(),
            factors=statuses,
            n_healthy=counts[FactorLifecycle.PRODUCTION],
            n_warning=counts[FactorLifecycle.VALIDATED],
            n_degraded=counts[FactorHealthStage.DEGRADED],
            n_stale=counts[FactorLifecycle.RETIRED],
            overall_stage=overall,
            summary=summary,
            alerts=alerts,
        )
