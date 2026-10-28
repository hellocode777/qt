"""回归测试：回测引擎必须尊重 `rebalance_freq`，不能写死 20 天。

2026-10-28 事故：`_compute_backtest` 内部曾硬编码 `rebalance_freq = 20`
（注释「match generate_rebalance_signals default」），而 CLI 的 `--rebalance=N`
只影响信号生成 → 用 5/10/20 日跑出的回测结果**逐位相同**，全周期阶梯实验
得到假的“周期不影响业绩”结论。

本测试用合成行情直接打回测引擎：调仓周期越小，调仓次数与换手必须越多。
"""

from __future__ import annotations

import polars as pl

from qp.pipeline.multifactor_pipeline import MultiFactorPipeline


def _dates(n_days: int) -> list[str]:
    """生成连续的伪交易日（仅用于回测引擎，不涉及真实日历）。"""
    return [f"2026-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}" for i in range(n_days)]


def _price_data(dates: list[str], symbols: tuple[str, ...]) -> dict[str, pl.DataFrame]:
    """构造 {symbol: [trade_date, close, volume]}；价格带轻微趋势避免全平。"""
    data: dict[str, pl.DataFrame] = {}
    for idx, symbol in enumerate(symbols):
        closes = [10.0 + idx * 0.5 + 0.05 * i for i in range(len(dates))]
        data[symbol] = pl.DataFrame(
            {
                "trade_date": dates,
                "close": closes,
                "volume": [1_000_000.0] * len(dates),
            }
        )
    return data


def _scores(dates: list[str], symbols: tuple[str, ...]) -> pl.DataFrame:
    """每日给每个标的打分，故意让排名随天数轮换（制造换仓需求）。"""
    rows: list[dict[str, object]] = []
    for day, date in enumerate(dates):
        for idx, symbol in enumerate(symbols):
            # 排名随天数轮转：每 5 天换一次头名
            score = float((idx - day // 5) % len(symbols))
            rows.append({"trade_date": date, "symbol": symbol, "score": score})
    return pl.DataFrame(rows)


def _run(freq: int) -> dict[str, object]:
    dates = _dates(61)
    symbols = ("600000", "600001", "600002", "600003", "600004", "600005")
    signals = pl.DataFrame({"date": dates[:1], "symbol": [symbols[0]]})
    return MultiFactorPipeline._compute_backtest(  # type: ignore[attr-defined]
        signals,
        _price_data(dates, symbols),
        scores=_scores(dates, symbols),
        top_n=2,
        rebalance_offset=0,
        rebalance_freq=freq,
    )


def test_shorter_freq_trades_more() -> None:
    """rebalance_freq=5 的调仓次数/换手必须明显高于 20。"""
    fast = _run(5)
    slow = _run(20)

    assert int(fast["n_trades"]) > int(slow["n_trades"]), (  # type: ignore[call-overload]
        f"5 日调仓的交易数应更多：fast={fast['n_trades']} slow={slow['n_trades']}"
    )
    assert float(fast["turnover_pct"]) > float(slow["turnover_pct"]), (  # type: ignore[arg-type]
        f"5 日调仓的换手应更高：fast={fast['turnover_pct']} slow={slow['turnover_pct']}"
    )


def test_default_freq_keeps_20_day_calendar() -> None:
    """不传 rebalance_freq 时保持历史 20 日行为（历史 run 结果可比）。"""
    dates = _dates(61)
    symbols = ("600000", "600001", "600002", "600003", "600004", "600005")
    signals = pl.DataFrame({"date": dates[:1], "symbol": [symbols[0]]})
    price = _price_data(dates, symbols)
    scores = _scores(dates, symbols)

    implicit = MultiFactorPipeline._compute_backtest(  # type: ignore[attr-defined]
        signals, price, scores=scores, top_n=2, rebalance_offset=0
    )
    explicit = MultiFactorPipeline._compute_backtest(  # type: ignore[attr-defined]
        signals, price, scores=scores, top_n=2, rebalance_offset=0, rebalance_freq=20
    )
    assert implicit["n_trades"] == explicit["n_trades"]
    assert implicit["turnover_pct"] == explicit["turnover_pct"]
