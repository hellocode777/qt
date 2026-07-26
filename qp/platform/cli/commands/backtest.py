"""CLI command handlers for the "backtest" group."""
from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import polars as pl


def backtest_config_strategy(
    strategy_id: str,
    price_data: dict[str, pl.DataFrame],
    prices: pl.DataFrame,
    today: object,
) -> int:
    """Run broker backtest for a config-based strategy."""
    import numpy as np
    import polars as pl

    from qp.simulation.broker import SimulatedBroker
    from qp.simulation.result import SimulationResult
    from qp.strategy.config import get_strategy_config

    config = get_strategy_config(strategy_id)

    # Import the strategy's run function dynamically
    strategy_module_map = {
        "momentum_vol_full": "qp.strategy.strategies.momentum_vol_full",
        "alpha_multi_factor_v1": "qp.strategy.strategies.alpha_multi_factor",
        "alpha_multi_factor_v2": "qp.strategy.strategies.alpha_multi_factor",
    }

    module_path = strategy_module_map.get(strategy_id)
    if module_path is None:
        print(f"❌ 策略 '{strategy_id}' 已注册但无执行模块映射。")
        return 1

    import importlib

    mod = importlib.import_module(module_path)
    run_func = getattr(mod, f"run_{strategy_id}", None)
    if run_func is None:
        # Try snake_case to function name conversion
        func_name = "run_" + strategy_id
        run_func = getattr(mod, func_name, None)
    if run_func is None:
        # Fallback: use run_momentum_vol_full for config-based variants
        try:
            from qp.strategy.strategies.momentum_vol_full import run_momentum_vol_full

            run_func = run_momentum_vol_full
        except ImportError:
            pass
    if run_func is None:
        print(f"❌ 策略 '{strategy_id}' 模块加载失败。")
        return 1

    # Build index proxy from price data
    index_df = build_index_df_from_prices(price_data)

    print(f"  数据覆盖:  {len(price_data)} stocks")
    print(f"  策略配置:  {config.display_name}")
    print()

    # Generate signals for all dates
    try:
        result = run_func(
            price_data=price_data,
            config=config,
            index_df=index_df,
            return_diagnostics=True,
        )
        if isinstance(result, tuple):
            signals, diagnostics = result
        else:
            signals = result
            diagnostics = {}
    except Exception as exc:
        print(f"❌ 策略执行失败: {exc}")
        import traceback

        traceback.print_exc()
        return 1

    if signals.is_empty():
        print("❌ 无信号。")
        return 1

    # Signals have columns: [date, symbol, signal, score, reason, name]
    symbols = signals["symbol"].unique().to_list()
    n_signals = len(signals)
    print(f"  信号总数 / Signals:    {n_signals}")
    print(f"  涉及标的 / Symbols:     {len(symbols)}")
    if diagnostics:
        print("  诊断 / Diagnostics:")
        for k, v in diagnostics.items():
            if isinstance(v, (int, float, str)):
                print(f"    {k}: {v}")
    print()

    # ── Broker backtest ──
    initial_capital = 1_000_000
    broker = SimulatedBroker(initial_cash=initial_capital, slippage_model="fixed")

    dates = sorted(
        signals["trade_date"].unique().to_list()
        if "trade_date" in signals.columns
        else prices["trade_date"].unique().to_list()
    )
    if not dates:
        print("❌ 无交易日数据。")
        return 1

    price_lookup = prices.sort(["symbol", "trade_date"])
    daily_nav: list[dict] = []
    daily_returns: list[float] = []

    current_holdings: dict[str, int] = {}
    for i, d in enumerate(dates):
        day_signals = (
            signals.filter(pl.col("trade_date") == d)
            if "trade_date" in signals.columns
            else signals
        )
        day_prices = price_lookup.filter(pl.col("trade_date") == d)

        price_map: dict[str, float] = {}
        adv_map: dict[str, float] = {}
        for row in day_prices.iter_rows(named=True):
            sym = str(row["symbol"])
            px = float(row["close"])
            vol = float(row.get("volume", 0))
            price_map[sym] = px
            if vol > 0 and px > 0:
                adv_map[sym] = px * vol

        broker.set_prices(price_map, adv_map, str(d))

        # On signal dates, rebalance to top-N
        if not day_signals.is_empty():
            # Sell everything we hold
            for sym, qty in list(current_holdings.items()):
                if qty > 0:
                    broker.submit_order(
                        {
                            "symbol": sym,
                            "side": "SELL",
                            "quantity": qty,
                            "order_type": "market",
                        }
                    )
            current_holdings.clear()

            # Buy new top-N
            day_symbols = day_signals["symbol"].to_list()
            top_n = min(config.max_positions, len(day_symbols))
            per_stock = initial_capital / top_n
            for sym in day_symbols[:top_n]:
                px = price_map.get(sym, 10.0)
                qty = int(per_stock // px // 100 * 100)
                if qty > 0:
                    broker.submit_order(
                        {
                            "symbol": sym,
                            "side": "BUY",
                            "quantity": qty,
                            "order_type": "market",
                        }
                    )
                    current_holdings[sym] = qty

        broker.execute_pending()
        equity = broker.get_equity()
        daily_nav.append({"date": str(d), "equity": equity})

        if i > 0 and daily_nav[-2]["equity"] > 0:
            ret = equity / daily_nav[-2]["equity"] - 1
            daily_returns.append(ret)

    # ── Compute metrics ──
    result = SimulationResult(
        strategy_id=strategy_id,
        initial_capital=initial_capital,
        final_equity=broker.get_equity(),
        n_days=len(dates),
        n_trades=broker.trade_count,
        total_commission=broker.total_commission,
        total_stamp_tax=broker.total_stamp_tax,
        total_slippage=broker.total_slippage,
        total_market_impact=broker.total_market_impact,
        total_cost=broker.total_trading_cost,
        start_date=str(dates[0]),
        end_date=str(dates[-1]),
    )

    if daily_returns:
        rets = np.array(daily_returns)
        result.total_return_pct = float(((1 + rets).prod() - 1) * 100)
        result.annual_return_pct = float(rets.mean() * 252 * 100)
        result.sharpe_ratio = (
            float(np.sqrt(252) * rets.mean() / rets.std()) if rets.std() > 0 else 0.0
        )
        result.annual_volatility_pct = float(rets.std() * np.sqrt(252) * 100)
        cum = (1 + rets).cumprod()
        running_max = np.maximum.accumulate(cum)
        result.max_drawdown_pct = (
            float(np.abs((cum - running_max).min() / running_max.min()) * 100)
            if len(cum) > 0
            else 0.0
        )

    # ── Print ──
    print()
    print("  ── 回测结果 / Backtest Results ──")
    print(f"  起始日期 / Start:       {result.start_date}")
    print(f"  结束日期 / End:         {result.end_date}")
    print(f"  交易天数 / Days:         {result.n_days}")
    print(f"  交易次数 / Trades:       {result.n_trades}")
    print(f"  总收益 / Total Return:   {result.total_return_pct:.1f}%")
    print(f"  年化收益 / Ann. Return:  {result.annual_return_pct:.1f}%")
    print(f"  夏普比率 / Sharpe:       {result.sharpe_ratio:.2f}")
    print(f"  最大回撤 / Max DD:       {result.max_drawdown_pct:.1f}%")
    print(f"  年化波动 / Ann. Vol:     {result.annual_volatility_pct:.1f}%")
    print()
    print("  ── 交易成本 / Trading Costs ──")
    print(f"  佣金 / Commission:       ¥{result.total_commission:,.0f}")
    print(f"  印花税 / Stamp Tax:      ¥{result.total_stamp_tax:,.0f}")
    print(f"  滑点 / Slippage:        ¥{result.total_slippage:,.0f}")
    print(f"  冲击成本 / Impact:       ¥{result.total_market_impact:,.0f}")
    print(f"  总成本 / Total Cost:     ¥{result.total_cost:,.0f}")

    return 0


def build_index_df_from_prices(price_data: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Build proxy index from average close across all stocks."""
    import polars as pl

    if not price_data:
        return pl.DataFrame()

    closes: list[pl.DataFrame] = []
    for code, pdf in price_data.items():
        if pdf is None or pdf.is_empty():
            continue
        date_col = next((c for c in ["trade_date", "date"] if c in pdf.columns), None)
        if date_col is None:
            continue
        sub = pdf.select([date_col, "close"]).rename({"close": f"close_{code}"})
        closes.append(sub)

    if not closes:
        return pl.DataFrame()

    merged = closes[0]
    for df in closes[1:]:
        date_col = df.columns[0]
        merged = merged.join(df, on=date_col, how="inner")

    close_cols = [c for c in merged.columns if c.startswith("close_")]
    date_col = merged.columns[0]
    return merged.select(
        [
            pl.col(date_col).alias("date"),
            (pl.sum_horizontal([pl.col(c) for c in close_cols]) / len(close_cols)).alias("close"),
        ]
    )


def cmd_backtest_run() -> int:
    """Run broker-based backtest.

    Supports both SimpleRankStrategy (legacy) and config-based strategies
    (momentum_vol_full, etc.) via StrategyLoader.
    """
    from datetime import date

    import numpy as np
    import polars as pl

    from qp.simulation.broker import SimulatedBroker
    from qp.simulation.result import SimulationResult
    from qp.strategy.config import list_strategy_configs
    from qp.strategy.registry import StrategyRegistry
    from qp.strategy.simple_rank import SimpleRankStrategy

    today = date.today()
    strategy_id = "simple_rank_v1.0"
    if len(sys.argv) > 3:
        strategy_id = sys.argv[3]

    print(f"=== QP 回测 / Backtest: {strategy_id} ===")
    print()

    # Load data
    try:
        prices = pl.read_parquet("data/dataset/daily_price_" + today.isoformat() + ".parquet")
    except FileNotFoundError:
        # Try the main dataset
        try:
            prices = pl.read_parquet(
                "data/dataset/daily_price_main_" + today.isoformat() + ".parquet"
            )
        except FileNotFoundError:
            print("❌ 未找到数据文件。请先运行 qp run daily")
            return 1

    # Build price_data dict for config-based strategies
    price_data: dict[str, pl.DataFrame] = {}
    if "symbol" in prices.columns:
        for sym in prices["symbol"].unique().to_list():
            sub = prices.filter(pl.col("symbol") == sym)
            if not sub.is_empty():
                price_data[sym] = sub

    # ── Try config-based strategies first ──
    available_configs = list_strategy_configs()
    if strategy_id in available_configs:
        return backtest_config_strategy(strategy_id, price_data, prices, today)

    # ── Try SimpleRankStrategy (legacy) ──
    registry = StrategyRegistry()
    registry.register(SimpleRankStrategy(top_n=10))
    try:
        strategy = registry.get(strategy_id)
    except KeyError:
        print(f"❌ 策略 '{strategy_id}' 未找到。")
        print("   可用 SimpleRank: simple_rank_v1.0")
        print(f"   可用 Config: {', '.join(available_configs)}")
        return 1

    signals = strategy.generate_signals(today)

    if signals.is_empty():
        print("❌ 无信号。")
        return 1

    symbols = signals["symbol"].to_list()[:10]
    print(f"  候选标的 / Candidates:  {len(symbols)} 只")
    print(f"  标的列表 / Symbols:      {', '.join(symbols[:5])}...")

    # Initialize broker
    broker = SimulatedBroker(initial_cash=1_000_000, slippage_model="fixed")

    # Get sorted trading dates
    dates = sorted(prices["trade_date"].unique().to_list())
    if not dates:
        print("❌ 无交易日数据。")
        return 1

    # Convert prices to dict for broker
    price_df = prices.sort(["symbol", "trade_date"])

    daily_nav: list[dict] = []
    daily_returns: list[float] = []

    for i, d in enumerate(dates):
        day_prices = price_df.filter(pl.col("trade_date") == d)
        price_map = {}
        adv_map = {}
        for row in day_prices.iter_rows(named=True):
            sym = str(row["symbol"])
            px = float(row["close"])  # type: ignore[arg-type]
            vol = float(row.get("volume", 0))  # type: ignore[arg-type]
            price_map[sym] = px
            if vol > 0 and px > 0:
                adv_map[sym] = px * vol

        broker.set_prices(price_map, adv_map, str(d))

        # On first day, submit opening orders
        if i == 0:
            per_stock_capital = 1_000_000 / len(symbols)
            for sym in symbols:
                px = price_map.get(sym, 10.0)
                qty = int(per_stock_capital / px // 100 * 100)
                if qty > 0:
                    broker.submit_order(
                        {
                            "symbol": sym,
                            "side": "BUY",
                            "quantity": qty,
                            "order_type": "market",
                        }
                    )

        broker.execute_pending()

        equity = broker.get_equity()
        daily_nav.append({"date": str(d), "equity": equity})

        if i > 0 and daily_nav[-2]["equity"] > 0:
            ret = equity / daily_nav[-2]["equity"] - 1
            daily_returns.append(ret)

    # Compute result
    result = SimulationResult(
        strategy_id=strategy_id,
        initial_capital=1_000_000,
        final_equity=broker.get_equity(),
        n_days=len(dates),
        n_trades=broker.trade_count,
        total_commission=broker.total_commission,
        total_stamp_tax=broker.total_stamp_tax,
        total_slippage=broker.total_slippage,
        total_market_impact=broker.total_market_impact,
        total_cost=broker.total_trading_cost,
        start_date=str(dates[0]),
        end_date=str(dates[-1]),
    )

    if daily_returns:
        rets = np.array(daily_returns)
        result.total_return_pct = float(((1 + rets).prod() - 1) * 100)
        result.annual_return_pct = float(rets.mean() * 252 * 100)
        result.sharpe_ratio = (
            float(np.sqrt(252) * rets.mean() / rets.std()) if rets.std() > 0 else 0.0
        )
        result.annual_volatility_pct = float(rets.std() * np.sqrt(252) * 100)
        cum = (1 + rets).cumprod()
        running_max = np.maximum.accumulate(cum)
        result.max_drawdown_pct = (
            float(np.abs((cum - running_max).min() / running_max.min()) * 100)
            if len(cum) > 0
            else 0.0
        )

    # Print
    print()
    print("  ── 回测结果 / Backtest Results ──")
    print(f"  起始日期 / Start:       {result.start_date}")
    print(f"  结束日期 / End:         {result.end_date}")
    print(f"  交易天数 / Days:         {result.n_days}")
    print(f"  交易次数 / Trades:       {result.n_trades}")
    print(f"  总收益 / Total Return:   {result.total_return_pct:.1f}%")
    print(f"  年化收益 / Ann. Return:  {result.annual_return_pct:.1f}%")
    print(f"  夏普比率 / Sharpe:       {result.sharpe_ratio:.2f}")
    print(f"  最大回撤 / Max DD:       {result.max_drawdown_pct:.1f}%")
    print(f"  年化波动 / Ann. Vol:     {result.annual_volatility_pct:.1f}%")
    print()
    print("  ── 交易成本 / Trading Costs ──")
    print(f"  佣金 / Commission:       ¥{result.total_commission:,.0f}")
    print(f"  印花税 / Stamp Tax:      ¥{result.total_stamp_tax:,.0f}")
    print(f"  滑点 / Slippage:        ¥{result.total_slippage:,.0f}")
    print(f"  冲击成本 / Impact:       ¥{result.total_market_impact:,.0f}")
    print(f"  总成本 / Total Cost:     ¥{result.total_cost:,.0f}")

    return 0

