"""Unit tests for fundamental factor health incremental refresh.

Regression context: fundamental factors (PE_TTM/PB/PCF_OCF/ROE/...) were only
written once (2026-08-05 full check); the daily incremental path
(FactorHealthPipeline.run_incremental) never covered them because they are NOT
columns of factor_values_daily.parquet. These tests verify:

  1. _build_fundamental_score_frames builds PIT-aligned score frames
     (publish_date <= trade_date) for valuation + quality factors.
  2. run_incremental(include_fundamental=True) persists fundamental factors
     into factor_health.parquet.
"""

from __future__ import annotations

import polars as pl
import pytest

from qp.monitoring.factor_health_pipeline import (
    _QUALITY_FACTORS,
    _VALUATION_BY_FIELD,
    FactorHealthPipeline,
)


def _make_price_df() -> pl.DataFrame:
    """Small price frame: 3 symbols × 6 trading days (2026-08-03..08-10)."""
    rows = []
    dates = ["2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06", "2026-08-07", "2026-08-10"]
    for sym in ["000001", "000002", "000003"]:
        for i, d in enumerate(dates):
            rows.append({"trade_date": d, "symbol": sym, "close": 10.0 + i})
    return pl.DataFrame(rows)


def _make_fund_df() -> pl.DataFrame:
    """Fundamental reports: one old report + one new report published later."""
    return pl.DataFrame(
        {
            "symbol": ["000001", "000001", "000002", "000003"],
            "report_date": ["2026-03-31", "2026-06-30", "2026-03-31", "2026-03-31"],
            "publish_date": [
                "2026-04-20 00:00:00",
                "2026-08-20 00:00:00",
                "2026-04-20 00:00:00",
                "2026-04-20 00:00:00",
            ],
            "EPS": [1.0, 1.2, 2.0, 0.5],
            "NAV": [4.0, 5.0, 10.0, 2.0],
            "cashflow_per_share": [0.5, 0.6, 1.0, 0.25],
            "ROE": [10.0, 12.0, 15.0, 5.0],
            "gross_margin": [30.0, 33.0, 40.0, 20.0],
            "revenue_growth": [5.0, 8.0, 10.0, 2.0],
            "net_margin": [8.0, 9.0, 12.0, 4.0],
            "debt_ratio": [50.0, 48.0, 30.0, 60.0],
            "net_profit_growth": [3.0, 6.0, 9.0, 1.0],
        }
    )


def test_build_fundamental_score_frames_pit(tmp_path, monkeypatch):
    import qp.monitoring.factor_health_pipeline as fhp

    # Point FUNDAMENTALS_LATEST at synthetic data
    monkeypatch.setattr(fhp, "FUNDAMENTALS_LATEST", tmp_path / "fundamentals.parquet")
    _make_fund_df().write_parquet(tmp_path / "fundamentals.parquet")

    pipe = FactorHealthPipeline()
    # Redirect logger base (not used here, but keeps writes out of real data)
    monkeypatch.setattr(pipe._logger, "_base", tmp_path)
    monkeypatch.setattr(pipe._logger, "_filepath", tmp_path / "factor_health.parquet")

    frames = pipe._build_fundamental_score_frames(_make_price_df(), lookback_days=60)

    # All 9 fundamental factors present
    assert set(frames) == set(_VALUATION_BY_FIELD) | set(_QUALITY_FACTORS), frames.keys()

    pe = frames["PE_TTM"]
    # PIT: old EPS (1.0) visible until 08-20 report, so PE = close / 1.0
    assert pe.filter(pl.col("symbol") == "000001")["score"].min() == pytest.approx(10.0)
    # PB: close / NAV(4.0)
    pb = frames["PB"]
    assert pb.filter(pl.col("symbol") == "000001")["score"].min() == pytest.approx(10.0 / 4.0)
    # Quality factor: old ROE (10.0) visible throughout window (new report pub 08-20)
    roe = frames["ROE"]
    assert roe.filter(pl.col("symbol") == "000001")["score"].n_unique() == 1
    assert roe.filter(pl.col("symbol") == "000001")["score"].unique().to_list() == [10.0]

    # All dates covered
    dates = sorted(pe["trade_date"].unique().to_list())
    assert dates == [
        "2026-08-03",
        "2026-08-04",
        "2026-08-05",
        "2026-08-06",
        "2026-08-07",
        "2026-08-10",
    ], dates


def test_run_incremental_writes_fundamental(tmp_path, monkeypatch):
    pipe = FactorHealthPipeline()
    # Redirect logger storage to temp dir
    monkeypatch.setattr(pipe._logger, "_base", tmp_path)
    monkeypatch.setattr(pipe._logger, "_filepath", tmp_path / "factor_health.parquet")

    # Factor values file only has price/volume factors (realistic: no PE_TTM)
    fv = pl.DataFrame(
        {
            "trade_date": [
                "2026-08-05",
                "2026-08-05",
                "2026-08-05",
                "2026-08-06",
                "2026-08-06",
                "2026-08-06",
            ],
            "symbol": ["000001", "000002", "000003"] * 2,
            "Momentum_1M": [0.1, 0.2, 0.3, 0.11, 0.21, 0.31],
        }
    )

    # Monkeypatch FUNDAMENTALS_LATEST read to synthetic data
    fund_df = _make_fund_df()
    import qp.monitoring.factor_health_pipeline as fhp

    monkeypatch.setattr(fhp, "FUNDAMENTALS_LATEST", tmp_path / "fundamentals.parquet")
    fund_df.write_parquet(tmp_path / "fundamentals.parquet")

    result = pipe.run_incremental(
        factor_values=fv,
        price_df=_make_price_df(),
        include_fundamental=True,
        min_stocks_per_day=2,  # synthetic data has only 3 symbols
        forward_days=1,  # 6-day price window can't support forward_days=5
    )

    assert result.status.value == "success", result.errors
    # All 9 fundamentals + 1 price/volume factor should be attempted
    assert result.metrics["n_factors_updated"] >= 9, result.metrics

    # Health snapshots persisted for fundamental factors
    health = pl.read_parquet(tmp_path / "factor_health.parquet")
    names = set(health["factor_name"].unique().to_list())
    assert {"PE_TTM", "ROE"} <= names, names


def test_run_incremental_without_fundamental_skips(tmp_path, monkeypatch):
    """include_fundamental=False keeps old behavior (price/volume only)."""
    pipe = FactorHealthPipeline()
    monkeypatch.setattr(pipe._logger, "_base", tmp_path)
    monkeypatch.setattr(pipe._logger, "_filepath", tmp_path / "factor_health.parquet")

    fv = pl.DataFrame(
        {
            "trade_date": [
                "2026-08-05",
                "2026-08-05",
                "2026-08-05",
                "2026-08-06",
                "2026-08-06",
                "2026-08-06",
            ],
            "symbol": ["000001", "000002", "000003"] * 2,
            "Momentum_1M": [0.1, 0.2, 0.3, 0.11, 0.21, 0.31],
        }
    )

    pipe.run_incremental(
        factor_values=fv,
        price_df=_make_price_df(),
        include_fundamental=False,
        min_stocks_per_day=2,
        forward_days=1,
    )

    health_path = tmp_path / "factor_health.parquet"
    assert health_path.exists(), "no health file written"
    health = pl.read_parquet(health_path)
    names = set(health["factor_name"].unique().to_list())
    assert names == {"Momentum_1M"}, names
