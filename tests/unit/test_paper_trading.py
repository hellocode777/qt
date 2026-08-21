"""Tests for Paper Trading: 30-day evaluation metrics + /paper WebUI.

Covers:
  - Max drawdown formula regression (relative-to-peak, not initial capital)
  - /paper dashboard: empty state, 0-day run (N/A gates, no fake zeros),
    in-progress run, completed run verdict
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from qp.simulation.paper_trading import (
    DailyRecord,
    PaperTradingResult,
    PaperTradingRun,
    PaperTradingTracker,
)


def _run_with_returns(returns: list[float], n_signals: int = 5) -> PaperTradingRun:
    """Build a run whose daily records encode the given daily returns."""
    equity = 100_000.0
    records: list[DailyRecord] = []
    for i, r in enumerate(returns):
        equity *= 1 + r
        records.append(
            DailyRecord(
                date=f"2026-08-{i + 1:02d}",
                equity=round(equity, 2),
                cash=0.0,
                n_positions=3,
                n_signals=n_signals,
                n_trades=1,
                daily_return=r,
                total_cost=0.0,
            )
        )
    return PaperTradingRun(
        run_id="pt-test",
        strategy_id="test_strat",
        capital=100_000.0,
        start_date="2026-08-01",
        daily_records=records,
    )


class TestMaxDrawdownFormula:
    """Max DD must be measured relative to the running peak, not initial capital."""

    def test_drawdown_relative_to_peak(self) -> None:
        # +20% then back to start: drawdown is 16.67% of the 1.2 peak,
        # NOT 20% of initial capital (old formula bug).
        run = _run_with_returns([0.20, 100_000.0 / 120_000.0 - 1])
        result = PaperTradingTracker().evaluate(run)
        assert result.max_drawdown_pct == pytest.approx(16.6667, abs=0.01)

    def test_no_drawdown_when_monotonic_up(self) -> None:
        run = _run_with_returns([0.05, 0.05, 0.05])
        result = PaperTradingTracker().evaluate(run)
        assert result.max_drawdown_pct == 0.0

    def test_drawdown_after_recovery_counts_from_peak(self) -> None:
        # 1.0 -> 0.9 -> 1.2 -> 1.0: peak is 1.2, trough vs peak = 16.67%
        run = _run_with_returns([-0.10, 1.2 / 0.9 - 1, 1.0 / 1.2 - 1])
        result = PaperTradingTracker().evaluate(run)
        assert result.max_drawdown_pct == pytest.approx(16.6667, abs=0.01)


@pytest.fixture
def paper_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[TestClient, PaperTradingTracker]:
    """Client for /paper with tracker redirected to a temp dir.

    Patch the SOURCE module (qp.simulation.paper_trading.PaperTradingTracker),
    not the router module attribute — the router imports it inside the
    request handler, so patching qp.web.routers.paper.PaperTradingTracker
    would be a no-op (see paper-trading-ops.md mock pitfall).
    """
    tracker = PaperTradingTracker(data_dir=str(tmp_path))
    monkeypatch.setattr(
        "qp.simulation.paper_trading.PaperTradingTracker",
        lambda: tracker,
    )
    from qp.web.app import create_app

    client = TestClient(create_app())
    return client, tracker


class TestPaperWeb:
    def test_empty_state(self, paper_client: tuple[TestClient, PaperTradingTracker]) -> None:
        client, _ = paper_client
        resp = client.get("/paper")
        assert resp.status_code == 200
        assert "暂无模拟交易运行" in resp.text
        assert "qp paper start" in resp.text

    def test_zero_day_run_shows_na_not_fake_zeros(
        self, paper_client: tuple[TestClient, PaperTradingTracker]
    ) -> None:
        # User rule: 0-day runs must show N/A + "未计算", never 0.00/未达标
        client, tracker = paper_client
        run = tracker.start("momentum_test")
        tracker._save(run)

        resp = client.get("/paper")
        assert resp.status_code == 200
        assert "momentum_test" in resp.text
        assert "0/30" in resp.text
        assert "N/A" in resp.text
        assert "未计算" in resp.text
        assert "未达标" not in resp.text  # no fake gate failures without data

    def test_in_progress_run_shows_live_metrics(
        self, paper_client: tuple[TestClient, PaperTradingTracker]
    ) -> None:
        client, tracker = paper_client
        run = _run_with_returns([0.20, 100_000.0 / 120_000.0 - 1], n_signals=6)
        run.strategy_id = "momentum_test"
        run.run_id = "pt-live01"
        tracker._save(run)

        resp = client.get("/paper")
        assert resp.status_code == 200
        assert "2/30" in resp.text
        assert "进行中" in resp.text
        # MaxDD now 16.7% (relative to peak), NOT 20% (initial capital)
        assert "16.7%" in resp.text
        assert "20.0%" not in resp.text
        # Equity curve JSON data block for this run
        assert 'id="paper-data-pt-live01"' in resp.text
        assert '"date": "2026-08-01"' in resp.text

    def test_completed_run_shows_final_verdict(
        self, paper_client: tuple[TestClient, PaperTradingTracker]
    ) -> None:
        client, tracker = paper_client
        run = _run_with_returns([0.02, 0.02, 0.02])
        run.strategy_id = "momentum_test"
        run.run_id = "pt-done01"
        run.result = PaperTradingResult(
            elapsed_days=30,
            total_return_pct=6.12,
            sharpe_ratio=1.8,
            max_drawdown_pct=3.0,
            passed=True,
            recommendation="PASS: Paper trading successful.",
        )
        tracker._save(run)

        resp = client.get("/paper")
        assert resp.status_code == 200
        assert "✅ 通过" in resp.text
        assert "PASS: Paper trading successful." in resp.text
        assert "最终" in resp.text
        assert "1.80" in resp.text  # final Sharpe from run.result
