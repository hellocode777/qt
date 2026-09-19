# pyright: reportArgumentType=false
"""Tests for index data provider (Tencent source).

2026-08-14: multifactor_pipeline._load_index_data() was a hardcoded
None (quant.db dependency removed) — market filter / regime detection
silently skipped. Now reads Gold dataset (qp data index).

2026-08-20: provider switched to Tencent kline (TDR-001, same as
TencentAdapter) — AkShare was a network fallback that violates the
"腾讯 kline 唯一行情源" rule. Supports sh000300 (CSI300) and
sh000001 (上证指数) with a symbol parameter.
"""

from datetime import timedelta

import polars as pl
import pytest

from qp.data.dataset import index_provider
from qp.shared.time import today_cn


def _fake_tencent_rows() -> list[list]:
    """Rows in Tencent kline format: [date, open, close, high, low, volume]."""
    return [
        ["2026-01-05", "4000.0", "4015.0", "4010.0", "3980.0", "1000000000.0"],
        ["2026-01-06", "4020.0", "4030.0", "4040.0", "4000.0", "1200000000.0"],
    ]


def _fake_get_from_params(rows: list[list] | None):
    """Build a fake requests.get that derives the symbol from the param."""

    def fake_get(url, params, timeout):
        symbol = params["param"].split(",")[0]
        return _FakeResp(rows, symbol=symbol)

    return fake_get


def test_fetch_index_data_writes_parquet(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(index_provider, "INDEX_DIR", tmp_path)

    def fake_get(url, params, timeout):
        assert params["param"].startswith("sh000300,day,")
        # TDR-001: fqkline/get+qfq is BANNED — param must NOT carry a qfq suffix.
        assert not params["param"].endswith(",qfq")
        return _FakeResp(_fake_tencent_rows(), symbol="sh000300")

    monkeypatch.setattr(index_provider.requests, "get", fake_get)
    out = index_provider.fetch_index_data(force=True, symbol="sh000300")
    assert out == tmp_path / "index_csi300.parquet"
    df = pl.read_parquet(out)
    assert df.height == 2
    assert df["trade_date"].dtype == pl.Date
    assert df["close"].to_list() == [4015.0, 4030.0]


def test_fetch_index_data_skips_when_fresh(tmp_path, monkeypatch) -> None:
    """A fresh local file (last trade_date today) is reused without a fetch."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(index_provider, "INDEX_DIR", tmp_path)
    path = tmp_path / "index_csi300.parquet"
    _fresh_index_df().write_parquet(path)

    calls: list[str] = []

    def fake_get(url, params, timeout):
        calls.append(params["param"])
        return _FakeResp(_fake_tencent_rows(), symbol="sh000300")

    monkeypatch.setattr(index_provider.requests, "get", fake_get)
    out = index_provider.fetch_index_data(force=False, symbol="sh000300")
    assert out == path
    assert calls == []  # 新鲜 → 不重新拉


def test_fetch_index_data_refetches_when_stale(tmp_path, monkeypatch) -> None:
    """2026-09-19: an existing-but-old file used to be reused forever, which
    left index_csi300 frozen at 2026-08-20 while the market filter kept
    consuming it.  Stale files must be re-fetched."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(index_provider, "INDEX_DIR", tmp_path)
    path = tmp_path / "index_csi300.parquet"
    _index_df().write_parquet(path)  # last trade_date 2026-01-06 → stale

    calls: list[str] = []

    def fake_get(url, params, timeout):
        calls.append(params["param"])
        return _FakeResp(
            [["2026-01-05", "4000.0", "4015.0", "4010.0", "3980.0", "1000000000.0"]],
            symbol="sh000300",
        )

    monkeypatch.setattr(index_provider.requests, "get", fake_get)
    out = index_provider.fetch_index_data(force=False, symbol="sh000300")
    assert out == path
    assert len(calls) == 1  # 过时 → 重新拉


def test_fetch_index_data_raises_on_empty(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(index_provider, "INDEX_DIR", tmp_path)

    def fake_get(url, params, timeout):
        return _FakeResp(None, symbol="sh000300")

    monkeypatch.setattr(index_provider.requests, "get", fake_get)
    with pytest.raises(RuntimeError, match="空数据"):
        index_provider.fetch_index_data(force=True, symbol="sh000300")


def test_fetch_index_data_keeps_local_file_when_refresh_fails(tmp_path, monkeypatch) -> None:
    """A failed refresh must not be reported as success, and the old file stays
    on disk (callers see the error and the stale date, not a silent lie)."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(index_provider, "INDEX_DIR", tmp_path)
    path = tmp_path / "index_csi300.parquet"
    _index_df().write_parquet(path)
    before = path.read_bytes()

    def fake_get(url, params, timeout):
        raise RuntimeError("network down")

    monkeypatch.setattr(index_provider.requests, "get", fake_get)
    with pytest.raises(RuntimeError, match="本地已保留旧数据"):
        index_provider.fetch_index_data(force=False, symbol="sh000300")
    assert path.read_bytes() == before  # 未被覆盖


def test_fetch_index_sh000001_uses_own_file(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(index_provider, "INDEX_DIR", tmp_path)

    def fake_get(url, params, timeout):
        assert params["param"].startswith("sh000001,day,")
        return _FakeResp(_fake_tencent_rows(), symbol="sh000001")

    monkeypatch.setattr(index_provider.requests, "get", fake_get)
    out = index_provider.fetch_index_data(force=True, symbol="sh000001")
    assert out == tmp_path / "index_sh000001.parquet"


def test_load_index_data_returns_none_when_missing(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(index_provider, "INDEX_DIR", tmp_path)
    assert index_provider.load_index_data("sh000300") is None


def test_load_index_data_reads_file(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(index_provider, "INDEX_DIR", tmp_path)
    path = tmp_path / "index_csi300.parquet"
    _index_df().write_parquet(path)
    df = index_provider.load_index_data("sh000300")
    assert df is not None
    assert df.height == 2
    assert df["close"].to_list() == [4015.0, 4030.0]


def test_get_index_close(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(index_provider, "INDEX_DIR", tmp_path)
    path = tmp_path / "index_sh000001.parquet"
    _index_df().write_parquet(path)
    assert index_provider.get_index_close("sh000001", "2026-01-05") == 4015.0
    assert index_provider.get_index_close("sh000001", "2026-01-09") is None


def test_pipeline_load_index_data_with_local_file(tmp_path, monkeypatch) -> None:
    """pipeline._load_index_data reads the Gold dataset (no network)."""
    from qp.pipeline.multifactor_pipeline import MultiFactorPipeline

    monkeypatch.chdir(tmp_path)
    path = tmp_path / "data" / "dataset" / "index_csi300.parquet"
    path.parent.mkdir(parents=True)
    _fresh_index_df().write_parquet(path)  # fresh → no refresh attempt

    pipe = MultiFactorPipeline.__new__(MultiFactorPipeline)
    df = pipe._load_index_data()
    assert df is not None
    assert df["close"].to_list() == [4015.0, 4030.0]


class _FakeResp:
    """Minimal stand-in for requests.Response with .json().

    The index symbol is parsed from the request param string so the fake
    can serve both sh000300 and sh000001 without hardcoding.
    """

    def __init__(self, rows: list[list] | None, symbol: str = "sh000300") -> None:
        self._rows = rows
        self._symbol = symbol

    def raise_for_status(self) -> None:
        return None

    def json(self):
        if self._rows is None:
            return {"data": {self._symbol: {"day": None}}}
        return {"data": {self._symbol: {"day": self._rows}}}


def _fresh_index_df() -> pl.DataFrame:
    """Index DataFrame whose last trade_date is today (age 0 → reused as-is)."""
    today = today_cn()
    return pl.DataFrame(
        {
            "trade_date": pl.Series(
                [today - timedelta(days=3), today - timedelta(days=2)], dtype=pl.Date
            ),
            "open": [4000.0, 4020.0],
            "high": [4010.0, 4040.0],
            "low": [3980.0, 4000.0],
            "close": [4015.0, 4030.0],
            "volume": [1.0e9, 1.2e9],
        }
    )


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
