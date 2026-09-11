"""Online Signal Monitor — daily health checks for approved strategies.

ADR-031 Step 6: Continuous monitoring of live strategies without
re-running research validation (IC, Sharpe, Overfit).

Checks:
  - Realized IC (close-to-close correlation with prior signal ranks)
  - Signal concentration (Herfindahl-Hirschman Index on symbol weights)
  - Signal strength (dispersion of raw scores)

Distinct from research validation:
  - Research: IC, Sharpe, MaxDD, PurgedCV (one-time, at experiment time)
  - Online: rolling IC, concentration, drift (every daily run)

Data flow:
  Daily Pipeline → generate_signals → score today's signals
      → persist to data/monitoring/online_signal_history.parquet
      → compute rolling metrics → health check → alert if degraded
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from qp.shared.paths import ONLINE_SIGNAL_HISTORY

# Persistence path
_ONLINE_SIGNAL_PARQUET = Path(ONLINE_SIGNAL_HISTORY)
_ONLINE_HEALTH_PARQUET = Path("data/monitoring/online_health_history.parquet")

# Thresholds (rule.md §10.3, ADR-031 §Online Monitoring)
ROLLING_IC_WARN = 0.02  # 20-day IC below this → WARNING
ROLLING_IC_HALT = 0.01  # 60-day IC below this → HALT
CONCENTRATION_WARN = 0.60  # Top-3 symbol weight > 60% → WARNING
SIGNAL_DISPERSION_MIN = 0.001  # Score std too low → signals too uniform

# ── Data-sufficiency gates for the realized rolling IC ──────────────
# The realized IC is a mean of per-signal-day Spearman correlations.  Its
# standard error is driven by the number of symbols ranked *per day*, not
# by the number of days: n=5 names/day gives a single-day IC SE of ≈0.45,
# so a 20-day mean of it carries SE ≈0.16 — 30x coarser than the 0.005
# absolute floor used by ModelDecayTrigger.  Judging decay on such a
# sample produces false STALE verdicts (observed 2026-09-10: rolling IC
# 0.0023 while the full-cross-section IC was +0.077, t=+5.3).
#
# Therefore: refuse to report a value at all when the sample cannot
# support any verdict.  300 names/day → single-day SE ≈0.058; with
# ≥10 contributing days the mean's SE is ≈0.018, i.e. the same order as
# ROLLING_IC_WARN, which is the coarsest scale the check pretends to
# resolve.  Callers get ``None`` (= "not measured"), never a number that
# looks like a measurement but is noise.
MIN_IC_PAIRS_PER_DAY = 300
MIN_IC_CONTRIB_DAYS = 10

# ── Signal-history sampling ─────────────────────────────────────────
# The history used to persist only the strategy's candidate signals
# (3-18 symbols/day in production), which left the realized IC
# unmeasurable.  Persist a deterministic cross-section sample instead:
# both score tails (where the spread lives) plus an evenly spaced middle
# band → 500 rows/day, comfortably above MIN_IC_PAIRS_PER_DAY.
HISTORY_SAMPLE_PER_SIDE = 200
HISTORY_SAMPLE_MIDDLE = 100


@dataclass
class OnlineHealthResult:
    """Result of one day's online health check.

    Attributes:
        date: Check date.
        strategy_id: Strategy being monitored.
        rolling_ic_20d: Mean rank IC over last 20 trading days.
        rolling_ic_60d: Mean rank IC over last 60 trading days.
        signal_count: Number of signals generated today.
        signal_concentration: HHI over top-N signals (0-1, lower=better).
        signal_dispersion: Std of raw scores (higher=better).
        health_score: Composite 0-100 score.
        level: HealthLevel string.
        alerts: List of alert messages (empty = healthy).
    """

    date: str
    strategy_id: str
    rolling_ic_20d: float = 0.0
    rolling_ic_60d: float = 0.0
    signal_count: int = 0
    signal_concentration: float = 0.0
    signal_dispersion: float = 0.0
    health_score: float = 100.0
    level: str = "healthy"
    alerts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "date": self.date,
            "strategy_id": self.strategy_id,
            "rolling_ic_20d": self.rolling_ic_20d,
            "rolling_ic_60d": self.rolling_ic_60d,
            "signal_count": self.signal_count,
            "signal_concentration": self.signal_concentration,
            "signal_dispersion": self.signal_dispersion,
            "health_score": self.health_score,
            "level": self.level,
            "alerts": ",".join(self.alerts),
        }


class OnlineSignalMonitor:
    """Daily online health monitor for approved strategies.

    Tracks signal quality trends without re-running research validation.
    Persists signal snapshots and health metrics to parquet for trend
    analysis and WebUI display.

    Usage:
        monitor = OnlineSignalMonitor()
        result = monitor.check(
            strategy_id="momentum_vol_full",
            today=today_cn(),
            signals_df=signals,   # [symbol, raw_score, rank]
            price_data=price_data,  # {symbol: DataFrame}
        )
        if result.alerts:
            logger.warning("Online monitor alerts: {}", result.alerts)
    """

    def __init__(self) -> None:
        self._signal_history: pl.DataFrame | None = None
        # Diagnostic for the most recent rolling_ic() call — populated with
        # the sample it saw, so callers can log *why* an IC was not
        # measurable instead of silently reading "no value" as "healthy".
        self.last_ic_sample: dict[str, Any] | None = None

    # ── Main entry point ───────────────────────────────────────

    def check(
        self,
        strategy_id: str,
        today: date,
        signals_df: pl.DataFrame,
        price_data: dict[str, pl.DataFrame],
        score_universe_df: pl.DataFrame | None = None,
    ) -> OnlineHealthResult:
        """Run a full online health check for a strategy.

        Args:
            strategy_id: Strategy identifier.
            today: Check date.
            signals_df: Today's signals [symbol, raw_score, rank].
            price_data: Full price data {symbol: DataFrame}.
            score_universe_df: Today's FULL cross-section scores
                [symbol, raw_score, rank].  When supplied, this (not the
                candidate signals) is sampled into the persisted signal
                history — otherwise the realized IC is computed over the
                top-N tail alone and is pure noise
                (docs/tracking/rolling_ic_false_stale.md).  ``None`` keeps
                the legacy candidate-only history.

        Returns:
            OnlineHealthResult with metrics and alerts.
        """
        date_str = today.isoformat()
        alerts: list[str] = []
        n_signals = signals_df.height if signals_df is not None else 0

        # ── Compute today's metrics ──
        concentration = self._compute_concentration(signals_df)
        dispersion = self._compute_dispersion(signals_df)

        # ── Persist today's signal snapshot ──
        self._save_signal_snapshot(strategy_id, date_str, signals_df, score_universe_df)

        # ── Compute rolling IC ──
        ic_20d = self._compute_realized_ic(strategy_id, price_data, window=20)
        ic_60d = self._compute_realized_ic(strategy_id, price_data, window=60)

        # ── Health scoring ──
        score = 100.0

        # Rolling IC check
        if ic_20d > 0 and ic_20d < ROLLING_IC_WARN:
            alerts.append(f"Rolling IC(20d)={ic_20d:.4f} < {ROLLING_IC_WARN}")
            score -= 25
        if ic_60d > 0 and ic_60d < ROLLING_IC_HALT:
            alerts.append(f"Rolling IC(60d)={ic_60d:.4f} < {ROLLING_IC_HALT} — HALT")
            score -= 40

        # Signal concentration check
        if concentration > CONCENTRATION_WARN:
            alerts.append(f"Signal concentration={concentration:.1%} > {CONCENTRATION_WARN:.0%}")
            score -= 15

        # Signal dispersion check
        if 0 < dispersion < SIGNAL_DISPERSION_MIN:
            alerts.append(f"Signal dispersion={dispersion:.6f} < {SIGNAL_DISPERSION_MIN}")
            score -= 10

        score = max(0.0, score)

        # Determine health level
        if score >= 80:
            level = "healthy"
        elif score >= 60:
            level = "watch"
        elif score >= 40:
            level = "warning"
        else:
            level = "critical"

        result = OnlineHealthResult(
            date=date_str,
            strategy_id=strategy_id,
            rolling_ic_20d=round(ic_20d, 4),
            rolling_ic_60d=round(ic_60d, 4),
            signal_count=n_signals,
            signal_concentration=round(concentration, 4),
            signal_dispersion=round(dispersion, 6),
            health_score=round(score, 1),
            level=level,
            alerts=alerts,
        )

        # Persist health record
        self._save_health(result)

        return result

    # ── Metric computations ────────────────────────────────────

    @staticmethod
    def _compute_concentration(signals_df: pl.DataFrame) -> float:
        """Herfindahl-Hirschman Index over top-N signal scores.

        HHI = sum(w_i²) where w_i = score_i / sum(scores).
        Lower = more diversified.  Only meaningful when n_signals >= 3.
        """
        if signals_df is None or signals_df.is_empty():
            return 0.0
        if signals_df.height < 3:
            return 1.0 / signals_df.height if signals_df.height > 0 else 0.0

        scores = signals_df["raw_score"].to_numpy().astype(np.float64)
        scores = np.abs(scores)  # Use absolute scores for concentration
        total = scores.sum()
        if total == 0:
            return 0.0
        weights = scores / total
        return float(np.sum(weights**2))

    @staticmethod
    def _compute_dispersion(signals_df: pl.DataFrame) -> float:
        """Standard deviation of raw scores (higher = more differentiated)."""
        if signals_df is None or signals_df.is_empty():
            return 0.0
        if signals_df.height < 2:
            return 0.0
        scores = signals_df["raw_score"].to_numpy().astype(np.float64)
        return float(np.std(scores))

    def _compute_realized_ic(
        self,
        strategy_id: str,
        price_data: dict[str, pl.DataFrame],
        window: int = 20,
    ) -> float:
        """Mean realized rank IC over the window (0.0 when not computable).

        Kept for the daily health score; the kill-switch path goes through
        :meth:`rolling_ic`, which additionally enforces the data-sufficiency
        gates and returns ``None`` rather than a noise-dominated number.
        """
        ics, _pairs = self._realized_ic_detail(strategy_id, price_data, window=window)
        return float(np.mean(ics)) if ics else 0.0

    def _realized_ic_detail(
        self,
        strategy_id: str,
        price_data: dict[str, pl.DataFrame],
        window: int = 20,
    ) -> tuple[list[float], list[int]]:
        """Per-day realized rank ICs plus the sample size behind each one.

        Correlation between prior signal rank and subsequent return over the
        last ``window`` signal records.  For each day in the signal history we
        check the next day's close return for each symbol, then compute
        Spearman rank correlation.

        Returns:
            ``(ic_values, pairs_per_day)`` — aligned lists.  A day appears
            only when it had >= 5 rankable symbols and a non-NaN IC.
            ``([], [])`` when there is not enough signal history.
        """
        history = self._load_signal_history(strategy_id)
        if history is None or history.is_empty() or history.height < 5:
            return [], []
        history = self._universe_rows(history)

        # Get recent signal dates (last window entries by unique date)
        dates = history.select("date").unique().sort("date").tail(window)["date"].to_list()
        if len(dates) < 5:
            return [], []

        ic_values: list[float] = []
        pair_counts: list[int] = []
        for _i, signal_date in enumerate(dates[:-1]):  # Exclude today
            day_signals = history.filter(pl.col("date") == signal_date)
            if day_signals.is_empty():
                continue

            # Find next trading day for each symbol
            ranks: list[float] = []
            returns: list[float] = []
            for row in day_signals.iter_rows(named=True):
                symbol = str(row["symbol"])
                score = float(row["raw_score"])
                pdf = price_data.get(symbol)
                if pdf is None or pdf.is_empty():
                    continue

                # Find signal date row and next row
                date_col = "trade_date" if "trade_date" in pdf.columns else "date"
                pdf_sorted = pdf.sort(date_col)
                date_series = pdf_sorted[date_col].cast(pl.Utf8).to_list()
                close_series = pdf_sorted["close"].to_list()

                try:
                    idx = date_series.index(signal_date)
                    if idx + 1 < len(close_series):
                        next_close = close_series[idx + 1]
                        cur_close = close_series[idx]
                        if cur_close > 0:
                            ret = (next_close - cur_close) / cur_close
                            ranks.append(score)
                            returns.append(ret)
                except (ValueError, IndexError):
                    continue

            if len(ranks) >= 5:
                # Spearman rank correlation
                try:
                    from scipy.stats import spearmanr

                    result = spearmanr(ranks, returns)
                    # Handle both tuple and SignificanceResult across scipy versions
                    if hasattr(result, "correlation"):
                        corr = float(str(result.correlation))  # type: ignore[union-attr]
                    elif hasattr(result, "__getitem__"):
                        corr = float(str(result[0]))  # type: ignore[index]
                    else:
                        corr = float(str(result))  # type: ignore[arg-type]
                    if not np.isnan(corr):
                        ic_values.append(corr)
                        pair_counts.append(len(ranks))
                except Exception:
                    pass

        return ic_values, pair_counts

    def rolling_ic(
        self,
        strategy_id: str,
        price_data: dict[str, pl.DataFrame],
        window: int = 20,
    ) -> float | None:
        """Public realized rolling IC for monitoring.

        Unlike ``_compute_realized_ic`` (which returns 0.0 when data is
        missing), this returns **None** whenever the sample cannot support a
        verdict — so callers can distinguish "not measured" from "real
        decay".  Callers must NOT treat None as a zero IC.

        ``None`` is returned when either:

        * there is insufficient signal history (< 5 signal days), or
        * the effective sample is too thin (:data:`MIN_IC_CONTRIB_DAYS`
          contributing days, each ranking at least
          :data:`MIN_IC_PAIRS_PER_DAY` symbols).  A mean over a handful of
          5-name days is noise (single-day IC SE ≈0.45), and reporting it as
          a measurement is what produced the false STALE verdict on
          2026-09-10.

        Args:
            strategy_id: Strategy identifier.
            price_data: Full price data {symbol: DataFrame}.
            window: Rolling window size.

        Returns:
            Mean rank IC over the window, or None when not measurable.
        """
        self.last_ic_sample = None
        history = self._load_signal_history(strategy_id)
        if history is None or history.is_empty() or history.height < 5:
            self.last_ic_sample = {
                "reason": "history_too_short",
                "height": 0 if history is None else history.height,
            }
            return None

        ics, pairs = self._realized_ic_detail(strategy_id, price_data, window=window)
        median_pairs = float(np.median(pairs)) if pairs else 0.0
        measurable = len(ics) >= MIN_IC_CONTRIB_DAYS and median_pairs >= MIN_IC_PAIRS_PER_DAY
        # P1-3: the point estimate alone cannot support a decay verdict — the
        # kill switch needs the sampling error of the mean as well.
        ic_se = float(np.std(ics, ddof=1) / np.sqrt(len(ics))) if len(ics) >= 2 else 0.0
        self.last_ic_sample = {
            "reason": "measured" if measurable else "insufficient_sample",
            "window": window,
            "contrib_days": len(ics),
            "median_pairs_per_day": median_pairs,
            "se": ic_se,
            "min_pairs_required": MIN_IC_PAIRS_PER_DAY,
            "min_days_required": MIN_IC_CONTRIB_DAYS,
        }

        if not measurable:
            return None
        return float(np.mean(ics))

    # ── Persistence ────────────────────────────────────────────

    @staticmethod
    def _universe_rows(history: pl.DataFrame) -> pl.DataFrame:
        """Keep only the cross-section sample rows (``kind == "universe"``).

        The IC must be computed on the sampled cross-section; the day's
        candidate signals sit in the extreme tail and carry no spread
        (docs/tracking/rolling_ic_false_stale.md).  Histories written before
        the ``kind`` column existed stored candidates only — return them
        unchanged so those days simply stay "not measurable" instead of
        being misread.
        """
        if "kind" in history.columns:
            return history.filter(pl.col("kind") == "universe")
        return history

    @staticmethod
    def _sample_universe(universe_df: pl.DataFrame) -> pl.DataFrame:
        """Deterministic cross-section sample for the signal history.

        Keeps both score tails (the spread a rank IC needs) plus an evenly
        spaced slice of the middle band.  Deterministic so re-runs of the
        same day persist byte-identical rows.

        Returns:
            ``[symbol, raw_score, rank]`` with up to
            ``2*HISTORY_SAMPLE_PER_SIDE + HISTORY_SAMPLE_MIDDLE`` rows.
            Empty frame when the input is unusable.
        """
        if universe_df is None or universe_df.is_empty():
            return pl.DataFrame()
        required = {"symbol", "raw_score", "rank"}
        if not required.issubset(set(universe_df.columns)):
            return pl.DataFrame()

        df = universe_df.drop_nulls(["symbol", "raw_score"]).sort("raw_score", descending=True)
        total = 2 * HISTORY_SAMPLE_PER_SIDE + HISTORY_SAMPLE_MIDDLE
        if df.height <= total:
            return df

        top = df.head(HISTORY_SAMPLE_PER_SIDE)
        bottom = df.tail(HISTORY_SAMPLE_PER_SIDE)
        middle = df.slice(HISTORY_SAMPLE_PER_SIDE, df.height - 2 * HISTORY_SAMPLE_PER_SIDE)
        step = max(1, middle.height // HISTORY_SAMPLE_MIDDLE)
        middle = middle.gather_every(step).head(HISTORY_SAMPLE_MIDDLE)

        return pl.concat([top, middle, bottom])

    def _save_signal_snapshot(
        self,
        strategy_id: str,
        date_str: str,
        signals_df: pl.DataFrame,
        score_universe_df: pl.DataFrame | None = None,
    ) -> None:
        """Persist today's signals to the history parquet (idempotent).

        Two row kinds are stored per day, tagged in the ``kind`` column:

        * ``candidate`` — the strategy's own signals (what "how many signals
          did it emit today" means, consumed by StrategyMonitor's health score)
        * ``universe`` — a deterministic sample of the full cross-section
          (what the realized IC must be computed on)

        Mixing the two silently is what made the IC noise *and* would have
        tripped "High signals: avg 500/day > max 30" — see
        docs/tracking/rolling_ic_false_stale.md.

        Rows for ``(strategy_id, date_str)`` are replaced, not appended, so
        repeated runs of the same day cannot inflate the sample (previously
        whole days were tripled, see §3.3 of the same doc).
        """
        frames: list[pl.DataFrame] = []

        def _tag(df: pl.DataFrame | None, kind: str) -> pl.DataFrame | None:
            if df is None or df.is_empty():
                return None
            if not {"symbol", "raw_score", "rank"}.issubset(set(df.columns)):
                return None
            return df.select(
                pl.lit(date_str).alias("date"),
                pl.lit(strategy_id).alias("strategy_id"),
                pl.col("symbol"),
                pl.col("raw_score"),
                pl.col("rank"),
                pl.lit(kind).alias("kind"),
            )

        candidates = _tag(signals_df, "candidate")
        if candidates is not None:
            frames.append(candidates)
        if score_universe_df is not None:
            sampled = _tag(self._sample_universe(score_universe_df), "universe")
            if sampled is not None:
                frames.append(sampled)
        if not frames:
            return
        record = pl.concat(frames, how="vertical")

        try:
            existing = (
                pl.read_parquet(str(_ONLINE_SIGNAL_PARQUET))
                if _ONLINE_SIGNAL_PARQUET.exists()
                else None
            )
            if existing is not None and not existing.is_empty():
                existing = existing.filter(
                    ~(
                        (pl.col("strategy_id") == strategy_id)
                        & (pl.col("date").cast(pl.Utf8) == date_str)
                    )
                )
                # Rows written before ``kind`` existed were candidate signals.
                if not existing.is_empty() and "kind" not in existing.columns:
                    existing = existing.with_columns(pl.lit("candidate").alias("kind"))
                combined = (
                    pl.concat([existing, record], how="vertical")
                    if not existing.is_empty()
                    else record
                )
            else:
                combined = record
            _ONLINE_SIGNAL_PARQUET.parent.mkdir(parents=True, exist_ok=True)
            combined.write_parquet(str(_ONLINE_SIGNAL_PARQUET))
            # Written history changed → drop the in-memory cache so later
            # reads in this process see the new rows.
            self._signal_history = None
        except OSError:
            pass

    def _load_signal_history(self, strategy_id: str) -> pl.DataFrame | None:
        """Load signal history for a strategy."""
        if self._signal_history is not None:
            return self._signal_history.filter(pl.col("strategy_id") == strategy_id)
        if not _ONLINE_SIGNAL_PARQUET.exists():
            return None
        try:
            df = pl.read_parquet(str(_ONLINE_SIGNAL_PARQUET))
            self._signal_history = df
            return df.filter(pl.col("strategy_id") == strategy_id)
        except OSError:
            return None

    def _save_health(self, result: OnlineHealthResult) -> None:
        """Append health record to history parquet."""
        record = pl.DataFrame([result.to_dict()])
        try:
            existing = (
                pl.read_parquet(str(_ONLINE_HEALTH_PARQUET))
                if _ONLINE_HEALTH_PARQUET.exists()
                else None
            )
            if existing is not None and not existing.is_empty():
                combined = pl.concat([existing, record], how="vertical")
            else:
                combined = record
            _ONLINE_HEALTH_PARQUET.parent.mkdir(parents=True, exist_ok=True)
            combined.write_parquet(str(_ONLINE_HEALTH_PARQUET))
        except OSError:
            pass

    def load_health_history(
        self,
        strategy_id: str,
        days: int = 30,
    ) -> list[dict[str, Any]]:
        """Load recent health records for a strategy."""
        if not _ONLINE_HEALTH_PARQUET.exists():
            return []
        try:
            df = pl.read_parquet(str(_ONLINE_HEALTH_PARQUET))
            result = df.filter(pl.col("strategy_id") == strategy_id).sort("date").tail(days)
            return result.to_dicts()
        except OSError:
            return []
