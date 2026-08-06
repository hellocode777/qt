"""CLI command handlers for the "portfolio" group."""

from __future__ import annotations

# ------------------------------------------------------------------
# 中英文行业映射
# ------------------------------------------------------------------


SECTOR_NAME_ZH: dict[str, str] = {
    "Consumer": "消费",
    "Financials": "金融",
    "Technology": "科技",
    "RealEstate": "房地产",
    "Healthcare": "医药健康",
    "Materials": "建材材料",
    "Energy": "新能源",
    "Other": "其他",
}


ALLOC_METHOD_ZH: dict[str, str] = {
    "equal_weight": "等权分配",
    "risk_parity": "风险平价",
    "kelly": "凯利公式",
}


def sector_zh(en_name: str) -> str:
    """Translate sector name to Chinese, falling back to English."""
    return SECTOR_NAME_ZH.get(en_name, en_name)


def cmd_portfolio_report() -> int:
    """Print portfolio-level KPI dashboard (bilingual)."""
    from datetime import date

    import polars as pl

    from qp.portfolio import (
        AllocationFactory,
        CostModel,
        IndustryMapper,
        MarketImpactModel,
        MeanVarianceOptimizer,
        PortfolioRiskManager,
    )
    from qp.strategy.aggregator import SignalAggregator
    from qp.strategy.registry import StrategyRegistry
    from qp.strategy.simple_rank import SimpleRankStrategy

    print("=" * 60)
    print("  QP 投资组合报告 / Portfolio Report")
    print("=" * 60)
    print()

    today = date.today()

    # Load data
    try:
        prices = pl.read_parquet(
            "data/dataset/daily_price_" + today.isoformat() + ".parquet"
        )
    except FileNotFoundError:
        print("❌ 错误: 未找到数据文件，请先运行 'qp run daily'")
        print("   Error: No data found. Run 'qp run daily' first.")
        return 1

    # Generate signals
    registry = StrategyRegistry()
    registry.register(SimpleRankStrategy(top_n=10))
    strategies = registry.get_backtest_ready()
    aggregator = SignalAggregator(method="rank_blend")
    signals_list = [s.generate_signals(today) for s in strategies]
    combined = aggregator.aggregate(signals_list)

    total_capital = 1_000_000
    symbols = combined["symbol"].to_list()[:10] if not combined.is_empty() else []

    if not symbols:
        print("❌ 无有效信号，请先运行 'qp run daily'")
        print("   No active signals. Run 'qp run daily' to generate signals.")
        return 1

    # ── 基本概况 ──
    print("── 基本概况 / Overview ──")
    print(f"  总资产 / Total Capital:     ¥{total_capital:>12,.0f}")
    print(f"  日期 / Date:                {today}")
    print(f"  活跃策略数 / Strategies:       {len(strategies)}")
    print(f"  候选股票数 / Candidates:       {len(symbols)}")
    print()

    # ── 风控限额 ──
    print("── 风控限额 / Risk Limits ──")
    risk_manager = PortfolioRiskManager()
    _filtered, risk_report = risk_manager.apply_risk_limits_with_prices(
        combined, prices
    )
    print(
        f"  持仓数量 / Positions:     {risk_report.candidates_in} → {risk_report.candidates_out} (过滤后)"
    )
    print(f"  单仓上限 / Max Position:  {risk_manager.max_single_position:.0%}")
    print(f"  单行业上限 / Max Sector:   {risk_manager.max_single_sector:.0%}")
    if risk_report.violations:
        for v in risk_report.violations:
            print(f"  ⚠  {v}")
    else:
        print("  ✅ 全部风控限额满足 / All risk limits satisfied")
    if risk_report.dropped_symbols:
        print(f"  已剔除 / Dropped:          {', '.join(risk_report.dropped_symbols)}")
    print()

    # ── 行业暴露 ──
    print("── 行业暴露 / Sector Exposure ──")
    industry = IndustryMapper()
    sector_wt = industry.get_sector_weights(risk_report.position_weights)
    for sector, wt in sorted(sector_wt.items(), key=lambda x: -x[1]):
        zh = sector_zh(sector)
        bar = "█" * int(wt * 100)
        flag = " ⚠" if wt > 0.25 else ""
        print(f"  {zh:<8s} ({sector:<14s}): {wt:6.1%} {bar}{flag}")
    print()

    # ── 成本分析 ──
    print("── 成本分析 / Cost Analysis ──")
    cost_model = CostModel()
    adv_map = MarketImpactModel.compute_adv(prices)
    total_cost = 0.0
    per_symbol_cap = total_capital / max(len(symbols), 1)
    for s in symbols:
        c = cost_model.estimate_trade(
            s, per_symbol_cap, "BUY", daily_volume=adv_map.get(s)
        )
        total_cost += c.total_cost
    print(f"  印花税 / Stamp Tax:          {cost_model.stamp_tax_rate:.3%} (仅卖出)")
    print(f"  佣金 / Commission:           {cost_model.commission_rate:.3%} (买卖双向)")
    print(
        f"  预估单边成本 / One-Way:       ¥{total_cost:>10,.0f}  ({total_cost / total_capital * 100:.3f}%)"
    )
    print(
        f"  预估双边成本 / Round-Trip:     ¥{total_cost * 2:>10,.0f}  ({total_cost * 2 / total_capital * 100:.3f}%)"
    )
    print()

    # ── 资金分配 ──
    print("── 资金分配 / Capital Allocation ──")
    for method in AllocationFactory.list_methods():
        alloc = AllocationFactory.create(method, cash_buffer=0.05)
        raw_signals = combined[:10].to_pandas()
        alloc_df = alloc.allocate_capital(raw_signals, total_capital)  # type: ignore[arg-type]
        top_wt = alloc_df["target_weight"].max() if not alloc_df.empty else 0
        n_alloc = len(alloc_df)
        zh_name = ALLOC_METHOD_ZH.get(method, method)
        print(f"  {zh_name:<8s} ({method:<14s}): {n_alloc} 只, 最大权重 {top_wt:.1%}")
    print()

    # ── 仓位优化 ──
    print("── 仓位优化 / Position Optimization ──")
    optimizer = MeanVarianceOptimizer()
    opt_result = optimizer.optimize(prices, symbols, total_capital)
    if opt_result.converged:
        print("  方法 / Method:            最大夏普比率 (SLSQP)")
    else:
        print(f"  状态 / Status:            {opt_result.message}")
    print(f"  预期夏普 / Expected Sharpe:  {opt_result.sharpe_ratio:.2f}")
    print(f"  预期波动 / Expected Vol:     {opt_result.expected_volatility:.2%}")
    if opt_result.fallback_used:
        print(f"  ⚠ 回退模式 / Fallback:      {opt_result.message}")
    print("  前5大持仓 / Top 5 Positions:")
    top5 = sorted(opt_result.weights.items(), key=lambda x: -x[1])[:5]
    for i, (sym, wt) in enumerate(top5, 1):
        sector = industry.get_sector(sym)
        zh_sec = sector_zh(sector)
        print(f"    {i}. {sym}  {wt:.2%}  ({zh_sec})")
    print()

    # ── KPI 仪表盘 ──
    print("── 组合 KPI 仪表盘 / Portfolio KPI Dashboard ──")

    # Load real metrics from NAV history
    try:
        from qp.portfolio.metrics import PortfolioMetrics
        from qp.portfolio.nav_ledger import NAVLedger

        nav_ledger = NAVLedger()
        nav_df = nav_ledger.load_history()
        if not nav_df.is_empty() and nav_df.height >= 5:
            metrics = PortfolioMetrics.from_nav(nav_df)
            sharpe_str = f"{metrics.sharpe_ratio:.2f}"
            maxdd_str = f"{metrics.max_drawdown_pct:.1f}%"
            ret_str = f"{metrics.annualized_return_pct:.1f}%"
            vol_str = f"{metrics.annualized_volatility_pct:.1f}%"
            calmar_str = f"{metrics.calmar_ratio:.2f}"
            rating_str = metrics.rating()
            n_days = metrics.n_days
        else:
            sharpe_str = maxdd_str = ret_str = vol_str = calmar_str = "N/A"
            rating_str = "数据不足 / No Data"
            n_days = 0
    except Exception:
        sharpe_str = maxdd_str = ret_str = vol_str = calmar_str = "N/A"
        rating_str = "计算失败 / Error"
        n_days = 0

    print(f"  {'指标':<20s} {'当前值':>12s}  {'说明'}")
    print(f"  {'─' * 52}")
    print(f"  {'夏普比率 / Sharpe':<20s} {sharpe_str:>12s}  年度风险调整收益")
    print(f"  {'最大回撤 / MaxDD':<20s} {maxdd_str:>12s}  历史最大亏损")
    print(f"  {'年化收益 / Ann.Ret':<20s} {ret_str:>12s}  年化收益率")
    print(f"  {'年化波动 / Ann.Vol':<20s} {vol_str:>12s}  年化波动率")
    print(f"  {'卡玛比率 / Calmar':<20s} {calmar_str:>12s}  收益/最大回撤")
    print(f"  {'评级 / Rating':<20s} {rating_str:>12s}  基于夏普比率")
    print(f"  {'数据天数 / Days':<20s} {n_days!s:>12s}  NAV 记录数")
    print(f"  {'持仓数量 / Count':<20s} {len(symbols):>12}    当前候选标的")

    return 0


def cmd_portfolio_risk() -> int:
    """Run risk analysis on current holdings (bilingual)."""
    from datetime import date

    import polars as pl

    from qp.portfolio import CorrelationAnalyzer, IndustryMapper, PortfolioRiskManager

    today = date.today()

    try:
        prices = pl.read_parquet(
            "data/dataset/daily_price_" + today.isoformat() + ".parquet"
        )
    except FileNotFoundError:
        print("❌ 错误: 未找到数据文件，请先运行 'qp run daily'")
        print("   Error: No data found. Run 'qp run daily' first.")
        return 1

    symbols_all = prices["symbol"].unique().to_list()
    print("=" * 60)
    print("  QP 风控分析 / Risk Analysis")
    print("=" * 60)
    print()
    print(f"  覆盖标的 / Symbols:  {len(symbols_all)} 只")
    print()

    # ── 行业集中度 ──
    print("── 行业集中度 / Sector Concentration ──")
    industry = IndustryMapper()
    sector_weights = industry.get_sector_weights(
        dict.fromkeys(symbols_all, 1.0 / len(symbols_all))
    )
    for sector, wt in sorted(sector_weights.items(), key=lambda x: -x[1]):
        zh = sector_zh(sector)
        bar = "█" * int(wt * 100)
        flag = " ⚠ >25%" if wt > 0.25 else ""
        print(f"  {zh:<8s} ({sector:<14s}): {wt:6.1%} {bar}{flag}")
    print()

    # ── 相关性扫描 ──
    print("── 相关性扫描 / Correlation Scan (阈值 >0.7) ──")
    analyzer = CorrelationAnalyzer(threshold=0.7)
    pairs = analyzer.find_high_correlation_pairs(prices, symbols_all)
    if pairs:
        for s1, s2, corr in pairs:
            s1_sec = sector_zh(industry.get_sector(s1))
            s2_sec = sector_zh(industry.get_sector(s2))
            print(f"  {s1}({s1_sec}) ↔ {s2}({s2_sec}):  {corr:+.3f}")
    else:
        print("  ✅ 未发现高相关性对 / No high-correlation pairs detected")
    print()

    # ── 风控限额 ──
    print("── 风控限额 / Risk Limits ──")
    risk_manager = PortfolioRiskManager()
    print(f"  单仓上限 / Max Position:     {risk_manager.max_single_position:.0%}")
    print(f"  单行业上限 / Max Sector:      {risk_manager.max_single_sector:.0%}")
    print("  最大持仓数 / Max Positions:   15")
    print("  相关性阈值 / Corr Threshold:  0.7")

    return 0
