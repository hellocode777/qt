# pyright: reportArgumentType=false
"""Tests for CSI300 index data provider + pipeline integration.

2026-08-14: multifactor_pipeline._load_index_data() was a hardcoded
None (quant.db dependency removed) — market filter / regime detection
silently skipped. Now reads Gold dataset (qp data index) with lazy
network fallback.
"""

import polars as pl
import pytest

from qp.data.dataset import index_provider


def test_fetch_index_data_writes_parquet(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(index_provider, "INDEX_DATASET_PATH", tmp_path / "index_csi300.parquet")

    import pandas as pd

    fake = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-05", "2026-01-06"]),
            "open": [4000.0, 4020.0],
            "high": [4010.0, 4040.0],
            "low": [3980.0, 4000.0],
            "close": [4015.0, 4030.0],
            "volume": [1.0e9, 1.2e9],
        }
    )

    def fake_fetch(symbol: str):
        assert symbol == "sh000300"
        return fake

    monkeypatch.setattr("akshare.stock_zh_index_daily", fake_fetch)
    out = index_provider.fetch_index_data(force=True)
    assert out == tmp_path / "index_csi300.parquet"
    df = pl.read_parquet(out)
    assert df.height == 2
    assert df["trade_date"].dtype == pl.Date
    assert df["close"].to_list() == [4015.0, 4030.0]


def _index_df() -> pl.DataFrame:
    """Small valid index DataFrame (Date dtype)."""
    return pl.DataFrame(
        {
            "trade_date": pl.date_range(
                pl.date(2026, 1, 5), pl.date(2026, 1, 6), interval="1d", eager=True
            ),
            "open": [4000.0, 4020.0],
            "high": [4010.0, 4040.0],
            "low": [3980.0, 4000.0],
            "close": [4015.0, 4030.0],
            "volume": [1.0e9, 1.2e9],
        }
    )


def test_fetch_index_data_skips_when_exists(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "index_csi300.parquet"
    monkeypatch.setattr(index_provider, "INDEX_DATASET_PATH", path)
    _index_df().write_parquet(path)

    calls: list[str] = []

    def fake_fetch(symbol: str):
        calls.append(symbol)
        return None

    monkeypatch.setattr("akshare.stock_zh_index_daily", fake_fetch)
    out = index_provider.fetch_index_data(force=False)
    assert out == path
    assert calls == []  # 已存在不重新拉


def test_fetch_index_data_raises_on_empty(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(index_provider, "INDEX_DATASET_PATH", tmp_path / "index_csi300.parquet")
    monkeypatch.setattr("akshare.stock_zh_index_daily", lambda symbol: None)

    with pytest.raises(RuntimeError, match="空数据"):
        index_provider.fetch_index_data(force=True)


def test_load_index_data_returns_none_when_missing(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(index_provider, "INDEX_DATASET_PATH", tmp_path / "index_csi300.parquet")
    assert index_provider.load_index_data() is None


def test_load_index_data_reads_file(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "index_csi300.parquet"
    monkeypatch.setattr(index_provider, "INDEX_DATASET_PATH", path)
    _index_df().write_parquet(path)
    df = index_provider.load_index_data()
    assert df is not None
    assert df.height == 2
    assert df["close"].to_list() == [4015.0, 4030.0]


def test_pipeline_load_index_data_with_local_file(tmp_path, monkeypatch) -> None:
    """pipeline._load_index_data reads the Gold dataset (no network)."""
    from qp.pipeline.multifactor_pipeline import MultiFactorPipeline

    monkeypatch.chdir(tmp_path)
    path = tmp_path / "data" / "dataset" / "index_csi300.parquet"
    path.parent.mkdir(parents=True)
    _index_df().write_parquet(path)

    pipe = MultiFactorPipeline.__new__(MultiFactorPipeline)
    df = pipe._load_index_data()
    assert df is not None
    assert df["close"].to_list() == [4015.0, 4030.0]
