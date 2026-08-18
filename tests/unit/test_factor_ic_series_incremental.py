"""Regression test: save_daily_ic_series must NOT wipe history on incremental writes.

Bug: the dedup logic removed the ENTIRE factor's existing history whenever
new records were appended — it compared against the factor's *full* date set
instead of only the *new* dates. Full-history writes (update-health) masked
this; incremental writes (FactorHealthPipeline.run_incremental) wiped 1782
days down to 4.
"""

from __future__ import annotations

import polars as pl

from qp.monitoring.factor_health_logger import FactorHealthLogger


def _fresh_logger(tmp_path, monkeypatch):
    logger = FactorHealthLogger()
    # Redirect storage to a temp dir so we don't touch real data.
    monkeypatch.setattr(logger, "_base", tmp_path)
    return logger


def test_incremental_append_keeps_history(tmp_path, monkeypatch):
    logger = _fresh_logger(tmp_path, monkeypatch)
    factor = "Volume_Concentration"

    # First write: two days of history
    logger.save_daily_ic_series(
        factor,
        [
            {"date": "2026-08-05", "ic": 0.089, "n_stocks": 3017},
            {"date": "2026-08-06", "ic": 0.091, "n_stocks": 3018},
        ],
    )

    # Incremental write: one overlapping + one new day
    logger.save_daily_ic_series(
        factor,
        [
            {"date": "2026-08-06", "ic": 0.091, "n_stocks": 3018},
            {"date": "2026-08-07", "ic": -0.014, "n_stocks": 3018},
        ],
    )

    df = pl.read_parquet(tmp_path / "factor_ic_series.parquet")
    df_factor = df.filter(pl.col("factor_name") == factor)

    # All three distinct days must survive (no history wipe)
    dates = sorted(df_factor["date"].to_list())
    assert dates == ["2026-08-05", "2026-08-06", "2026-08-07"], dates
    assert df_factor.height == 3, df_factor.height
    # No duplicate (factor_name, date)
    assert df_factor["date"].n_unique() == 3


def test_full_history_overwrite_equivalent(tmp_path, monkeypatch):
    """Full-history write must also be idempotent (replace same dates)."""
    logger = _fresh_logger(tmp_path, monkeypatch)
    factor = "Momentum_3M"

    logger.save_daily_ic_series(
        factor,
        [
            {"date": "2026-08-05", "ic": 0.01, "n_stocks": 3000},
            {"date": "2026-08-06", "ic": 0.02, "n_stocks": 3000},
        ],
    )
    logger.save_daily_ic_series(
        factor,
        [
            {"date": "2026-08-05", "ic": 0.01, "n_stocks": 3000},
            {"date": "2026-08-06", "ic": 0.02, "n_stocks": 3000},
            {"date": "2026-08-07", "ic": 0.03, "n_stocks": 3000},
        ],
    )

    df = pl.read_parquet(tmp_path / "factor_ic_series.parquet")
    df_factor = df.filter(pl.col("factor_name") == factor)
    assert df_factor.height == 3, df_factor.height
    assert sorted(df_factor["date"].to_list()) == [
        "2026-08-05",
        "2026-08-06",
        "2026-08-07",
    ]


def test_multiple_factors_isolated(tmp_path, monkeypatch):
    """Writes to one factor must not affect another factor's rows."""
    logger = _fresh_logger(tmp_path, monkeypatch)

    logger.save_daily_ic_series(
        "A",
        [{"date": "2026-08-05", "ic": 0.01, "n_stocks": 100}],
    )
    logger.save_daily_ic_series(
        "B",
        [{"date": "2026-08-06", "ic": 0.02, "n_stocks": 100}],
    )
    logger.save_daily_ic_series(
        "A",
        [{"date": "2026-08-07", "ic": 0.03, "n_stocks": 100}],
    )

    df = pl.read_parquet(tmp_path / "factor_ic_series.parquet")
    assert df.filter(pl.col("factor_name") == "A").height == 2
    assert df.filter(pl.col("factor_name") == "B").height == 1
