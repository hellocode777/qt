"""回放对比：同一批决策包，bug 口径 vs 修复口径，看 3 个月收益差。

只读历史数据，不触碰生产状态。口径：
- 两边都用**包里的 alloc_capital**（report.total_capital，已含 regime 敞口）
- 只改 allocator 内部两个常量：max_weight_limit 与 standard_position_weight
- BUY 股数用 allocator 重算（整手），SELL 沿用包内指令与价格
- 建仓/平仓价用包内 estimated_price，mark-to-market 用当日 close
"""

from __future__ import annotations

import glob
import json

import pandas as pd
import polars as pl

from qp.portfolio.capital_allocator import CapitalAllocator, CapitalAllocatorConfig
from qp.portfolio.cash.reserve_policy import ReservePolicy

START, END, INIT = "2026-08-16", "2026-11-06", 100_000.0


def load_prices() -> tuple[dict[tuple[str, str], float], list[str]]:
    px = (
        pl.read_parquet("data/dataset/daily_price_latest.parquet")
        .select(["trade_date", "symbol", "close"])
        .drop_nulls()
    )
    m = {
        (str(r["trade_date"]), str(r["symbol"])): float(r["close"])
        for r in px.iter_rows(named=True)
    }
    dates = sorted({d for d, _ in m if START <= d <= END})
    return m, dates


def load_packs() -> dict[str, dict]:
    packs: dict[str, dict] = {}
    for f in sorted(glob.glob("data/decisions/dp-*.json")):
        with open(f) as fh:
            d = json.load(fh)
        packs[str(d.get("date"))] = d  # 同日多包 → 后者覆盖（重跑）
    return packs


def weights_for(buys: list[dict], alloc: float, cap: float) -> dict[str, float]:
    """用给定 cap 跑一次真实 allocator，返回 symbol → 目标权重。"""
    if not buys or alloc <= 0:
        return {}
    cands = pd.DataFrame(
        {
            "symbol": [r["symbol"] for r in buys],
            "alpha_score": [0.5] * len(buys),
            "max_weight_limit": [cap] * len(buys),
            "risk_cluster": [""] * len(buys),
        }
    )
    allocator = CapitalAllocator(
        CapitalAllocatorConfig(
            method="equal_weight",
            cash_buffer=0.05,
            target_vol=0.15,
            reserve_policy=ReservePolicy(standard_position_weight=cap),
        )
    )
    res = allocator.run(candidates=cands, total_capital=alloc, date="")
    tp = res.target_portfolio
    if tp is None:
        return {}
    return {
        str(p["symbol"]): float(p["target_weight"])
        for p in tp.positions
        if p.get("symbol") != "CASH"
    }


def simulate(fixed: bool, px: dict[tuple[str, str], float], dates: list[str], packs: dict):
    cash, pos, last = INIT, {}, {}
    curve, trades = [], []
    for day in dates:
        for (d, s), p in px.items():
            if d == day:
                last[s] = p
        d = packs.get(day)
        if d:
            rep = d.get("report") or {}
            recs = rep.get("recommendations") or []
            alloc = float(rep.get("total_capital") or 0)
            exp = float((d.get("regime") or {}).get("suggested_exposure") or 0)
            buys = [r for r in recs if r.get("action") == "BUY"]
            sells = [r for r in recs if r.get("action") == "SELL"]

            for r in sells:
                sym = str(r["symbol"])
                if sym in pos:
                    price = float(r.get("estimated_price") or last.get(sym, 0))
                    cash += pos[sym] * price
                    del pos[sym]

            if buys and alloc > 0:
                if fixed:
                    cap = min(1.0, 0.08 / exp) if exp > 0 else 1.0
                    w = weights_for(buys, alloc, cap)
                else:
                    w = weights_for(buys, alloc, 0.08)  # bug 口径：硬编码 8%
                for r in buys:
                    sym = str(r["symbol"])
                    price = float(r.get("estimated_price") or 0)
                    if price <= 0 or sym not in w:
                        continue
                    qty = int(w[sym] * alloc / price // 100 * 100)
                    amt = qty * price
                    if qty <= 0 or amt > cash:
                        continue
                    cash -= amt
                    pos[sym] = pos.get(sym, 0) + qty
                    trades.append((day, sym, qty, price, amt))

        equity = cash + sum(q * last.get(s, 0) for s, q in pos.items())
        curve.append((day, equity, cash, len(pos), equity / INIT - 1))
    return curve, trades


def main() -> None:
    px, dates = load_prices()
    packs = load_packs()
    print(f"区间 {START} → {END}，{len(dates)} 个交易日，{len(packs)} 个决策包(去重)\n")

    results = {}
    for label, fixed in (("修复前(8% 硬编码)", False), ("修复后(按敞口换算)", True)):
        curve, trades = simulate(fixed, px, dates, packs)
        peak, mdd = INIT, 0.0
        for _, eq, *_ in curve:
            peak = max(peak, eq)
            mdd = max(mdd, (peak - eq) / peak)
        expo = [eq - c for _, eq, c, *_ in curve]
        results[label] = (curve, trades, mdd, expo)
        final = curve[-1]
        print(f"【{label}】")
        print(f"  期末权益 {final[1]:,.0f}  收益 {final[4] * 100:+.2f}%")
        print(f"  最大回撤 {mdd * 100:.2f}%  成交笔数 {len(trades)}")
        avg_expo = sum((eq - c) / eq for _, eq, c, *_ in curve) / len(curve)
        print(f"  平均仓位 {avg_expo * 100:.2f}%")
        peak_expo = max((eq - c) / eq for _, eq, c, *_ in curve)
        print(f"  最高仓位 {peak_expo * 100:.2f}%\n")

    a, b = results["修复前(8% 硬编码)"], results["修复后(按敞口换算)"]
    print("=" * 62)
    print(f"收益差: {(b[0][-1][4] - a[0][-1][4]) * 100:+.2f}pp")
    print("各建仓日对比（当日收盘权益 / 仓位）:")
    print(f"  {'日期':<12}{'修复前权益':>12}{'修复后权益':>12}{'前仓位':>9}{'后仓位':>9}")
    for (day, eq_a, cash_a, *_), (_, eq_b, cash_b, *_) in zip(a[0], b[0], strict=False):
        if day in packs:
            print(
                f"  {day:<12}{eq_a:>12,.0f}{eq_b:>12,.0f}"
                f"{(eq_a - cash_a) / eq_a * 100:>8.1f}%{(eq_b - cash_b) / eq_b * 100:>8.1f}%"
            )


if __name__ == "__main__":
    main()
