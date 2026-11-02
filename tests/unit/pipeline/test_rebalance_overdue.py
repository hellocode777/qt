"""动态调仓锚点（`is_overdue_rebalance` + 状态读写）的行为测试。

2026-11 要解决的问题：调仓日撞上 Quality Gate 被拦 → 按旧语义
（`offset % days == 0`）要整整错后 40 个交易日才能再调，持仓的
换仓 / 排名退出被无限期压住。

新语义：以「上次**实际执行**调仓的日期」为锚，`offset >= days` 即到期，
被拦之后的下一个放行日就能补做。
"""

from __future__ import annotations

import polars as pl
import pytest

from qp.pipeline import rebalance_cadence as rc

# 2026-11-03 起连续 60 个工作日，足够覆盖 40 交易日窗口
DATES = [
    str(d)
    for d in pl.date_range(
        start=pl.date(2026, 10, 29), end=pl.date(2027, 1, 29), interval="1d", eager=True
    ).to_list()
    if d.weekday() < 5
]
SPEC = rc.CadenceSpec(mode="trading_days", days=40, anchor="2026-10-29", source="approved")


class TestIsOverdueRebalance:
    def test_not_due_before_window(self) -> None:
        due, reason = rc.is_overdue_rebalance("2026-11-02", SPEC, DATES, "2026-10-29")
        assert due is False
        assert "offset_since_last=2" in reason

    def test_due_exactly_at_window(self) -> None:
        # 从 10-29 起第 41 个交易日（offset=40）
        idx = DATES.index("2026-10-29") + 40
        due, reason = rc.is_overdue_rebalance(DATES[idx], SPEC, DATES, "2026-10-29")
        assert due is True
        assert "due=True" in reason

    def test_overdue_after_missed_window(self) -> None:
        """核心场景：调仓日被 gate 拦掉，第二天放行即可补做。"""
        idx = DATES.index("2026-10-29") + 40
        missed, later = DATES[idx], DATES[idx + 1]
        assert rc.is_overdue_rebalance(missed, SPEC, DATES, "2026-10-29")[0] is True
        due, reason = rc.is_overdue_rebalance(later, SPEC, DATES, "2026-10-29")
        assert due is True, "错过的窗口必须能在下一个放行日补做"
        assert "offset_since_last=41" in reason

    def test_same_day_does_not_retrigger(self) -> None:
        """刚执行完当天再跑一次，不该重复调仓。"""
        due, _ = rc.is_overdue_rebalance("2026-12-24", SPEC, DATES, "2026-12-24")
        assert due is False

    def test_unknown_last_executed_falls_back(self) -> None:
        """状态里的日期不在交易日序列 → 不判到期，交给调用方回退日历语义。"""
        due, reason = rc.is_overdue_rebalance("2026-12-24", SPEC, DATES, "2019-01-01")
        assert due is False
        assert "不在交易日序列" in reason

    def test_today_not_in_series(self) -> None:
        due, reason = rc.is_overdue_rebalance("2026-12-26", SPEC, DATES, "2026-10-29")
        assert due is False
        assert "不在交易日序列" in reason

    def test_wrong_mode_raises(self) -> None:
        monthly = rc.CadenceSpec(mode="monthly")
        with pytest.raises(ValueError):
            rc.is_overdue_rebalance("2026-12-24", monthly, DATES, "2026-10-29")


class TestStateIo:
    def _patch_path(self, monkeypatch: pytest.MonkeyPatch, path) -> None:
        from qp.shared import paths

        monkeypatch.setattr(paths, "REBALANCE_STATE_FILE", path)

    def test_roundtrip(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        self._patch_path(monkeypatch, tmp_path / "state" / "rebalance_state.json")
        assert rc.load_last_executed("lvr_vol_only") is None
        rc.record_rebalance_executed("2026-12-24", strategy_id="lvr_vol_only", days=40, reason="t")
        assert rc.load_last_executed("lvr_vol_only") == "2026-12-24"

    def test_strategy_mismatch_ignores_state(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        """换策略后旧锚点作废（不同策略有自己的节奏）。"""
        self._patch_path(monkeypatch, tmp_path / "rebalance_state.json")
        rc.record_rebalance_executed("2026-12-24", strategy_id="old_strategy", days=40)
        assert rc.load_last_executed("lvr_vol_only") is None
        assert rc.load_last_executed("old_strategy") == "2026-12-24"

    def test_corrupt_state_returns_none(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        p = tmp_path / "bad.json"
        p.write_text("{not json", encoding="utf-8")
        self._patch_path(monkeypatch, p)
        assert rc.load_last_executed("lvr_vol_only") is None

    def test_non_dict_state_returns_none(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        p = tmp_path / "list.json"
        p.write_text("[1, 2, 3]", encoding="utf-8")
        self._patch_path(monkeypatch, p)
        assert rc.load_last_executed("lvr_vol_only") is None


class TestShouldRecordRebalance:
    """记录锚点的判据是「真的产生调仓动作」，不是 is_rebalance_day。

    关键场景：空仓首次建仓可能发生在非调仓日（_should_generate_buys 的修复），
    那次建仓同样确立下一次调仓的起算点，必须记录。
    """

    def test_orders_are_recorded(self) -> None:
        from qp.pipeline.daily_pipeline import _should_record_rebalance

        assert _should_record_rebalance(3, 0) is True

    def test_sells_are_recorded(self) -> None:
        from qp.pipeline.daily_pipeline import _should_record_rebalance

        assert _should_record_rebalance(0, 2) is True

    def test_empty_rebalance_day_not_recorded(self) -> None:
        """调仓日但没候选也没卖出 → 不消耗窗口。"""
        from qp.pipeline.daily_pipeline import _should_record_rebalance

        assert _should_record_rebalance(0, 0) is False
