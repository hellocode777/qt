"""`_should_generate_buys` / `_has_active_positions` 的行为测试。

2026-11 实况：生产策略 lvr_vol_only 的 cadence 锚点是 2026-10-29，那天正好
被 bear 门禁拦掉；而 BUY 只在调仓日生成 ⇒ 空仓 + 非调仓日 = 永远不买，
首次建仓被推到 40 个交易日之后（12-24），且到点若仍是 bear 会继续空转。

修复口径：**空仓时首次建仓不受 cadence 约束**；已有持仓仍只在调仓日加仓/换仓。
Quality Gate（bear/crisis）不受影响——它依旧独立拦截。
"""

from __future__ import annotations

import polars as pl
import pytest

from qp.pipeline import daily_pipeline as dp
from qp.shared.types import PositionState


class TestShouldGenerateBuys:
    def test_flat_book_allows_buys_off_cadence(self) -> None:
        """非调仓日 + 空仓 → 允许 BUY（本次修复的核心行为）。"""
        assert dp._should_generate_buys(is_rebalance_day=False, has_active_positions=False) is True

    def test_holding_book_blocked_off_cadence(self) -> None:
        """非调仓日 + 有持仓 → 不买（保持原行为，避免变成每天乱加仓）。"""
        assert dp._should_generate_buys(is_rebalance_day=False, has_active_positions=True) is False

    @pytest.mark.parametrize("has_active", [True, False])
    def test_rebalance_day_always_allows(self, has_active: bool) -> None:
        assert (
            dp._should_generate_buys(is_rebalance_day=True, has_active_positions=has_active) is True
        )


class TestHasActivePositions:
    def _write(self, path, statuses: list[int]):
        pl.DataFrame({"status": statuses}).write_parquet(path)
        return path

    def _patch(self, monkeypatch: pytest.MonkeyPatch, path) -> None:
        from qp.decision import position_ledger as ledger_mod

        monkeypatch.setattr(ledger_mod, "POSITIONS_PARQUET", path)

    def test_missing_file_is_flat(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        self._patch(monkeypatch, tmp_path / "absent.parquet")
        assert dp._has_active_positions() is False

    def test_holding_detected(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        path = self._write(
            tmp_path / "pos.parquet",
            [PositionState.HOLDING.value, PositionState.CLOSED.value],
        )
        self._patch(monkeypatch, path)
        assert dp._has_active_positions() is True

    def test_reducing_counts_as_active(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        path = self._write(tmp_path / "pos.parquet", [PositionState.REDUCING.value])
        self._patch(monkeypatch, path)
        assert dp._has_active_positions() is True

    def test_all_closed_is_flat(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        path = self._write(
            tmp_path / "pos.parquet",
            [PositionState.CLOSED.value, PositionState.CLOSED.value],
        )
        self._patch(monkeypatch, path)
        assert dp._has_active_positions() is False

    def test_empty_frame_is_flat(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        path = self._write(tmp_path / "pos.parquet", [])
        self._patch(monkeypatch, path)
        assert dp._has_active_positions() is False

    def test_read_failure_falls_back_to_holding(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        """读盘异常 → 按有持仓处理，退回旧调仓日判定（宁可少买，不可乱买）。"""
        bad = tmp_path / "bad.parquet"
        bad.write_text("not a parquet file", encoding="utf-8")
        self._patch(monkeypatch, bad)
        assert dp._has_active_positions() is True
