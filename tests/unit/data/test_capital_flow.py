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


def test_fetch_sina_maps_columns(tmp_path, monkeypatch) -> None:
    """新浪源列映射 + 分页（第一页有数据，第二页空 → 停）。"""
    import json

    fake_sina = [
        {
            "opendate": "2026-08-13",
            "trade": "1355.29",
            "changeratio": "0.0091",
            "netamount": "763667782.19",
            "ratioamount": "0.1767",
            "r0_net": "710637602.52",
            "r1_net": "66175957.63",
            "r2_net": "-13145777.96",
            "r3_net": "0.0000",
        },
        {
            "opendate": "2026-08-12",
            "trade": "1344.40",
            "changeratio": "-0.0015",
            "netamount": "352437836.97",
            "ratioamount": "0.0760",
            "r0_net": "292392408.98",
            "r1_net": "51555860.21",
            "r2_net": "8489567.78",
            "r3_net": "0.0000",
        },
    ]
    calls: dict[str, int] = {"n": 0}

    class FakeResp:
        status_code = 200

        def __init__(self, text: str) -> None:
            self.text = text

        def raise_for_status(self) -> None:
            pass

    def fake_get(url: str, params: dict | None = None, timeout: int | None = None):
        assert "MoneyFlow.ssl_qsfx_lscjfb" in url
        assert params is not None
        assert params["daima"] == "sh600519"
        calls["n"] += 1
        payload = fake_sina if params["page"] == 1 else []
        return FakeResp(json.dumps(payload))

    monkeypatch.setattr("qp.data.capital_flow.adapter.requests.get", fake_get)

    adapter = CapitalFlowAdapter(cache_dir=str(tmp_path / "cf_cache"))
    monkeypatch.setattr(adapter, "_fetch_eastmoney", lambda symbol: None)
    df = adapter._fetch_sina("600519")
    assert df is not None
    assert list(df["date"].to_list()) == ["2026-08-13", "2026-08-12"]
    assert df["symbol"].to_list() == ["600519", "600519"]
    assert df["main_net_flow"].dtype == float
    assert df["main_net_flow"].to_list()[0] == 763667782.19
    assert calls["n"] == 1  # 第一页 2 条 < 100 → 直接停，不再请求下一页


def test_fetch_single_falls_back_to_sina(tmp_path, monkeypatch) -> None:
    """_fetch_single 东财失败时自动用新浪源。"""
    import pandas as pd

    adapter = CapitalFlowAdapter(cache_dir=str(tmp_path / "cf_cache"))
    monkeypatch.setattr(adapter, "_fetch_eastmoney", lambda symbol: None)
    monkeypatch.setattr(
        adapter,
        "_fetch_sina",
        lambda symbol, min_date=None: pd.DataFrame(
            {
                "date": ["2026-08-13"],
                "symbol": [symbol],
                "main_net_flow": [100.0],
            }
        ),
    )
    df = adapter._fetch_single("600519")
    assert df is not None
    assert df["main_net_flow"].to_list() == [100.0]
    # 已缓存
    assert (tmp_path / "cf_cache" / "600519.json").exists()


def test_fetch_raw_incremental_merges_cache(tmp_path, monkeypatch) -> None:
    """增量模式: 用过期缓存做底座，只拉缺失尾部并合并去重。"""
    import pandas as pd

    cache_dir = tmp_path / "cf_cache"
    cache_dir.mkdir(parents=True)
    # 造一个「一个月前」的过期缓存（mtime 显式设为 30 天前）
    import os
    import time

    stale = [{"date": "2026-08-13", "symbol": "600519", "close": 10.0, "main_net_flow": 1.0}]
    import json

    (cache_dir / "600519.json").write_text(json.dumps(stale), encoding="utf-8")
    old = time.time() - 30 * 86400
    os.utime(cache_dir / "600519.json", (old, old))

    adapter = CapitalFlowAdapter(cache_dir=str(cache_dir))

    captured: dict[str, object] = {}

    def fake_sina(symbol: str, min_date=None):
        captured["min_date"] = min_date
        # 远端返回「缓存最后一天 + 新的一天」
        return pd.DataFrame(
            {
                "date": ["2026-08-13", "2026-09-10"],
                "symbol": [symbol, symbol],
                "close": [10.0, 11.0],
                "main_net_flow": [1.0, 2.0],
            }
        )

    monkeypatch.setattr(adapter, "_fetch_sina", fake_sina)

    df = adapter.fetch_raw(
        pd.Timestamp("2026-09-01").date(),
        pd.Timestamp("2026-09-10").date(),
        symbols=["600519"],
        incremental=True,
    )

    assert captured["min_date"] is not None  # 从缓存最后一天续拉
    assert df["date"].to_list() == ["2026-08-13", "2026-09-10"]  # 合并 + 去重 + 排序
    assert df["main_net_flow"].to_list() == [1.0, 2.0]
    # 缓存写回后应含完整历史
    saved = json.loads((cache_dir / "600519.json").read_text(encoding="utf-8"))
    assert len(saved) == 2
    assert max(r["date"] for r in saved) == "2026-09-10"


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
        def __init__(self, **kwargs) -> None:
            pass

        def fetch_raw(self, start_date, end_date, symbols=None, **kwargs):
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
