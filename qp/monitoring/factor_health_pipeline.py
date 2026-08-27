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
from qp.shared.paths import FACTOR_VALUES_DAILY
from qp.shared.protocols.base_pipeline import BasePipeline
from qp.shared.time import fmt_date
from qp.shared.types import PipelineStatus


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

        This is the lightweight alternative to the full-history
        ``qp factor update-health`` command: it only recomputes IC for the
        dates present in ``factor_values`` (normally the latest trading day)
        and re-classifies health from the accumulated IC history, so it runs
        in seconds rather than ~2 min per factor.

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
            compute_daily_ic_series,
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

            date_str = fmt_date(datetime.now(UTC))
            updated = 0
            skipped: list[str] = []

            # ── 3. Per-factor IC + health ──
            for fname in factor_cols:
                score_df = fv.select(
                    pl.col("trade_date").cast(pl.Utf8).alias("trade_date"),
                    pl.col("symbol").cast(pl.Utf8).alias("symbol"),
                    pl.col(fname).alias("score"),
                ).drop_nulls(subset=["score"])

                if score_df.is_empty():
                    skipped.append(fname)
                    continue

                try:
                    daily_records = compute_daily_ic_series(
                        score_df,
                        price_df,
                        forward_days=forward_days,
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

                    # Multi-horizon decay curve (1d/3d/5d/10d/20d)
                    multi_horizon: dict[int, float] = {}
                    try:
                        from qp.research.evaluation.rank_ic import compute_ic_decay

                        decay_records = compute_ic_decay(
                            score_df, price_df, min_stocks_per_day=min_stocks_per_day
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
