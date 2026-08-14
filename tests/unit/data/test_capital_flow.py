# pyright: reportArgumentType=false
"""Tests for CapitalFlowPipeline + CapitalFlowProduct + pipeline wiring.

2026-08-14: capital_flow module was dead code (0 refs, 0 coverage).
Now: qp ingest capital-flow → Gold parquet; multifactor_pipeline has
_load_capital_flow_data() that degrades to {} when file is missing.
"""

import polars as pl

from qp.data.capital_flow.adapter import CapitalFlowAdapter
from qp.data.capital_flow.product import CapitalFlowProduct
from qp.pipeline.capital_flow_pipeline import CapitalFlowPipeline
from qp.pipeline.multifactor_pipeline import MultiFactorPipeline
from qp.platform.pipeline.context import PipelineContext

# ── CapitalFlowAdapter ──


def test_adapter_column_mapping() -> None:
    """中文列 → 英文列映射正确。"""
    import pandas as pd

    fake = pd.DataFrame(
        {
            "日期": ["2026-08-13"],
            "收盘价": [100.0],
            "涨跌幅": [1.5],
            "主力净流入-净额": [123456.0],
            "主力净流入-净占比": [2.1],
            "超大单净流入-净额": [100.0],
            "大单净流入-净额": [200.0],
            "中单净流入-净额": [300.0],
            "小单净流入-净额": [400.0],
        }
    )
    adapter = CapitalFlowAdapter(cache_dir="data/capital_flow_cache_test")
    mapped = fake.rename(
        columns={
            "日期": "date",
            "收盘价": "close",
            "涨跌幅": "change_pct",
            "主力净流入-净额": "main_net_flow",
            "主力净流入-净占比": "main_net_flow_pct",
            "超大单净流入-净额": "super_large_net",
            "大单净流入-净额": "large_net",
            "中单净流入-净额": "medium_net",
            "小单净流入-净额": "small_net",
        }
    )
    assert "main_net_flow" in mapped.columns
    assert adapter.validate_schema(mapped.assign(symbol="600519"))


def test_adapter_fetch_raw_empty_without_symbols() -> None:
    adapter = CapitalFlowAdapter(cache_dir="data/capital_flow_cache_test")
    import datetime

    df = adapter.fetch_raw(datetime.date(2026, 1, 1), datetime.date(2026, 8, 13))
    assert df.empty


# ── CapitalFlowPipeline ──


def test_pipeline_quick_mode_writes_parquet(tmp_path, monkeypatch) -> None:
    """quick 模式（CORE_SYMBOLS）拉取 → 落盘 parquet + 注册。"""
    monkeypatch.chdir(tmp_path)

    import pandas as pd

    fake = pd.DataFrame(
        {
            "symbol": ["600519", "000001"],
            "date": ["2026-08-12", "2026-08-12"],
            "close": [100.0, 50.0],
            "change_pct": [1.0, -0.5],
            "main_net_flow": [10000.0, -5000.0],
            "main_net_flow_pct": [2.0, -1.0],
            "super_large_net": [8000.0, -3000.0],
            "large_net": [2000.0, -2000.0],
            "medium_net": [100.0, 500.0],
            "small_net": [900.0, 500.0],
        }
    )

    class FakeAdapter:
        def fetch_raw(self, start_date, end_date, symbols=None):
            assert symbols is not None and len(symbols) > 0
            return fake

    monkeypatch.setattr("qp.pipeline.capital_flow_pipeline.CapitalFlowAdapter", FakeAdapter)

    pipeline = CapitalFlowPipeline()
    ctx = PipelineContext(pipeline_name="capital_flow_ingest", parameters={"quick": True})
    result = pipeline.run(ctx)

    assert result.status.value == "success"
    assert result.metrics["output_symbols"] == 2
    path = tmp_path / "data" / "dataset" / "capital_flow_latest.parquet"
    assert path.exists()
    df = pl.read_parquet(path)
    assert df.height == 2
    assert set(df["symbol"].to_list()) == {"600519", "000001"}


def test_pipeline_fails_on_zero_rows(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    class EmptyAdapter:
        def fetch_raw(self, start_date, end_date, symbols=None):
            import pandas as pd

            return pd.DataFrame()

    monkeypatch.setattr("qp.pipeline.capital_flow_pipeline.CapitalFlowAdapter", EmptyAdapter)

    pipeline = CapitalFlowPipeline()
    ctx = PipelineContext(pipeline_name="capital_flow_ingest", parameters={"quick": True})
    result = pipeline.run(ctx)

    assert result.status.value == "failed"


# ── multifactor_pipeline 接线 ──


def test_multifactor_load_capital_flow_missing_returns_empty(tmp_path, monkeypatch) -> None:
    """parquet 缺失 → 返回空 dict（下游跳过），不抛错。"""
    monkeypatch.chdir(tmp_path)
    result = MultiFactorPipeline._load_capital_flow_data()
    assert result == {}


def test_multifactor_load_capital_flow_reads_file(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "data" / "dataset" / "capital_flow_latest.parquet"
    path.parent.mkdir(parents=True)
    pl.DataFrame(
        {
            "symbol": ["600519", "600519", "000001"],
            "date": pl.date_range(
                pl.date(2026, 8, 11), pl.date(2026, 8, 13), interval="1d", eager=True
            ),
            "main_net_flow": [100.0, 200.0, -50.0],
        }
    ).write_parquet(path)

    result = MultiFactorPipeline._load_capital_flow_data()
    assert set(result.keys()) == {"600519", "000001"}
    assert result["600519"].height == 2
    assert result["600519"]["main_net_flow"].to_list() == [100.0, 200.0]


# ── CapitalFlowProduct ──


def test_product_get_snapshot() -> None:
    """get_snapshot 返回 as_of_date 当日（或之前）最新横截面数据。"""
    product = CapitalFlowProduct()
    product._flow_data = {
        "600519": pl.DataFrame(
            {
                "symbol": ["600519", "600519", "600519"],
                "date": pl.date_range(
                    pl.date(2026, 8, 10), pl.date(2026, 8, 12), interval="1d", eager=True
                ),
                "main_net_flow": [1.0, 2.0, 3.0],
            }
        )
    }
    snap = product.get_snapshot("2026-08-11")
    assert snap.height == 1
    assert snap["symbol"].to_list() == ["600519"]
    assert snap["main_net_flow"].to_list() == [2.0]


def test_product_get_flow_filters_range() -> None:
    product = CapitalFlowProduct()
    product._flow_data = {
        "600519": pl.DataFrame(
            {
                "date": pl.date_range(
                    pl.date(2026, 8, 10), pl.date(2026, 8, 12), interval="1d", eager=True
                ),
                "main_net_flow": [1.0, 2.0, 3.0],
            }
        )
    }
    df = product.get_flow("600519", "2026-08-11", "2026-08-12")
    assert df.height == 2
    assert df["main_net_flow"].to_list() == [2.0, 3.0]


def test_product_get_flow_unknown_symbol_empty() -> None:
    product = CapitalFlowProduct()
    assert product.get_flow("999999").is_empty()
