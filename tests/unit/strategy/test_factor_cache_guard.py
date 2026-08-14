# pyright: reportArgumentType=false
"""Tests for experiment raw-factor cache integrity (2026-08-14).

Guards added: (1) sampled cache (e.g. --max-stocks 500) must not be
silently reused as full-universe cache; (2) sampled runs must not
overwrite the full-market cache file.
"""

from collections import defaultdict
from pathlib import Path

import polars as pl
import pytest

from qp.strategy import multifactor as mf


class _NullLogger:
    def info(self, *a, **k):
        pass


@pytest.fixture()
def sampled_cache(tmp_path: Path) -> Path:
    """500-symbol sampled cache parquet (leftover from --max-stocks run)."""
    return _write_sampled_cache(tmp_path / "_factor_raw_cache.parquet")


def _write_sampled_cache(cache_path: Path) -> Path:
    """Create a 500-symbol x 72-month cache parquet and return its path."""
    dates = pl.date_range(pl.date(2020, 1, 1), pl.date(2025, 12, 31), interval="1w", eager=True)
    rows = []
    for sym in range(500):
        for d in dates:
            rows.append(
                {
                    "trade_date": d,
                    "symbol": f"{sym:06d}",
                    "Amplitude_5D": 0.01,
                    "Volatility_20D": 0.02,
                    "Momentum_3M": 0.03,
                }
            )
    pl.DataFrame(rows).write_parquet(cache_path)
    return cache_path


def test_cache_rejected_when_sample_too_small(tmp_path: Path, monkeypatch) -> None:
    """缓存只有 500 只（预期 3000 只）→ 视为残缺缓存拒绝。"""
    cache_path = _write_sampled_cache(tmp_path / "cache_small.parquet")
    monkeypatch.setattr(mf, "_CACHE_PATH", str(cache_path))

    all_raw: dict = {}
    ok = mf._load_raw_factors_from_cache(
        all_raw,
        {"Amplitude_5D", "Volatility_20D", "Momentum_3M"},
        logger=_NullLogger(),
        expected_symbols=3000,
    )
    assert ok is False
    assert all_raw == {}


def test_cache_accepted_when_full_universe(tmp_path: Path, monkeypatch) -> None:
    """缓存覆盖足够（≥ 预期 80%）→ 正常命中。"""
    cache_path = _write_sampled_cache(tmp_path / "cache_full.parquet")
    monkeypatch.setattr(mf, "_CACHE_PATH", str(cache_path))

    all_raw: dict = defaultdict(lambda: defaultdict(dict))
    ok = mf._load_raw_factors_from_cache(
        all_raw,
        {"Amplitude_5D", "Volatility_20D", "Momentum_3M"},
        logger=_NullLogger(),
        expected_symbols=500,
    )
    assert ok is True
    assert len(all_raw) > 0


def test_cache_accepted_when_no_expected(tmp_path: Path, monkeypatch) -> None:
    """未传 expected_symbols（旧调用方）→ 保持向后兼容命中。"""
    cache_path = _write_sampled_cache(tmp_path / "cache_legacy.parquet")
    monkeypatch.setattr(mf, "_CACHE_PATH", str(cache_path))

    all_raw: dict = defaultdict(lambda: defaultdict(dict))
    ok = mf._load_raw_factors_from_cache(
        all_raw,
        {"Amplitude_5D", "Volatility_20D", "Momentum_3M"},
        logger=_NullLogger(),
    )
    assert ok is True
