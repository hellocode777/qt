"""质量过滤阈值的**量纲回归测试**。

2026-10-28 事故：`DEFAULT_QUALITY_FILTERS` 写成小数语义（ROE -0.05 / gross_margin 0.10 /
net_profit_growth -0.50），而 `fundamentals_latest.parquet` 是**百分数**
（ROE 中位 ≈ 4.01、gross_margin ≈ 23.28、debt_ratio ≈ 46.80）。后果：

- `net_profit_growth`：任何净利降幅 > 0.5% 就被剔除（实测当日通过率只有 34%）；
- `gross_margin`：0.10 对百分数几乎永不触发（检查形同虚设）；
- `ROE`：把「容忍 -5%」收紧成「容忍 -0.05%」。

本测试用百分数量纲的合成数据断言筛选行为，任何把阈值改回小数的改动都会变红。
"""

from __future__ import annotations

import polars as pl

from qp.strategy.quality_filter import (
    DEFAULT_QUALITY_FILTERS,
    DEFAULT_VALUATION_FILTERS,
    _get_latest_value,
    apply_quality_filter,
    build_pit_universe,
)

DATES = ["2026-10-26", "2026-10-27", "2026-10-28"]


def _price(close: float = 10.0) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "trade_date": DATES,
            "close": [close] * len(DATES),
            "volume": [1_000_000.0] * len(DATES),
        }
    )


def _fund(
    *,
    roe: float = 5.0,
    gross_margin: float = 25.0,
    net_profit_growth: float = 10.0,
    debt_ratio: float = 50.0,
    report_date: str = "2026-03-31",
    publish_date: str = "2026-04-25",
) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "report_date": [report_date],
            "publish_date": [publish_date],
            "ROE": [roe],
            "gross_margin": [gross_margin],
            "net_profit_growth": [net_profit_growth],
            "debt_ratio": [debt_ratio],
        }
    )


def _val(pe: float = 30.0) -> pl.DataFrame:
    return pl.DataFrame({"trade_date": DATES, "PE_TTM": [pe] * len(DATES)})


def _run(*, fund: pl.DataFrame | None = None, val: pl.DataFrame | None = None) -> set[str]:
    return apply_quality_filter(
        {"600000": _price()},
        {"600000": fund} if fund is not None else {},
        {"600000": val} if val is not None else {},
    )


class TestThresholdUnits:
    """阈值必须是百分数量纲。"""

    def test_quality_thresholds_are_percent_scale(self) -> None:
        assert DEFAULT_QUALITY_FILTERS["ROE"]["min"] == -5.0
        assert DEFAULT_QUALITY_FILTERS["gross_margin"]["min"] == 10.0
        assert DEFAULT_QUALITY_FILTERS["net_profit_growth"]["min"] == -50.0
        assert DEFAULT_QUALITY_FILTERS["debt_ratio"]["max"] == 85.0

    def test_valuation_threshold_is_multiple_scale(self) -> None:
        assert DEFAULT_VALUATION_FILTERS["PE_TTM"]["min"] == 0.0
        assert DEFAULT_VALUATION_FILTERS["PE_TTM"]["max"] == 200.0


class TestNetProfitGrowth:
    """净利降幅 23% 属于正常波动，不该被剔除（修复前会被杀）。"""

    def test_negative_23_percent_passes(self) -> None:
        assert _run(fund=_fund(net_profit_growth=-23.0)) == {"600000"}

    def test_minus_36_percent_passes(self) -> None:
        assert _run(fund=_fund(net_profit_growth=-36.51)) == {"600000"}

    def test_cliff_drop_minus_60_percent_is_rejected(self) -> None:
        assert _run(fund=_fund(net_profit_growth=-60.0)) == set()

    def test_boundary_minus_50_percent_passes(self) -> None:
        assert _run(fund=_fund(net_profit_growth=-50.0)) == {"600000"}


class TestGrossMargin:
    """毛利率检查修复前形同虚设（0.10 vs 百分数），现在必须真的拦。"""

    def test_low_margin_5_percent_is_rejected(self) -> None:
        assert _run(fund=_fund(gross_margin=5.0)) == set()

    def test_margin_10_18_percent_passes(self) -> None:
        assert _run(fund=_fund(gross_margin=10.18)) == {"600000"}


class TestRoe:
    def test_mild_loss_minus_3_percent_passes(self) -> None:
        assert _run(fund=_fund(roe=-3.0)) == {"600000"}

    def test_deep_loss_minus_6_percent_is_rejected(self) -> None:
        assert _run(fund=_fund(roe=-6.0)) == set()


class TestDebtRatio:
    def test_debt_79_passes(self) -> None:
        assert _run(fund=_fund(debt_ratio=79.77)) == {"600000"}

    def test_debt_90_is_rejected(self) -> None:
        assert _run(fund=_fund(debt_ratio=90.0)) == set()


class TestValuation:
    def test_pe_216_is_rejected(self) -> None:
        assert _run(fund=_fund(), val=_val(pe=216.21)) == set()

    def test_pe_30_passes(self) -> None:
        assert _run(fund=_fund(), val=_val(pe=30.0)) == {"600000"}


class TestLatestValueOrdering:
    """`_get_latest_value` 必须取「最新报告期」，不能依赖行序。"""

    def test_picks_latest_by_report_date_even_when_unsorted(self) -> None:
        frame = pl.DataFrame(
            {
                "report_date": ["2026-03-31", "2025-12-31"],
                "ROE": [1.02, 4.25],
            }
        )
        # 行序是新的在前，tail(1) 会拿到旧值 4.25；排序后应取 1.02
        assert _get_latest_value(frame, "ROE") == 1.02

    def test_returns_none_for_missing_field(self) -> None:
        frame = pl.DataFrame({"report_date": ["2026-03-31"], "ROE": [1.0]})
        assert _get_latest_value(frame, "net_profit_growth") is None


class TestPitUniverseUsesSameUnits:
    """PIT 路径与静态路径必须用同一套百分数阈值。"""

    def test_npg_minus_23_kept_in_pit_universe(self) -> None:
        universe = build_pit_universe(
            {"600000": _price()},
            {"600000": _fund(net_profit_growth=-23.0)},
            {"600000": _val()},
        )
        assert "600000" in universe["2026-10-28"]

    def test_npg_minus_60_excluded_in_pit_universe(self) -> None:
        universe = build_pit_universe(
            {"600000": _price()},
            {"600000": _fund(net_profit_growth=-60.0)},
            {"600000": _val()},
        )
        assert "600000" not in universe["2026-10-28"]
