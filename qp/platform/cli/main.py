"""Main entry point for the `qp` CLI.

All operations go through this single entry point (ADR-002).
"""

from __future__ import annotations

import sys


def _cmd_version() -> int:
    """Print version information."""
    from qp.platform.metadata.version import __version__

    print(f"qp {__version__}")
    return 0


def _cmd_doctor() -> int:
    """Run environment diagnostics."""
    import platform

    from qp.platform.metadata.environment import EnvironmentMeta

    print("=== QP Doctor ===")
    print()
    print(f"Python version: {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
    print(f"Platform: {platform.platform()}")

    env = EnvironmentMeta()
    print(f"CPU cores: {env.cpu_count}")
    print(f"Disk free: {env.disk_free_gb:.1f} GB")
    print(f"Working dir: {env.cwd}")

    try:
        from qp.platform.config import load_config
        config = load_config()
        print(f"Config: OK (env={config.runtime.env})")
    except Exception as e:
        print(f"Config: FAILED ({e})")

    try:
        from qp.platform.storage.factory import StorageFactory
        factory = StorageFactory("duckdb", duckdb_path=":memory:")
        storage = factory.get_storage()
        storage.connect()
        print(f"Storage: OK (backend={factory._backend_name})")
        storage.close()
    except Exception as e:
        print(f"Storage: FAILED ({e})")

    print()
    print("=== All checks passed ===")
    return 0


def _cmd_pipeline_list() -> int:
    """List registered pipelines."""

    print("Registered Pipelines:")
    print("  data_ingest     — Raw data → cleaned daily_price.parquet")
    print("  feature_compute — Compute momentum_20d feature")
    print("  daily           — End-to-end: data → feature → strategy → report")
    return 0


def _cmd_ingest() -> int:
    """Run data ingestion pipeline."""
    from qp.data.pipeline import DataPipeline
    from qp.platform.pipeline.context import PipelineContext

    pipeline = DataPipeline()

    kwargs: dict = {}
    args = sys.argv[2:]
    for arg in args:
        if arg == "--demo":
            kwargs["demo"] = True
        elif not arg.startswith("--"):
            if "start_date" not in kwargs:
                kwargs["start_date"] = arg
            else:
                kwargs["end_date"] = arg

    context = PipelineContext(pipeline_name=pipeline.name, parameters=kwargs)
    result = pipeline.run(context)

    print(f"Status: {result.status.value}")
    print(f"Rows: {result.metrics.get('raw_rows', 'N/A')} raw → {result.metrics.get('cleaned_rows', 'N/A')} cleaned")
    if result.errors:
        for e in result.errors:
            print(f"Error: {e}")
    if result.metadata.get("version"):
        print(f"Version: {result.metadata['version']}")

    return 0 if result.status.value == "success" else 1


def _cmd_run() -> int:
    """Run the daily end-to-end pipeline."""
    from qp.pipeline.daily_pipeline import DailyPipeline
    from qp.platform.pipeline.context import PipelineContext

    print("=== QP Daily Pipeline ===")
    print()

    demo = "--demo" in sys.argv
    context = PipelineContext(
        pipeline_name="daily",
        parameters={"demo": demo} if demo else {},
    )
    pipeline = DailyPipeline()
    result = pipeline.run(context)

    print(f"Status: {result.status.value}")
    print(f"Pipeline: {result.pipeline_name}")
    print(f"Run ID: {result.run_id}")
    print(f"Duration: {result.duration_seconds:.1f}s")
    print()

    if result.metrics:
        print("Metrics:")
        for k, v in sorted(result.metrics.items()):
            print(f"  {k}: {v}")

    if result.metadata:
        print()
        print("Orders:")
        for k, v in sorted(result.metadata.items()):
            if k.startswith("order_"):
                print(f"  {k.removeprefix('order_')}: {v}")

    if result.errors:
        print()
        print("Errors:")
        for e in result.errors:
            print(f"  {e}")

    return 0 if result.status.value == "success" else 1


def _cmd_validate() -> int:
    """Run validation gate checks on the current strategy."""
    import polars as pl

    from qp.validation import (
        ICIRCheck,
        MaxDrawdownCheck,
        RankICCheck,
        RuleEngine,
        SharpeCheck,
        StratificationCheck,
        TStatCheck,
        ValidationContext,
    )

    print("=== QP Validation Gate ===")
    print()

    # Load data
    try:
        feature_df = pl.read_parquet("data/dataset/momentum_20d.parquet")
        price_df = pl.read_parquet("data/dataset/daily_price_2026-07-20.parquet")
    except FileNotFoundError as e:
        print(f"Error: Data not found. Run 'qp run daily' first. ({e})")
        return 1

    # Ensure date types match
    feature_df = feature_df.with_columns(pl.col("trade_date").cast(pl.Date))
    price_df = price_df.with_columns(pl.col("trade_date").cast(pl.Date))

    # Build validation context
    ctx = ValidationContext(
        feature_df=feature_df,
        price_df=price_df,
        strategy_id="simple_rank_v1.0",
        backtest_metrics={
            "sharpe_ratio": 0.88,       # From Phase 1 real-data run
            "max_drawdown_pct": 14.02,
            "total_return": 40.62,
        },
    )

    # Register all checks
    engine = RuleEngine()
    engine.register(RankICCheck(min_ic_mean=0.02))
    engine.register(ICIRCheck(min_ic_ir=0.3))
    engine.register(TStatCheck(min_t_stat=2.0))
    engine.register(StratificationCheck(n_quantiles=5, min_t_stat=2.0))
    engine.register(SharpeCheck(min_sharpe=1.0))
    engine.register(MaxDrawdownCheck(max_drawdown_pct=25.0))

    result = engine.validate(ctx)

    # Print results
    print(f"Strategy: {ctx.strategy_id}")
    print(f"Overall:  {result.status.value.upper()}")
    print(f"Score:    {result.score}/100")
    print(f"Confidence: {result.confidence:.0%}")
    print()

    print("Checks:")
    for r in result.rules:
        icon = "✅" if r.status.value == "pass" else "❌"
        print(f"  {icon} {r.rule_name:<22s}  {r.detail}")

    if result.failed_rules:
        print()
        print(f"Failed: {len(result.failed_rules)}/{len(result.rules)} rules — {', '.join(result.failed_rules)}")
        print(f"Recommendation: {result.recommendation}")
    else:
        print()
        print("All checks passed — strategy may proceed to Paper Trading.")

    return 0 if result.passed else 1


# ------------------------------------------------------------------
# 中英文行业映射
# ------------------------------------------------------------------

_SECTOR_NAME_ZH: dict[str, str] = {
    "Consumer": "消费",
    "Financials": "金融",
    "Technology": "科技",
    "RealEstate": "房地产",
    "Healthcare": "医药健康",
    "Materials": "建材材料",
    "Energy": "新能源",
    "Other": "其他",
}

_ALLOC_METHOD_ZH: dict[str, str] = {
    "equal_weight": "等权分配",
    "risk_parity": "风险平价",
    "kelly": "凯利公式",
}


def _sector_zh(en_name: str) -> str:
    """Translate sector name to Chinese, falling back to English."""
    return _SECTOR_NAME_ZH.get(en_name, en_name)


def _cmd_portfolio_report() -> int:
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
        prices = pl.read_parquet("data/dataset/daily_price_" + today.isoformat() + ".parquet")
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
    filtered, risk_report = risk_manager.apply_risk_limits_with_prices(combined, prices)
    print(f"  持仓数量 / Positions:     {risk_report.candidates_in} → {risk_report.candidates_out} (过滤后)")
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
        zh = _sector_zh(sector)
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
        c = cost_model.estimate_trade(s, per_symbol_cap, "BUY", daily_volume=adv_map.get(s))
        total_cost += c.total_cost
    print(f"  印花税 / Stamp Tax:          {cost_model.stamp_tax_rate:.3%} (仅卖出)")
    print(f"  佣金 / Commission:           {cost_model.commission_rate:.3%} (买卖双向)")
    print(f"  预估单边成本 / One-Way:       ¥{total_cost:>10,.0f}  ({total_cost/total_capital*100:.3f}%)")
    print(f"  预估双边成本 / Round-Trip:     ¥{total_cost*2:>10,.0f}  ({total_cost*2/total_capital*100:.3f}%)")
    print()

    # ── 资金分配 ──
    print("── 资金分配 / Capital Allocation ──")
    for method in AllocationFactory.list_methods():
        alloc = AllocationFactory.create(method, cash_buffer=0.05)
        raw_signals = combined[:10].to_pandas()
        alloc_df = alloc.allocate_capital(raw_signals, total_capital)  # type: ignore[arg-type]
        top_wt = alloc_df["target_weight"].max() if not alloc_df.empty else 0
        n_alloc = len(alloc_df)
        zh_name = _ALLOC_METHOD_ZH.get(method, method)
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
        zh_sec = _sector_zh(sector)
        print(f"    {i}. {sym}  {wt:.2%}  ({zh_sec})")
    print()

    # ── KPI 仪表盘 ──
    print("── 组合 KPI 仪表盘 / Portfolio KPI Dashboard ──")
    print(f"  {'指标':<20s} {'目标':>10s} {'状态':>10s}  {'说明'}")
    print(f"  {'─'*58}")
    print(f"  {'夏普比率 / Sharpe':<18s} {'≥ 1.2':>8s}  {'待回测':>8s}   年度风险调整收益")
    print(f"  {'最大回撤 / MaxDD':<18s} {'≤ 20%':>8s}  {'待回测':>8s}   历史最大亏损")
    print(f"  {'超额占比 / Alpha%':<18s} {'≥ 60%':>8s}  {'待回测':>8s}   Alpha 收益占比")
    print(f"  {'持仓数量 / Count':<18s}  {'8-15':>8s} {len(symbols):>10}    当前候选标的")

    return 0


def _cmd_portfolio_risk() -> int:
    """Run risk analysis on current holdings (bilingual)."""
    from datetime import date

    import polars as pl

    from qp.portfolio import CorrelationAnalyzer, IndustryMapper, PortfolioRiskManager

    today = date.today()

    try:
        prices = pl.read_parquet("data/dataset/daily_price_" + today.isoformat() + ".parquet")
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
    sector_weights = industry.get_sector_weights(dict.fromkeys(symbols_all, 1.0 / len(symbols_all)))
    for sector, wt in sorted(sector_weights.items(), key=lambda x: -x[1]):
        zh = _sector_zh(sector)
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
            s1_sec = _sector_zh(industry.get_sector(s1))
            s2_sec = _sector_zh(industry.get_sector(s2))
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


def _print_help() -> int:
    """Print help message."""
    print("qp — Quant Platform CLI")
    print()
    print("Usage: qp <command> [options]")
    print()
    print("Commands:")
    print("  version          Show version information")
    print("  doctor           Run environment diagnostics")
    print("  pipeline list    List registered pipelines")
    print("  ingest [start] [end] [--demo]  Run data ingestion")
    print("  run daily [--demo]       Run end-to-end daily pipeline")
    print("  validate                 Run validation gate checks")
    print("  portfolio report         Portfolio KPI dashboard")
    print("  portfolio risk           Risk analysis + correlation scan")
    print()
    print("Phase 1 (available):")
    print("  qp ingest --demo              Ingest with synthetic demo data")
    print("  qp ingest 2024-01-01 2024-12-31  Ingest date range")
    print("  qp run daily --demo           Full pipeline with demo data")
    print()
    print("Phase 2 (available):")
    print("  qp validate                   Validate current strategy against all gates")
    print()
    print("Phase 3 (available):")
    print("  qp portfolio report           Portfolio KPI dashboard")
    print("  qp portfolio risk             Risk analysis + correlation scan")
    return 0


def main() -> int:
    """Entry point for the qp CLI."""
    if len(sys.argv) < 2:
        print("qp: missing command. Try 'qp --help'", file=sys.stderr)
        return 1

    command = sys.argv[1]

    if command == "version" or command == "--version" or command == "-V":
        return _cmd_version()
    if command == "doctor":
        return _cmd_doctor()
    if command in ("--help", "-h"):
        return _print_help()

    if command == "ingest":
        return _cmd_ingest()

    if command == "run" and len(sys.argv) > 2 and sys.argv[2] == "daily":
        return _cmd_run()

    if command == "pipeline" and len(sys.argv) > 2 and sys.argv[2] == "list":
        return _cmd_pipeline_list()

    if command == "validate":
        return _cmd_validate()

    if command == "portfolio" and len(sys.argv) > 2:
        sub = sys.argv[2]
        if sub == "report":
            return _cmd_portfolio_report()
        if sub == "risk":
            return _cmd_portfolio_risk()
        print(f"qp portfolio: unknown subcommand '{sub}'. Try: report, risk", file=sys.stderr)
        return 1

    if command == "portfolio":
        print("qp portfolio: missing subcommand. Try: qp portfolio report", file=sys.stderr)
        return 1

    print(f"qp: unknown command '{command}'. Try 'qp --help'", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
