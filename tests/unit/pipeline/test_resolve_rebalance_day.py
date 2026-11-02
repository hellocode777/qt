"""`daily_pipeline._resolve_rebalance_day` 的行为测试。

这是生产调仓日的唯一决策入口（2026-10-28 抽出），必须锁住：
- 默认 monthly（未配置 cadence）；
- approved 快照的 cadence 优先级最高；
- context 参数在快照没写时生效；
- force_rebalance 恒为 True；
- trading_days 数据不可用时优雅退回 monthly，不抛异常。
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest

from qp.pipeline import daily_pipeline as dp

TODAY = date(2026, 10, 29)
DATES = [f"2026-{m:02d}-{d:02d}" for m in (9, 10) for d in range(1, 31)]


class _FakeLog:
    def __init__(self) -> None:
        self.records: list[str] = []

    def info(self, msg: str, *args: Any) -> None:
        self.records.append(msg.format(*args))

    def warning(self, msg: str, *args: Any) -> None:
        self.records.append(msg.format(*args))

    def error(self, msg: str, *args: Any) -> None:
        self.records.append(msg.format(*args))

    def debug(self, msg: str, *args: Any) -> None:
        self.records.append(msg.format(*args))


def _patch_snapshots(monkeypatch: pytest.MonkeyPatch, parameters: dict[str, Any] | None) -> None:
    from qp.strategy.registry import StrategyRegistry

    snapshots = (
        [] if parameters is None else [SimpleNamespace(parameters=parameters, strategy_id="x")]
    )
    monkeypatch.setattr(StrategyRegistry, "load_active", lambda self: snapshots)


def _patch_trade_dates(monkeypatch: pytest.MonkeyPatch, dates: list[str]) -> None:
    from qp.pipeline import rebalance_cadence

    monkeypatch.setattr(rebalance_cadence, "load_trade_dates", lambda path: dates)


class TestResolveRebalanceDay:
    def test_approved_cadence_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_snapshots(
            monkeypatch,
            {
                "rebalance_cadence": "trading_days",
                "rebalance_days": 40,
                "rebalance_anchor": "2026-09-01",
            },
        )
        _patch_trade_dates(monkeypatch, DATES)

        _ok, rule = dp._resolve_rebalance_day(
            today=TODAY, force_rebalance=False, context_parameters={}, log=_FakeLog()
        )
        assert rule is not None and "trading_days=40" in rule
        assert "anchor=2026-09-01" in rule

    def test_context_used_when_snapshot_has_no_cadence(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_snapshots(monkeypatch, {"top_n": 10})
        _patch_trade_dates(monkeypatch, DATES)

        _ok, rule = dp._resolve_rebalance_day(
            today=TODAY,
            force_rebalance=False,
            context_parameters={"rebalance_cadence": "trading_days", "rebalance_days": 10},
            log=_FakeLog(),
        )
        assert rule is not None and "trading_days=10" in rule

    def test_force_rebalance_always_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_snapshots(monkeypatch, {"rebalance_cadence": "trading_days", "rebalance_days": 40})
        _patch_trade_dates(monkeypatch, DATES)

        ok, rule = dp._resolve_rebalance_day(
            today=TODAY, force_rebalance=True, context_parameters={}, log=_FakeLog()
        )
        assert ok is True
        assert rule is not None and "forced" in rule

    def test_monthly_default_without_akshare_calendar(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """未配置 cadence → monthly；日历不可用时退回 day<=5（29 号 → 不调仓）。"""
        _patch_snapshots(monkeypatch, None)

        import qp.data.calendar.calendar as cal_mod

        class _NoRealCalendar:
            has_real_calendar = False

            def __init__(self, *a: Any, **k: Any) -> None: ...

            def first_trading_day_of_month(self, year: int, month: int) -> date:
                return date(year, month, 1)

            def is_first_trading_day_of_month(self, d: date) -> bool:
                return d.day == 1

        monkeypatch.setattr(cal_mod, "TradingCalendar", _NoRealCalendar)

        ok, _rule = dp._resolve_rebalance_day(
            today=TODAY, force_rebalance=False, context_parameters={}, log=_FakeLog()
        )
        assert ok is False  # 29 号不是月初，day<=5 近似也不成立

    def test_trading_days_data_failure_falls_back(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """交易日序列读取失败 → 退回 monthly 判定，不抛异常。"""
        _patch_snapshots(
            monkeypatch,
            {"rebalance_cadence": "trading_days", "rebalance_days": 40},
        )

        from qp.pipeline import rebalance_cadence

        def _boom(path: str) -> list[str]:
            raise FileNotFoundError("no data")

        monkeypatch.setattr(rebalance_cadence, "load_trade_dates", _boom)

        ok, _rule = dp._resolve_rebalance_day(
            today=TODAY, force_rebalance=False, context_parameters={}, log=_FakeLog()
        )
        assert ok is False  # 退回 monthly 后 29 号不调仓


class TestDynamicAnchorWiring:
    """2026-11：调仓日撞上 Quality Gate 被拦后，超期即补做（动态锚点接线）。"""

    def _patch_last_executed(self, monkeypatch, value):
        from qp.pipeline import rebalance_cadence

        monkeypatch.setattr(rebalance_cadence, "load_last_executed", lambda sid="": value)

    def test_overdue_anchor_overrides_calendar(self, monkeypatch) -> None:
        """日历上今天不是调仓日，但距上次实际调仓已超 40 个交易日 → 应当调仓。"""
        _patch_snapshots(
            monkeypatch,
            {
                "rebalance_cadence": "trading_days",
                "rebalance_days": 40,
                "rebalance_anchor": "2026-09-01",
            },
        )
        _patch_trade_dates(monkeypatch, DATES)

        # 先证明日历语义下今天不调仓
        calendar_ok, _ = dp._resolve_rebalance_day(
            today=TODAY, force_rebalance=False, context_parameters={}, log=_FakeLog()
        )
        assert calendar_ok is False

        # 动态锚点：上次实际调仓 2026-09-01，已远超 40 个交易日
        self._patch_last_executed(monkeypatch, "2026-09-01")
        overdue_ok, rule = dp._resolve_rebalance_day(
            today=TODAY, force_rebalance=False, context_parameters={}, log=_FakeLog()
        )
        assert overdue_ok is True
        assert rule is not None and "last_executed=2026-09-01" in rule

    def test_within_window_stays_false(self, monkeypatch) -> None:
        """刚调过仓（3 天前）→ 即使日历判定为调仓日也不该重复调。"""
        _patch_snapshots(
            monkeypatch,
            {
                "rebalance_cadence": "trading_days",
                "rebalance_days": 40,
                "rebalance_anchor": "2026-09-01",
            },
        )
        _patch_trade_dates(monkeypatch, DATES)
        self._patch_last_executed(monkeypatch, "2026-10-26")

        ok, _rule = dp._resolve_rebalance_day(
            today=TODAY, force_rebalance=False, context_parameters={}, log=_FakeLog()
        )
        assert ok is False

    def test_no_state_falls_back_to_calendar(self, monkeypatch) -> None:
        """没有状态文件 → 走旧的日历语义，行为不变。"""
        _patch_snapshots(
            monkeypatch,
            {
                "rebalance_cadence": "trading_days",
                "rebalance_days": 40,
                "rebalance_anchor": "2026-09-01",
            },
        )
        _patch_trade_dates(monkeypatch, DATES)
        self._patch_last_executed(monkeypatch, None)

        ok, _rule = dp._resolve_rebalance_day(
            today=TODAY, force_rebalance=False, context_parameters={}, log=_FakeLog()
        )
        assert ok is False
