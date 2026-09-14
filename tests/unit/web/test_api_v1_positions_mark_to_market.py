"""Regression: `/api/v1/positions` 必须给持仓行最新收盘标记值。

背景（2026-09-14 修复）：SPA 持仓页 / 总览页的活跃行曾绑定 `positions.parquet` 的
`pnl` / `pnl_pct`，而这两个字段是**已实现盈亏**（`Position.realized_pnl` 仅 CLOSED 时非零，
`pnl_pct` 仅 `close()` 赋值）→ 持仓行恒显示 0.00 / 0.00%，把默认值当成了测量值。

这些测试锁住新契约：
- 活跃行 → 由最新收盘价算出 latest_price / market_value_latest / unrealized_pnl(_pct)
- 无行情 → 标记字段一律 None（不得回落为 0）
- 已平仓行 → unrealized_* 为 None，盈亏仍以 parquet 的已实现值为准
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from qp.web.routers import api_v1


def _pos(
    position_id: str,
    symbol: str,
    entry_price: float,
    shares: int,
    *,
    is_active: bool = True,
    entry_date: str = "2026-09-02",
    exit_price: float = 0.0,
    pnl: float = 0.0,
    pnl_pct: float = 0.0,
) -> dict:
    """一条持仓记录（列集合与 Position.to_dict() 一致）。"""
    return {
        "position_id": position_id,
        "symbol": symbol,
        "entry_date": entry_date,
        "entry_price": entry_price,
        "shares": shares,
        "strategy_id": "s1",
        "decision_id": "dp-1",
        "status": 4 if is_active else 5,
        "status_name": "HOLDING" if is_active else "CLOSED",
        "exit_date": "" if is_active else "2026-08-20",
        "exit_price": exit_price,
        "exit_reason": "" if is_active else "rank_drop",
        "pnl": pnl,
        "pnl_pct": pnl_pct,
        "notes": "",
        "is_active": is_active,
        "market_value": entry_price * shares,
    }


def _write(path, rows: list[dict]) -> None:
    pl.DataFrame(rows).write_parquet(str(path))


@pytest.fixture()
def isolated(tmp_path, monkeypatch):
    """POSITIONS_DIR / DAILY_PRICE_LATEST 指向 tmp，并清掉行情缓存。"""
    pos_dir = tmp_path / "positions"
    pos_dir.mkdir()
    _write(
        pos_dir / "positions.parquet",
        [
            _pos("P-00001", "600207", 4.5, 100),
            _pos("P-00002", "600930", 3.89, 100),
            _pos(
                "P-00003",
                "000001",
                10.0,
                200,
                is_active=False,
                exit_price=11.0,
                pnl=200.0,
                pnl_pct=0.1,
            ),
        ],
    )
    px_path = tmp_path / "daily_price_latest.parquet"
    # 最新交易日 2026-09-14：600207 有行情（未停牌）；600930 停牌；000001 只有旧价（应被排除）
    pl.DataFrame(
        {
            "symbol": ["600207", "600930", "000001", "600207"],
            "trade_date": [
                date(2026, 9, 14),
                date(2026, 9, 14),
                date(2026, 9, 11),
                date(2026, 9, 11),
            ],
            "close": [4.9, 3.94, 11.0, 4.7],
            "is_suspended": [False, True, False, False],
        }
    ).write_parquet(str(px_path))
    monkeypatch.setattr(api_v1, "POSITIONS_DIR", pos_dir)
    monkeypatch.setattr(api_v1, "DAILY_PRICE_LATEST", px_path)
    api_v1._latest_quotes_cached.cache_clear()
    return api_v1.positions(active_only=False)


def test_active_row_marked_from_latest_close(isolated):
    """活跃行：按最新收盘价标记，parquet 的已实现 pnl=0 保持不变。"""
    p = next(r for r in isolated["positions"] if r["position_id"] == "P-00001")
    assert isolated["quote_date"] == "2026-09-14"
    assert p["latest_price"] == 4.9  # 09-14 收盘，非 09-11 的 4.7
    assert p["quote_date"] == "2026-09-14"
    assert p["market_value_latest"] == 490.0
    assert p["unrealized_pnl"] == 40.0
    assert p["unrealized_pnl_pct"] == pytest.approx(0.088889, abs=1e-6)
    # 记录时点字段不被覆盖：已实现盈亏仍是 0（语义不同，不可互相冒充）
    assert p["pnl"] == 0.0
    assert p["market_value"] == 450.0


def test_suspended_symbol_uses_last_close_with_flag(isolated):
    """停牌股沿用最后收盘价，但带 latest_suspended=True（不伪装成实时）。"""
    p = next(r for r in isolated["positions"] if r["position_id"] == "P-00002")
    assert p["latest_price"] == 3.94
    assert p["latest_suspended"] is True
    assert p["unrealized_pnl"] == 5.0


def test_missing_quote_is_none_not_zero(tmp_path, isolated):
    """无行情的活跃股：标记字段全 None（前端显示 —），绝不回落为 0。"""
    _write(
        api_v1.POSITIONS_DIR / "positions.parquet",
        [_pos("P-00009", "600519", 1500.0, 100, entry_date="2026-09-01")],
    )
    rows = api_v1.positions(active_only=True)["positions"]
    assert len(rows) == 1
    p = rows[0]
    assert p["latest_price"] is None
    assert p["market_value_latest"] is None
    assert p["unrealized_pnl"] is None
    assert p["unrealized_pnl_pct"] is None
    assert p["quote_date"] is None
    assert p["market_value"] == 150000.0  # 成本市值仍可读


def test_closed_row_keeps_realized_pnl(isolated):
    """已平仓行：unrealized_* 为 None，盈亏以已实现值（parquet）为准。"""
    p = next(r for r in isolated["positions"] if r["position_id"] == "P-00003")
    assert p["is_active"] is False
    assert p["unrealized_pnl"] is None
    assert p["unrealized_pnl_pct"] is None
    assert p["market_value_latest"] is None
    assert p["pnl"] == 200.0
    assert p["pnl_pct"] == 0.1


def test_active_only_filter(tmp_path, isolated):
    out = api_v1.positions(active_only=True)
    assert {r["position_id"] for r in out["positions"]} == {"P-00001", "P-00002"}


def test_missing_positions_file_reports_error(tmp_path, monkeypatch):
    monkeypatch.setattr(api_v1, "POSITIONS_DIR", tmp_path / "empty")
    monkeypatch.setattr(api_v1, "DAILY_PRICE_LATEST", tmp_path / "none.parquet")
    out = api_v1.positions(active_only=False)
    assert out["positions"] == []
    assert "error" in out
