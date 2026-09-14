"""PositionService — 持仓/账户的统一估值口径（成本 / 最新收盘 / 费用后）。

为什么要统一：同一批持仓在 WebUI 有四个展示点（老 UI dashboard、老 UI portfolio、
SPA 总览、SPA 持仓页），各自算一遍必然打架 —— 2026-09-14 前 SPA 用 positions.parquet
的 ``pnl``/``pnl_pct``（**已实现盈亏**，持仓中恒为 0），老 UI 用最新收盘
mark-to-market；账户又有成本市值（``index.json`` ``active_value``）与最新市值两套口径。
本模块是唯一实现，其余位置只消费（api_v1 / routers.dashboard / routers.portfolio / SPA）。

口径（全部显式命名；缺失即 ``None`` → 前端显示 ``—``，不回落为 0）：

- ``cost``: ``entry_price × shares``（建仓成本市值，与 ``PositionLedger.total_active_value``
  同值，即 ``index.json`` 的 ``active_value``）
- ``mark``: ``最新收盘 × shares``（``daily_price_latest.parquet`` 最后一个 ``trade_date``）
- ``fees``: ``qp.portfolio.cost_model.CostModel``（与回测 broker / 决策包同源）估算
  买入 = 佣金 + 滑点；卖出 = 佣金 + 印花税 + 滑点
- ``net`` : 毛盈亏 − 买入费 − 卖出费（费用后）

**未计**（局限，勿当精确值）：券商最低佣金（常见 ¥5/笔，小额单影响显著）、过户费、
真实成交滑点与市场冲击（impact 需 ADV，见 ``MarketImpactModel.compute_adv`` 的 volume 单位）。

Usage:
    svc = PositionService()
    rows = svc.enrich(ledger_rows)                 # 每行补 mark/fee/net 字段
    views = svc.account_views(cash=99504.0, rows=rows)
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import polars as pl
from loguru import logger

from qp.portfolio.cost_model import CostModel
from qp.shared.paths import DAILY_PRICE_LATEST

BUY = "BUY"
SELL = "SELL"


def mtime_ns(path: Any) -> int:
    """文件 mtime(ns)；不存在/不可读返回 0（作为缓存键：文件一变缓存自动失效）。"""
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0


@lru_cache(maxsize=4)
def _quotes_cached(path: str, mtime: int) -> dict[str, Any]:
    """最后交易日行情快照：``{quote_date, closes: {symbol: close}, suspended: {symbol: bool}}``。

    缓存键含 ``mtime`` —— 全表 700 万行，不缓存会拖慢页面；含 mtime 才能随数据更新自动失效。
    无文件/无数据 → 空 dict（调用方按 None 处理，**不当作 0**）。
    """
    empty: dict[str, Any] = {"quote_date": None, "closes": {}, "suspended": {}}
    if mtime <= 0:
        return empty
    try:
        px = pl.read_parquet(path)
    except Exception as exc:
        logger.warning("latest quotes unavailable ({}): {}", path, exc)
        return empty
    if px.is_empty():
        return empty
    latest = px["trade_date"].max()
    snapshot = (
        px.filter(pl.col("trade_date") == latest)
        .select(["symbol", "close", "is_suspended"])
        .unique(subset=["symbol"], keep="first")
    )
    closes: dict[str, float] = {}
    suspended: dict[str, bool] = {}
    for r in snapshot.iter_rows(named=True):
        if r["close"] is None:
            continue
        sym = str(r["symbol"])
        closes[sym] = float(r["close"])
        suspended[sym] = bool(r["is_suspended"])
    return {"quote_date": str(latest)[:10], "closes": closes, "suspended": suspended}


def clear_quote_cache() -> None:
    """清行情缓存（测试用；生产无需调用——mtime 变了自动失效）。"""
    _quotes_cached.cache_clear()


class PositionService:
    """持仓估值 + 账户视图（只读）。

    Usage:
        svc = PositionService()
        rows = svc.enrich(rows)
        views = svc.account_views(cash=10000.0, rows=srv.enrich(rows))
    """

    def __init__(
        self,
        quote_path: Any = DAILY_PRICE_LATEST,
        cost_model: CostModel | None = None,
    ) -> None:
        self._quote_path = quote_path
        self._cost_model = cost_model or CostModel()

    # ------------------------------------------------------------------
    # 行情 & 费率
    # ------------------------------------------------------------------

    def quotes(self) -> dict[str, Any]:
        """最后交易日行情快照（按文件 mtime 缓存）。"""
        return _quotes_cached(str(self._quote_path), mtime_ns(self._quote_path))

    def cost_rates(self) -> dict[str, Any]:
        """费率（元数据，供前端展示口径；来源 CostModel 默认值）。"""
        return {
            "commission_rate": self._cost_model.commission_rate,
            "stamp_tax_rate": self._cost_model.stamp_tax_rate,
            "stamp_tax_side": SELL,
            "slippage_bps": round(self._cost_model.slippage_rate * 10000, 4),
            "source": "qp/portfolio/cost_model.py",
            "excludes": "券商最低佣金/过户费/市场冲击",
        }

    def estimate_fees(self, trade_value: float, side: str) -> dict[str, float]:
        """单边费用估算（不含市场冲击：不传 daily_volume，与决策包 engine.py 同法）。"""
        if trade_value <= 0:
            return {"commission": 0.0, "stamp_tax": 0.0, "slippage": 0.0, "total": 0.0}
        c = self._cost_model.estimate_trade(symbol="", trade_value=trade_value, side=side)
        return {
            "commission": round(c.commission, 4),
            "stamp_tax": round(c.stamp_tax, 4),
            "slippage": round(c.slippage, 4),
            "total": round(c.total_cost, 4),
        }

    # ------------------------------------------------------------------
    # 单行持仓：补 mark / fee / net 字段（就地写回并返回）
    # ------------------------------------------------------------------

    def value_position(self, p: dict[str, Any]) -> dict[str, Any]:
        """给一行持仓补全估值字段。

        活跃行 → ``market_value_latest`` / ``unrealized_pnl(_pct)`` /
        ``unrealized_pnl_net(_pct)``；已平仓行 → ``realized_pnl_net(_pct)``
        （毛盈亏 ``pnl`` 保持 parquet 原值不动）。无行情时相关字段一律 ``None``。
        """
        quote = self.quotes()
        quote_date = quote["quote_date"]
        symbol = str(p.get("symbol", ""))
        close = quote["closes"].get(symbol)
        entry = float(p.get("entry_price") or 0.0)
        shares = float(p.get("shares") or 0)
        active = bool(p.get("is_active"))
        entry_value = entry * shares

        p["latest_price"] = close
        p["latest_suspended"] = quote["suspended"].get(symbol) if close is not None else None
        p["quote_date"] = quote_date if close is not None else None
        p["est_buy_fee"] = (
            round(self.estimate_fees(entry_value, BUY)["total"], 2) if entry_value > 0 else None
        )

        if active:
            self._value_active(p, close, entry, entry_value, shares)
        else:
            self._value_closed(p, entry_value, shares)
        return p

    def _value_active(
        self,
        p: dict[str, Any],
        close: float | None,
        entry: float,
        entry_value: float,
        shares: float,
    ) -> None:
        buy_fee = p.get("est_buy_fee") or 0.0
        p["market_value_latest"] = None
        p["est_sell_fee"] = None
        p["est_round_trip_fee"] = None
        p["unrealized_pnl"] = None
        p["unrealized_pnl_pct"] = None
        p["unrealized_pnl_net"] = None
        p["unrealized_pnl_net_pct"] = None
        if close is None:
            return

        mark_value = round(close * shares, 2)
        p["market_value_latest"] = mark_value
        gross = round((close - entry) * shares, 2)
        p["unrealized_pnl"] = gross if entry > 0 else None
        p["unrealized_pnl_pct"] = round((close - entry) / entry, 6) if entry > 0 else None

        sell_fee = round(self.estimate_fees(mark_value, SELL)["total"], 2)
        p["est_sell_fee"] = sell_fee
        if p.get("est_buy_fee") is not None:
            p["est_round_trip_fee"] = round(buy_fee + sell_fee, 2)
        if entry > 0:
            net = round(gross - buy_fee - sell_fee, 2)
            cost_basis = entry_value + buy_fee
            p["unrealized_pnl_net"] = net
            p["unrealized_pnl_net_pct"] = round(net / cost_basis, 6) if cost_basis > 0 else None

    def _value_closed(self, p: dict[str, Any], entry_value: float, shares: float) -> None:
        buy_fee = p.get("est_buy_fee") or 0.0
        exit_price = float(p.get("exit_price") or 0.0)
        exit_value = exit_price * shares
        p["market_value_latest"] = None
        p["unrealized_pnl"] = None
        p["unrealized_pnl_pct"] = None
        p["unrealized_pnl_net"] = None
        p["unrealized_pnl_net_pct"] = None
        p["realized_pnl_net"] = None
        p["realized_pnl_net_pct"] = None
        p["est_sell_fee"] = (
            round(self.estimate_fees(exit_value, SELL)["total"], 2) if exit_value > 0 else None
        )
        p["est_round_trip_fee"] = (
            round(buy_fee + (p["est_sell_fee"] or 0.0), 2)
            if p.get("est_buy_fee") is not None
            else None
        )
        if exit_value > 0 and entry_value > 0:
            gross = float(p.get("pnl") or 0.0)
            net = round(gross - buy_fee - (p["est_sell_fee"] or 0.0), 2)
            cost_basis = entry_value + buy_fee
            p["realized_pnl_net"] = net
            p["realized_pnl_net_pct"] = round(net / cost_basis, 6) if cost_basis > 0 else None

    def enrich(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """批量补全（就地修改并返回同一列表）。"""
        return [self.value_position(r) for r in rows]

    # ------------------------------------------------------------------
    # 账户视图：成本口径 vs 最新收盘口径 vs 费用后
    # ------------------------------------------------------------------

    def account_views(self, cash: float, rows: list[dict[str, Any]]) -> dict[str, Any]:
        """账户三口径（不用 ``index.json`` 的旧汇总，按行重算，避免两处口径漂移）。

        Args:
            cash: 账户可用现金（``account.json`` 的 ``cash``，ADR-032 真值）。
            rows: 已 ``enrich`` 过的持仓行（含已平仓）。
        """
        active = [r for r in rows if r.get("is_active")]
        closed = [r for r in rows if not r.get("is_active")]

        cost_value = round(
            sum(float(r.get("entry_price") or 0) * float(r.get("shares") or 0) for r in active), 2
        )
        fallback = [str(r.get("symbol")) for r in active if r.get("market_value_latest") is None]
        mark_value = round(
            sum(
                float(r["market_value_latest"])
                if r.get("market_value_latest") is not None
                else float(r.get("entry_price") or 0) * float(r.get("shares") or 0)
                for r in active
            ),
            2,
        )
        gross_unreal = round(
            sum(float(r["unrealized_pnl"]) for r in active if r.get("unrealized_pnl") is not None),
            2,
        )
        net_unreal = round(
            sum(
                float(r["unrealized_pnl_net"])
                for r in active
                if r.get("unrealized_pnl_net") is not None
            ),
            2,
        )
        fees_unreal = round(
            sum(
                float(r["est_round_trip_fee"])
                for r in active
                if r.get("est_round_trip_fee") is not None
            ),
            2,
        )
        cost_basis = round(
            cost_value
            + sum(float(r["est_buy_fee"]) for r in active if r.get("est_buy_fee") is not None),
            2,
        )
        realized_gross = round(sum(float(r.get("pnl") or 0.0) for r in closed), 2)
        realized_net = round(
            sum(
                float(r["realized_pnl_net"])
                for r in closed
                if r.get("realized_pnl_net") is not None
            ),
            2,
        )

        return {
            "quote_date": self.quotes()["quote_date"],
            "cost": {
                "positions_value": cost_value,
                "total_equity": round(cash + cost_value, 2),
                "basis": "entry_price × shares",
                "note": "与 PositionLedger.total_active_value / index.json.active_value 同值",
            },
            "mark": {
                "positions_value": mark_value,
                "total_equity": round(cash + mark_value, 2),
                "basis": "最新收盘 × shares",
                "unrealized_pnl": gross_unreal,
                "unrealized_pnl_net": net_unreal,
                "unrealized_pnl_pct": round(gross_unreal / cost_value, 6)
                if cost_value > 0
                else None,
                "unrealized_pnl_net_pct": round(net_unreal / cost_basis, 6)
                if cost_basis > 0
                else None,
                "est_round_trip_fee": fees_unreal,
                "n_active": len(active),
                "n_fallback_cost": len(fallback),
                "fallback_symbols": fallback,
            },
            "realized": {
                "gross": realized_gross,
                "net": realized_net,
                "n_closed": len(closed),
            },
            "fees": self.cost_rates(),
        }
