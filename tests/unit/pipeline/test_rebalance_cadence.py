"""调仓节奏（cadence）解析与判定的单元测试。

覆盖：默认 monthly 零行为变更、参数优先级（approved > context > 默认）、
非法参数报错、N 交易日节奏的锚点与偏移计算、today 不在交易日序列时的行为。
"""

from __future__ import annotations

import pytest

from qp.pipeline.rebalance_cadence import (
    MODE_MONTHLY,
    MODE_TRADING_DAYS,
    CadenceSpec,
    is_trading_days_rebalance,
    load_trade_dates,
    resolve_cadence,
)


def _series(n: int) -> list[str]:
    """构造 n 个伪交易日（简单递增，仅用于索引计算）。"""
    return [f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}" for i in range(n)]


class TestResolveCadence:
    def test_default_is_monthly(self) -> None:
        spec = resolve_cadence({}, {})
        assert spec.mode == MODE_MONTHLY
        assert spec.source == "default"

    def test_approved_snapshot_wins_over_context(self) -> None:
        spec = resolve_cadence(
            {"rebalance_cadence": "trading_days", "rebalance_days": 40},
            {"rebalance_cadence": "monthly"},
        )
        assert spec.mode == MODE_TRADING_DAYS
        assert spec.days == 40
        assert spec.source == "approved"

    def test_context_used_when_approved_has_no_cadence(self) -> None:
        spec = resolve_cadence(
            {"top_n": 10},
            {"rebalance_cadence": "trading_days", "rebalance_days": 10},
        )
        assert spec.mode == MODE_TRADING_DAYS
        assert spec.days == 10
        assert spec.source == "context"

    def test_monthly_explicit(self) -> None:
        spec = resolve_cadence({"rebalance_cadence": "MONTHLY"}, {})
        assert spec.mode == MODE_MONTHLY
        assert spec.source == "approved"

    def test_unknown_mode_raises(self) -> None:
        with pytest.raises(ValueError, match="rebalance_cadence"):
            resolve_cadence({"rebalance_cadence": "weekly"}, {})

    def test_trading_days_requires_positive_days(self) -> None:
        with pytest.raises(ValueError, match="rebalance_days"):
            resolve_cadence({"rebalance_cadence": "trading_days"}, {})
        with pytest.raises(ValueError, match="rebalance_days"):
            resolve_cadence({"rebalance_cadence": "trading_days", "rebalance_days": 0}, {})

    def test_anchor_carried_through(self) -> None:
        spec = resolve_cadence(
            {
                "rebalance_cadence": "trading_days",
                "rebalance_days": 40,
                "rebalance_anchor": "2026-01-05",
            },
            {},
        )
        assert spec.anchor == "2026-01-05"


class TestTradingDaysRebalance:
    def test_every_n_days_from_dataset_start(self) -> None:
        dates = _series(90)
        spec = CadenceSpec(mode=MODE_TRADING_DAYS, days=40)
        assert is_trading_days_rebalance(dates[0], spec, dates)[0] is True
        assert is_trading_days_rebalance(dates[39], spec, dates)[0] is False
        assert is_trading_days_rebalance(dates[40], spec, dates)[0] is True
        assert is_trading_days_rebalance(dates[80], spec, dates)[0] is True
        assert is_trading_days_rebalance(dates[20], spec, dates)[0] is False

    def test_anchor_shifts_the_cycle(self) -> None:
        dates = _series(100)
        spec = CadenceSpec(mode=MODE_TRADING_DAYS, days=40, anchor=dates[5])
        assert is_trading_days_rebalance(dates[5], spec, dates)[0] is True
        assert is_trading_days_rebalance(dates[45], spec, dates)[0] is True
        assert is_trading_days_rebalance(dates[0], spec, dates)[0] is False

    def test_today_outside_series_is_not_rebalance(self) -> None:
        dates = _series(50)
        ok, reason = is_trading_days_rebalance(
            "2099-01-01", spec=CadenceSpec(MODE_TRADING_DAYS, 40), trade_dates=dates
        )
        assert ok is False
        assert "不在交易日序列" in reason

    def test_anchor_not_in_series_counts_trading_days(self) -> None:
        """锚点不必是交易日（例如节假日/未来日期），按「锚点后第几个交易日」计数。"""
        dates = _series(60)
        # 用一个不在序列里的过去日期作锚点：序列从 2025-12-25 开始之后…
        spec = CadenceSpec(mode=MODE_TRADING_DAYS, days=40, anchor="2025-12-31")
        ok, _ = is_trading_days_rebalance(dates[0], spec, dates)
        assert ok is True  # 首个 >= 锚点的交易日 = offset 0

    def test_future_anchor_reports_not_yet(self) -> None:
        dates = _series(30)
        spec = CadenceSpec(mode=MODE_TRADING_DAYS, days=40, anchor="2099-01-01")
        ok, reason = is_trading_days_rebalance(dates[0], spec, dates)
        assert ok is False
        assert "早于锚点" in reason

    def test_reason_reports_next_gap(self) -> None:
        dates = _series(90)
        spec = CadenceSpec(mode=MODE_TRADING_DAYS, days=40)
        ok, reason = is_trading_days_rebalance(dates[45], spec, dates)
        assert ok is False
        assert "next_gap=35" in reason

    def test_wrong_mode_raises(self) -> None:
        with pytest.raises(ValueError, match="trading_days"):
            is_trading_days_rebalance("2026-01-01", CadenceSpec(MODE_MONTHLY), ["2026-01-01"])


class TestLoadTradeDates:
    def test_reads_sorted_unique_dates(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        import polars as pl

        path = tmp_path / "prices.parquet"
        pl.DataFrame(
            {
                "trade_date": ["2026-01-03", "2026-01-05", "2026-01-03", "2026-01-04"],
                "close": [1.0, 1.0, 1.0, 1.0],
            }
        ).write_parquet(path)

        assert load_trade_dates(path) == ["2026-01-03", "2026-01-04", "2026-01-05"]

    def test_missing_file_raises(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        with pytest.raises(FileNotFoundError):
            load_trade_dates(tmp_path / "nope.parquet")
