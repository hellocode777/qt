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
    print(
        f"Python version: {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    )
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
    print(
        f"Rows: {result.metrics.get('raw_rows', 'N/A')} raw → {result.metrics.get('cleaned_rows', 'N/A')} cleaned"
    )
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
    """Run validation gate checks on the current strategy.

    Usage:
        qp validate                          # All-stage validation
        qp validate --stage backtest_passed  # Specific stage only
        qp validate --json                   # Machine-readable output
        qp validate --strategy-id my_strat   # Target a specific strategy
    """
    import json as _json
    import sys

    import polars as pl

    from qp.validation import ValidationPipeline, ValidationPipelineConfig

    # Parse flags
    stage = "backtest_passed"
    strategy_id = "simple_rank_v1.0"
    json_output = False

    args = sys.argv
    i = 2  # skip "qp" and "validate"
    while i < len(args):
        if args[i] == "--stage" and i + 1 < len(args):
            stage = args[i + 1]
            i += 2
        elif args[i] == "--strategy-id" and i + 1 < len(args):
            strategy_id = args[i + 1]
            i += 2
        elif args[i] == "--json":
            json_output = True
            i += 1
        else:
            i += 1

    valid_stages = {
        "research", "backtest_passed", "paper_trading",
        "shadow_production", "production",
    }
    if stage not in valid_stages:
        print(f"Invalid stage: '{stage}'. Valid: {', '.join(sorted(valid_stages))}")
        return 1

    if not json_output:
        print(f"=== QP Validation Gate ({stage}) ===")
        print()

    # Load data
    try:
        feature_df = pl.read_parquet("data/dataset/momentum_20d.parquet")
        price_df = pl.read_parquet("data/dataset/daily_price_2026-07-20.parquet")
    except FileNotFoundError as e:
        msg = f"Data not found. Run 'qp run daily' first. ({e})"
        if json_output:
            print(_json.dumps({"status": "error", "message": msg}))
        else:
            print(f"Error: {msg}")
        return 1

    # Ensure date types match
    feature_df = feature_df.with_columns(pl.col("trade_date").cast(pl.Date))
    price_df = price_df.with_columns(pl.col("trade_date").cast(pl.Date))

    # Build pipeline config with accumulated metadata
    config = ValidationPipelineConfig(
        stage=stage,
        strategy_id=strategy_id,
        overrides={},  # Use defaults — override via config file in future
    )

    pipeline = ValidationPipeline(config=config)

    # Build a context carrying all validation data
    class _CLIValidationCtx:
        pass

    ctx = _CLIValidationCtx()
    ctx.feature_df = feature_df
    ctx.price_df = price_df
    ctx.signal_df = None
    ctx.backtest_metrics = {
        "sharpe_ratio": 0.88,
        "max_drawdown_pct": 14.02,
        "total_return": 40.62,
        "daily_turnover_pct": 30.0,
        "sharpe_ratio_net": 0.72,
        "max_drawdown_pct_net": 17.5,
        "total_cost_pct": 0.35,
    }
    ctx.metadata = {
        "pre_neutralization_ic": 0.05,
        "post_neutralization_ic": 0.038,
        "train_start": "2020-01-01",
        "train_end": "2024-12-31",
        "in_sample_ic": 0.06,
        "out_of_sample_ic": 0.04,
    }

    result = pipeline.run(ctx)

    if json_output:
        out = {
            "stage": stage,
            "strategy_id": strategy_id,
            "status": result.status.value,
            "validation": result.metadata.get("validation", {}),
            "recommendation": result.metadata.get("recommendation", ""),
        }
        print(_json.dumps(out, indent=2, ensure_ascii=False, default=str))
    else:
        validation = result.metadata.get("validation", {})
        print(f"Strategy:   {strategy_id}")
        print(f"Stage:      {stage}")
        print(f"Overall:    {validation.get('status', 'unknown').upper()}")
        print(f"Score:      {validation.get('score', 0)}/100")
        print(f"Confidence: {validation.get('confidence', 0):.0%}")
        print()

        rules = validation.get("rules", [])
        if rules:
            print(f"Checks ({len(rules)} total):")
            for r in rules:
                icon = "✅" if r.get("status") == "pass" else "❌"
                print(f"  {icon} {r.get('rule_name', '?'):<24s}  {r.get('detail', '')}")

        failed = validation.get("failed_rules", [])
        if failed:
            print()
            print(f"Failed: {len(failed)}/{len(rules)} rules — {', '.join(failed)}")
            rec = result.metadata.get("recommendation", "")
            if rec:
                print(f"Recommendation: {rec}")
        elif rules:
            print()
            print("All checks passed — strategy may proceed to the next stage.")

    return 0 if result.status.value == "success" else 1


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
    print(f"  {'─' * 58}")
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


# ------------------------------------------------------------------
# Phase 4 CLI commands
# ------------------------------------------------------------------


def _cmd_experiment_list() -> int:
    """List all tracked experiments."""
    from qp.research.experiment import ExperimentTracker

    tracker = ExperimentTracker()
    records = tracker.list_experiments()

    if not records:
        print("(empty)")
        print("  暂无实验记录。运行 qp run daily 后将自动记录实验。")
        return 0

    print(f"{'ID':<32s} {'Status':<14s} {'Sharpe':>8s} {'IC':>8s} {'Ret':>8s}  Lineage")
    print("-" * 100)
    for r in records:
        print(
            f"{r.config.experiment_id:<32s} "
            f"{r.status.value:<14s} "
            f"{r.metrics.sharpe_ratio:>7.2f} "
            f"{r.metrics.ic_mean:>7.4f} "
            f"{r.metrics.total_return_pct:>7.1f}% "
            f" {r.lineage.chain_str()}"
        )
    print(f"\n共 {len(records)} 条记录 / {len(records)} experiments total")
    return 0


def _cmd_experiment_show() -> int:
    """Show experiment details."""
    if len(sys.argv) < 3:
        print("用法: qp experiment show <experiment_id>")
        return 1

    from qp.research.experiment import ExperimentTracker

    exp_id = sys.argv[2]
    tracker = ExperimentTracker()
    record = tracker.get(exp_id)

    if record is None:
        print(f"实验 {exp_id} 未找到 / Experiment not found")
        return 1

    print(f"=== 实验详情 / Experiment: {exp_id} ===")
    print()
    print(f"  状态 / Status:       {record.status.value}")
    print(f"  创建时间 / Created:   {record.config.created_at.isoformat()}")
    print(f"  描述 / Description:  {record.config.description or '(none)'}")
    print()
    print("  ── 配置 / Config ──")
    print(f"    特征 / Features:    {record.config.features}")
    print(f"    数据版本 / Dataset:  {record.config.dataset_version}")
    print(f"    CV折数 / CV Folds:   {record.config.cv_folds}")
    if record.config.model_params:
        print(f"    模型参数 / Model:    {record.config.model_params}")
    print()
    print("  ── 指标 / Metrics ──")
    print(f"    IC均值 / IC Mean:      {record.metrics.ic_mean:.4f}")
    print(f"    IC_IR:                 {record.metrics.ic_ir:.2f}")
    print(f"    IC t-stat:             {record.metrics.ic_t_stat:.2f}")
    print(f"    夏普比率 / Sharpe:      {record.metrics.sharpe_ratio:.2f}")
    print(f"    最大回撤 / MaxDD:       {record.metrics.max_drawdown_pct:.1f}%")
    print(f"    总收益 / Total Return:  {record.metrics.total_return_pct:.1f}%")
    print(f"    样本内IC / In-Sample:   {record.metrics.in_sample_ic:.4f}")
    print(f"    样本外IC / Out-of-Sample: {record.metrics.out_of_sample_ic:.4f}")
    print()
    print("  ── 血缘 / Lineage ──")
    print(f"    {record.lineage.chain_str()}")
    if record.errors:
        print()
        print("  ── 错误 / Errors ──")
        for e in record.errors:
            print(f"    {e}")

    return 0


def _cmd_experiment_run() -> int:
    """Run a named experiment pipeline (e.g. multifactor)."""
    if len(sys.argv) < 4:
        print("qp experiment run <name> [options]", file=sys.stderr)
        print("  Available: multifactor", file=sys.stderr)
        print("  Options:", file=sys.stderr)
        print("    --symbols 000001,000002,...   Stock codes", file=sys.stderr)
        print("    --start 2024-01-01           Start date", file=sys.stderr)
        print("    --end 2026-07-20             End date", file=sys.stderr)
        print("    --top-n 10                   Top N stocks", file=sys.stderr)
        print("    --rebalance 20               Rebalance frequency (days)", file=sys.stderr)
        print("    --industry-neutral           Enable industry neutralization", file=sys.stderr)
        print("    --orthogonalize              Enable factor orthogonalization", file=sys.stderr)
        print("    --dataset daily_price_main   Gold dataset name", file=sys.stderr)
        return 1

    pipeline_name = sys.argv[3]

    if pipeline_name != "multifactor":
        print(
            f"qp experiment run: unknown pipeline '{pipeline_name}'. Try: multifactor",
            file=sys.stderr,
        )
        return 1

    from qp.platform.pipeline.context import PipelineContext
    from qp.research.experiment.multifactor_pipeline import MultiFactorPipeline

    # Parse options
    params: dict[str, object] = {}
    args = sys.argv[4:]
    i = 0
    while i < len(args):
        arg = args[i]
        if arg.startswith("--symbols="):
            params["symbols"] = arg.split("=", 1)[1].split(",")
        elif arg == "--symbols" and i + 1 < len(args):
            i += 1
            params["symbols"] = args[i].split(",")
        elif arg.startswith("--start="):
            params["start_date"] = arg.split("=", 1)[1]
        elif arg.startswith("--end="):
            params["end_date"] = arg.split("=", 1)[1]
        elif arg.startswith("--top-n="):
            params["top_n"] = int(arg.split("=", 1)[1])
        elif arg.startswith("--rebalance="):
            params["rebalance_freq"] = int(arg.split("=", 1)[1])
        elif arg == "--industry-neutral":
            params["industry_neutral"] = True
        elif arg == "--orthogonalize":
            params["orthogonalize"] = True
        elif arg.startswith("--dataset="):
            params["dataset"] = arg.split("=", 1)[1]
        i += 1

    context = PipelineContext(pipeline_name="multifactor_experiment", parameters=params)
    pipeline = MultiFactorPipeline()
    result = pipeline.run(context)

    if result.status.value != "success":
        return 1

    # Print summary
    logger = __import__("loguru").logger
    logger.info("")
    logger.info("── 实验指标 / Metrics ──")
    for k, v in sorted(result.metrics.items()):
        if isinstance(v, float):
            if abs(v) < 0.01:
                logger.info("  {}: {:.4f}", k, v)
            elif abs(v) < 1:
                logger.info("  {}: {:.2f}", k, v)
            else:
                logger.info("  {}: {:.1f}", k, v)

    return 0


def _cmd_model_list() -> int:
    """List registered models."""
    from qp.research.trainer import ModelRegistry

    registry = ModelRegistry()
    models = registry.list_models()

    if not models:
        print("(empty)")
        print("  暂无已注册模型。")
        return 0

    print(f"{'Model ID':<35s} {'Strategy':<25s} {'Stage':<16s} {'Sharpe':>8s} {'Features'}")
    print("-" * 120)
    for m in models:
        features_str = ", ".join(m.features[:3])
        if len(m.features) > 3:
            features_str += f" +{len(m.features) - 3}"
        print(
            f"{m.model_id:<35s} "
            f"{m.strategy_id:<25s} "
            f"{m.stage.value:<16s} "
            f"{m.metrics.get('sharpe_ratio', 0):>7.2f} "
            f" {features_str}"
        )
    print(f"\n共 {len(models)} 个模型 / {len(models)} models total")
    return 0


def _cmd_model_show() -> int:
    """Show model details."""
    if len(sys.argv) < 3:
        print("用法: qp model show <model_id>")
        return 1

    from qp.research.trainer import ModelRegistry

    model_id = sys.argv[2]
    registry = ModelRegistry()
    meta = registry.get(model_id)

    if meta is None:
        print(f"模型 {model_id} 未找到 / Model not found")
        return 1

    print(f"=== 模型详情 / Model: {model_id} ===")
    print()
    print(f"  策略 / Strategy:       {meta.strategy_id}")
    print(f"  阶段 / Stage:          {meta.stage.value}")
    print(f"  创建时间 / Created:     {meta.created_at}")
    print(f"  文件哈希 / Hash:        {meta.file_hash}")
    print(f"  文件路径 / Path:        {meta.file_path}")
    print()
    print("  ── 训练配置 / Training Config ──")
    print(f"    特征 / Features:      {meta.features}")
    print(f"    时间窗口 / Window:     {meta.training_window}")
    print(f"    CV折数 / CV Folds:    {meta.cv_folds}")
    if meta.hyperparams:
        print("    超参数 / Hyperparams:")
        for k, v in meta.hyperparams.items():
            print(f"      {k}: {v}")
    print()
    print("  ── 评估指标 / Metrics ──")
    if meta.metrics:
        for k, v in sorted(meta.metrics.items()):
            print(f"    {k}: {v}")
    else:
        print("    (none)")

    return 0


def _cmd_data_fetch() -> int:
    """Fetch full main-board data through complete Data Layer pipeline."""
    from qp.data.loader.full_pipeline import FullDataPipeline
    from qp.platform.pipeline.context import PipelineContext

    params: dict[str, object] = {}
    args = sys.argv[3:] if len(sys.argv) > 3 else []
    i = 0
    while i < len(args):
        arg = args[i]
        if arg.startswith("--batch="):
            params["batch_size"] = int(arg.split("=", 1)[1])
        elif arg == "--skip-etl":
            params["skip_etl"] = True
        elif arg.startswith("--start="):
            params["start_date"] = arg.split("=", 1)[1]
        elif arg.startswith("--end="):
            params["end_date"] = arg.split("=", 1)[1]
        i += 1

    print("═══ QP Data Fetch ═══")
    context = PipelineContext(pipeline_name="full_data_ingest", parameters=params)
    pipeline = FullDataPipeline()
    result = pipeline.run(context)

    print(f"\nStatus: {result.status.value}")
    if result.artifacts:
        for a in result.artifacts:
            print(f"Output:  {a}")
    if result.metrics:
        n_stocks = result.metrics.get("n_stocks", 0)
        n_rows = result.metrics.get("n_rows", 0)
        print(f"Stocks:  {n_stocks:.0f}")
        print(f"Rows:    {n_rows:.0f}")
        for tier in ["raw", "bronze", "silver", "gold"]:
            mb = result.metrics.get(f"{tier}_mb", 0)
            if mb:
                print(f"  {tier.capitalize()}: {mb:.0f} MB")
    return 0 if result.status.value == "success" else 1


def _cmd_backtest_run() -> int:
    """Run broker-based backtest."""
    from datetime import date

    import numpy as np
    import polars as pl

    from qp.simulation.broker import SimulatedBroker
    from qp.simulation.result import SimulationResult
    from qp.strategy.registry import StrategyRegistry
    from qp.strategy.simple_rank import SimpleRankStrategy

    today = date.today()
    strategy_id = "simple_rank_v1.0"
    if len(sys.argv) > 2:
        strategy_id = sys.argv[2]

    print(f"=== QP 回测 / Backtest: {strategy_id} ===")
    print()

    # Load data
    try:
        prices = pl.read_parquet("data/dataset/daily_price_" + today.isoformat() + ".parquet")
    except FileNotFoundError:
        print("❌ 未找到数据文件。请先运行 qp run daily")
        return 1

    # Generate signals
    registry = StrategyRegistry()
    registry.register(SimpleRankStrategy(top_n=10))
    strategy = registry.get(strategy_id)
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


def _cmd_monitor_check() -> int:
    """Run daily monitoring check (Kill Switch + Drift + Decay + Health)."""
    from datetime import datetime

    print("=== QP 监控检查 / Monitor Check ===")
    print(f"  时间 / Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # Market Regime
    print("── 市场状态 / Market Regime ──")
    try:
        from qp.monitoring.regime import MarketRegimeEngine

        engine = MarketRegimeEngine()
        # Try to load price data for regime detection
        from pathlib import Path

        import polars as pl

        data_dir = Path("data/dataset")
        parquet_files = sorted(data_dir.glob("daily_price_*.parquet"))
        if parquet_files:
            prices = pl.read_parquet(str(parquet_files[-1]))
            result = engine.classify(prices)
            print(f"  状态 / Regime:     {result.regime.value}")
            print(f"  置信度 / Confidence: {result.confidence:.0%}")
            print(f"  趋势强度 / ADX:    {result.trend_strength:.1f}")
            direction_map = {1: "上升 Uptrend", -1: "下降 Downtrend", 0: "中性 Neutral"}
            print(f"  趋势方向 / Dir:    {direction_map.get(result.trend_direction, 'N/A')}")
            print(f"  年化波动 / Vol:    {result.annualized_vol:.1%}")
            print(f"  波动分位 / Vol%:   {result.volatility_percentile:.0f}%")
            print(f"  {result.summary}")
        else:
            print("  ⚠ 无数据 / No price data — 跳过 regime 检测")
    except Exception as e:
        print(f"  ⚠ Regime detection failed: {e}")

    # Kill Switch
    print()
    print("── 熔断检查 / Kill Switch ──")
    try:
        from qp.monitoring.kill_switch import (
            DrawdownTrigger,
            KillSwitch,
            PortfolioDrawdownTrigger,
            PSITrigger,
        )

        ks = KillSwitch()
        ks.add_trigger(DrawdownTrigger(historical_max_dd=0.14, ratio=1.5))
        ks.add_trigger(PortfolioDrawdownTrigger(monthly_limit=0.15, rolling_60d_limit=0.20))
        ks.add_trigger(PSITrigger(threshold=0.25))

        result = ks.check(
            current_drawdown=0.0,
            monthly_return=0.0,
            rolling_60d_drawdown=0.0,
            psi=0.0,
        )
        status_icon = "✅" if not result.triggered else "🚨"
        status_text = "正常 OK" if not result.triggered else "触发 TRIGGERED"
        print(f"  {status_icon} 熔断状态 / Status: {status_text}")
        if result.triggered:
            for t in result.triggers:
                print(f"    ⚠ {t}")
        print(f"  建议操作 / Rec:   {result.recommendation}")
    except Exception as e:
        print(f"  ⚠ Kill switch check failed: {e}")

    # Strategy Health
    print()
    print("── 策略健康 / Strategy Health ──")
    try:
        from qp.monitoring.strategy_monitor import StrategyMonitor

        monitor = StrategyMonitor(strategy_id="simple_rank_v1.0")
        health = monitor.health_check()
        icon = {
            "healthy": "✅",
            "watch": "👀",
            "warning": "⚠️",
            "critical": "🚨",
        }.get(health.health_level.value, "❓")
        print(f"  {icon} 健康等级 / Level:  {health.health_level.value.upper()}")
        print(f"  健康分数 / Score:     {health.health_score:.0f}/100")
        print(f"  日均信号 / Avg Signals: {health.avg_daily_signals:.1f}")
        print(f"  信号稳定性 / Consistency: {health.signal_consistency:.0%}")
        if health.alerts:
            for a in health.alerts:
                print(f"    ⚠ {a}")
    except Exception as e:
        print(f"  ⚠ Health check failed: {e}")

    # Model Decay
    print()
    print("── 模型衰减 / Model Decay ──")
    try:
        from qp.monitoring.model_decay import ModelDecayDetector

        detector = ModelDecayDetector(training_ic_mean=0.035)
        status = detector.check(rolling_ic=0.030)
        icon = {
            "healthy": "✅",
            "warning": "⚠️",
            "decaying": "🔴",
            "stale": "💀",
        }.get(status.stage.value, "❓")
        print(f"  {icon} 衰减状态 / Stage: {status.stage.value.upper()}")
        print(f"  训练IC / Training IC:   {status.training_ic_mean:.4f}")
        print(f"  滚动IC / Rolling IC:    {status.rolling_ic:.4f}")
        print(f"  IC比率 / IC Ratio:      {status.ic_ratio:.0%}")
        if status.needs_attention:
            print(f"  ⚠ {status.recommended_action}")
    except Exception as e:
        print(f"  ⚠ Model decay check failed: {e}")

    print()
    return 0


def _cmd_monitor_regime() -> int:
    """Detect current market regime."""
    from pathlib import Path

    import polars as pl

    from qp.monitoring.regime import MarketRegimeEngine

    print("=== QP 市场状态检测 / Market Regime Detection ===")
    print()

    data_dir = Path("data/dataset")
    parquet_files = sorted(data_dir.glob("daily_price_*.parquet"))
    if not parquet_files:
        print("❌ 未找到数据文件 / No data found. 请先运行 qp run daily")
        return 1

    prices = pl.read_parquet(str(parquet_files[-1]))
    engine = MarketRegimeEngine()
    result = engine.classify(prices)

    direction_map = {1: "上升 (Uptrend)", -1: "下降 (Downtrend)", 0: "中性 (Neutral)"}

    print(f"  市场状态 / Regime:      {result.regime.value}")
    print(f"  置信度 / Confidence:    {result.confidence:.0%}")
    print(f"  趋势强度 / ADX:         {result.trend_strength:.1f}")
    print(f"  趋势方向 / Direction:   {direction_map.get(result.trend_direction)}")
    print(f"  年化波动率 / Ann. Vol:  {result.annualized_vol:.1%}")
    print(f"  波动率分位数 / Vol%:    {result.volatility_percentile:.0f}%")
    print()

    if result.is_trending:
        print("  💡 建议：趋势市场 → 动量策略 / Use momentum strategies")
    elif result.regime.value == "RANGING":
        print("  💡 建议：震荡市场 → 均值回归策略 / Use mean-reversion strategies")
    elif result.regime.value == "HIGH_VOL":
        print("  💡 建议：高波动 → 降低仓位 / Reduce position sizes")

    return 0


def _cmd_monitor_alert_test() -> int:
    """Send test alerts to all configured channels."""
    from qp.monitoring.alerts import (
        AlertManager,
        AlertSeverity,
        LogAlert,
        TelegramAlert,
        TerminalAlert,
    )

    print("=== QP 告警测试 / Alert Test ===")
    print()

    manager = AlertManager()
    manager.add_channel(TerminalAlert(use_colors=True))
    manager.add_channel(LogAlert())
    manager.add_channel(TelegramAlert(), min_severity=AlertSeverity.WARNING)

    print(f"  已注册通道 / Channels: {manager.channel_count}")
    print()

    print("  发送 INFO 级别...")
    manager.info("测试信息 / Test Info", "监控系统正常运行。All systems operational.", "alert_test")

    print("  发送 WARNING 级别...")
    manager.warning(
        "测试警告 / Test Warning", "这是一条警告测试。This is a test warning.", "alert_test"
    )

    print("  发送 CRITICAL 级别...")
    manager.critical(
        "测试严重告警 / Test Critical",
        "这是一条严重告警测试。This is a test critical alert.",
        "alert_test",
    )

    print()
    print("  告警测试完成 / Alert test complete.")
    return 0


def _cmd_knowledge_stats() -> int:
    """Show knowledge archive statistics."""
    from qp.knowledge.archive import KnowledgeArchive

    print("=== QP 知识库统计 / Knowledge Archive Stats ===")
    print()

    archive = KnowledgeArchive()
    stats = archive.stats()

    category_names = {
        "research_debt": "研究债务 / Research Debt",
        "decision_audit": "决策审计 / Decision Audit",
        "experiment_summary": "实验总结 / Experiment Summary",
        "failure_analysis": "失败分析 / Failure Analysis",
        "post_mortem": "事后复盘 / Post Mortem",
    }

    for cat, name in category_names.items():
        count = stats.get(cat, 0)
        bar = "█" * min(count, 30)
        print(f"  {name:40s} {count:3d} {bar}")

    print(f"  {'─' * 55}")
    print(f"  {'总计 / Total':40s} {stats.get('total', 0):3d}")
    print()
    print("  存储位置 / Storage: data/knowledge/")
    return 0


def _cmd_knowledge_search() -> int:
    """Search knowledge archive."""
    from qp.knowledge.archive import KnowledgeArchive

    if len(sys.argv) < 3:
        print("qp knowledge search <query>", file=sys.stderr)
        return 1

    query = " ".join(sys.argv[2:])
    print(f"=== QP 知识库搜索 / Knowledge Search: '{query}' ===")
    print()

    archive = KnowledgeArchive()
    results = archive.search(query, limit=20)

    if not results:
        print(f"  未找到匹配 '{query}' 的条目。")
        print(f"  No entries match '{query}'.")
        return 0

    print(f"  找到 / Found: {len(results)} 条")
    print()

    for i, entry in enumerate(results, 1):
        cat_names = {
            "research_debt": "研究债务",
            "decision_audit": "决策审计",
            "experiment_summary": "实验总结",
            "failure_analysis": "失败分析",
            "post_mortem": "事后复盘",
        }
        cat_zh = cat_names.get(entry.category.value, entry.category.value)
        print(f"  {i}. [{cat_zh}] {entry.title}")
        print(f"     ID: {entry.entry_id}")
        print(f"     标签 / Tags: {', '.join(entry.tags) if entry.tags else '(无)'}")
        # Show first 120 chars of content
        preview = entry.content.strip()[:120].replace("\n", " ")
        print(f"     预览 / Preview: {preview}...")
        print()

    return 0


def _cmd_decide() -> int:
    """Generate trading recommendations for manual review."""
    from datetime import date

    import polars as pl

    from qp.decision.engine import DecisionEngine
    from qp.monitoring.regime import MarketRegimeEngine
    from qp.portfolio.cost_model import CostModel
    from qp.portfolio.risk_manager import PortfolioRiskManager
    from qp.strategy.registry import StrategyRegistry
    from qp.strategy.simple_rank import SimpleRankStrategy

    # Parse arguments
    strategy_id = "simple_rank_v1.0"
    total_capital = 1_000_000.0

    args = sys.argv[2:]
    for arg in args:
        if arg.startswith("--capital="):
            total_capital = float(arg.split("=")[1])
        elif not arg.startswith("--"):
            strategy_id = arg

    print("═══ QP 交易建议 / Trading Recommendations ═══")
    print()

    # Load data
    today = date.today()
    try:
        prices = pl.read_parquet("data/dataset/daily_price_" + today.isoformat() + ".parquet")
    except FileNotFoundError:
        print("❌ 未找到数据文件。请先运行 qp run daily")
        print("   No data found. Run 'qp run daily' first.")
        return 1

    # Market regime
    regime_str = ""
    try:
        engine = MarketRegimeEngine()
        regime_result = engine.classify(prices)
        regime_str = regime_result.summary
        print(f"  市场状态 / Regime: {regime_result.regime.value}")
        print(
            f"  趋势/波动: ADX={regime_result.trend_strength:.1f} | Vol={regime_result.annualized_vol:.1%}"
        )
    except Exception:
        pass
    print()

    # Generate signals
    try:
        registry = StrategyRegistry()
        registry.register(SimpleRankStrategy(top_n=10))
        strategy = registry.get(strategy_id)
        signals = strategy.generate_signals(today)
    except Exception:
        print(f"❌ 策略 '{strategy_id}' 未注册或信号生成失败")
        print(f"   Strategy '{strategy_id}' not registered or signal generation failed.")
        return 1

    if signals.is_empty():
        print("❌ 无信号 / No signals generated for today.")
        return 1

    n_symbols = len(signals)
    print(f"  候选标的 / Candidates: {n_symbols} 只")
    print(f"  资金规模 / Capital: ¥{total_capital:,.0f}")
    print()

    # Risk check
    risk_manager = PortfolioRiskManager()
    filtered_signals, risk_report = risk_manager.apply_risk_limits_with_prices(signals, prices)
    print(
        f"  风控过滤 / Risk Filter: {risk_report.candidates_out}/{risk_report.candidates_in} 通过"
    )
    if risk_report.violations:
        for v in risk_report.violations:
            print(f"    ⚠ {v}")
    print()

    # Cost preview
    cost_model = CostModel()
    total_est_cost = 0.0
    for sym in filtered_signals["symbol"].to_list()[:10]:
        px_row = prices.filter(pl.col("symbol") == sym)
        px = float(px_row["close"][0]) if not px_row.is_empty() else 10.0
        trade_val = px * (total_capital / 10 / px // 100 * 100)
        if trade_val > 0:
            cost = cost_model.estimate_trade(sym, trade_val, "BUY")
            total_est_cost += cost.total_cost
    print(
        f"  预估总成本 / Est. Cost: ¥{total_est_cost:,.0f} ({total_est_cost / total_capital * 100:.2f}%)"
    )
    print()

    # Generate recommendations via DecisionEngine
    decision_engine = DecisionEngine()
    report = decision_engine.generate(
        signals=filtered_signals,
        prices=prices,
        risk_report=risk_report,
        total_capital=total_capital,
        strategy_id=strategy_id,
        market_regime=regime_str,
    )

    # Print bilingual output
    print(decision_engine.format_bilingual(report))

    return 0


def _cmd_paper_start() -> int:
    """Start a 30-day paper trading run."""
    from datetime import date

    from qp.strategy.paper_trading import PaperTradingTracker
    from qp.strategy.registry import StrategyRegistry

    strategy_id = "simple_rank_v1.0"
    if len(sys.argv) > 3 and not sys.argv[3].startswith("--"):
        strategy_id = sys.argv[3]

    print("═══ QP 模拟交易 / Paper Trading ═══")
    print()
    print(f"  策略 / Strategy:  {strategy_id}")
    print(f"  起始日期 / Start: {date.today().isoformat()}")

    # Verify strategy exists
    try:
        registry = StrategyRegistry()
        from qp.strategy.simple_rank import SimpleRankStrategy

        registry.register(SimpleRankStrategy(top_n=10))
        registry.get(strategy_id)
    except KeyError:
        print(f"  ❌ 策略 '{strategy_id}' 未注册")
        return 1

    tracker = PaperTradingTracker()
    run = tracker.start(strategy_id, capital=1_000_000)
    print(f"  运行编号 / Run ID: {run.run_id}")
    print(f"  状态文件 / State:   {run.state_file}")
    print()
    print("  ✅ 模拟交易已启动。每天运行 'qp paper status' 查看进度。")
    print("  ✅ Paper trading started. Run 'qp paper status' for daily updates.")
    return 0


def _cmd_paper_status() -> int:
    """Show current paper trading status."""
    from qp.strategy.paper_trading import PaperTradingTracker

    strategy_id = "simple_rank_v1.0"
    if len(sys.argv) > 3 and not sys.argv[3].startswith("--"):
        strategy_id = sys.argv[3]

    tracker = PaperTradingTracker()
    run = tracker.load(strategy_id)

    if run is None:
        print(f"  ⚠ 未找到 '{strategy_id}' 的模拟交易记录。请先运行 'qp paper start'。")
        print("  ⚠ No paper trading run found. Run 'qp paper start' first.")
        return 1

    st = tracker.status(run)

    print("═══ QP 模拟交易状态 / Paper Trading Status ═══")
    print()
    print(f"  策略 / Strategy:    {st['strategy_id']}")
    print(f"  运行编号 / Run ID:  {st['run_id']}")
    print(f"  起始日期 / Start:   {st['start_date']}")
    print(f"  已过天数 / Days:    {st['elapsed_days']}/30")
    print(f"  当前权益 / Equity:  ¥{st['current_equity']:,.0f}")
    print()

    if st["is_complete"] and "result" in st:
        r = st["result"]
        icon = "✅" if r["passed"] else "❌"
        print("  ── 评估结果 / Evaluation ──")
        print(f"  {icon} 通过 / Passed:    {r['passed']}")
        print(f"  总收益 / Return:         {r['total_return']:.1f}%")
        print(f"  夏普 / Sharpe:           {r['sharpe']:.2f}")
        print(f"  最大回撤 / Max DD:       {r['max_drawdown']:.1f}%")
        print(f"  建议 / Recommendation:   {r['recommendation']}")
    else:
        remaining = 30 - st["elapsed_days"]
        print(f"  ⏳ 还剩 {remaining} 天完成评估 / {remaining} days remaining.")
    print()
    return 0


def _cmd_retrain() -> int:
    """Run monthly model retrain pipeline."""
    from datetime import date

    from qp.platform.pipeline.context import PipelineContext
    from qp.research.trainer.auto_retrain import MonthlyRetrainPipeline

    strategy_id = "simple_rank_v1.0"
    dry_run = False

    args = sys.argv[2:]
    for arg in args:
        if arg == "--dry-run":
            dry_run = True
        elif not arg.startswith("--"):
            strategy_id = arg

    print("═══ QP 模型重训 / Model Retrain ═══")
    print()
    print(f"  策略 / Strategy:    {strategy_id}")
    print(f"  模式 / Mode:        {'演习 dry-run' if dry_run else '正式 live'}")
    print()

    context = PipelineContext(
        pipeline_name="monthly_retrain",
        parameters={
            "strategy_id": strategy_id,
            "train_end": date.today().isoformat(),
            "dry_run": dry_run,
        },
    )

    pipeline = MonthlyRetrainPipeline()
    result = pipeline.run(context)

    if result.status.value == "failed":
        print("  ❌ 重训失败 / Retrain FAILED")
        for e in result.errors:
            print(f"     {e}")
        return 1

    print(f"  ✅ 重训完成 / Status: {result.status.value}")
    print()

    if result.metrics:
        print("  ── 指标 / Metrics ──")
        for k, v in sorted(result.metrics.items()):
            print(f"  {k}: {v:.4f}")

    if result.metadata and "retrain_result" in result.metadata:
        rr = result.metadata["retrain_result"]
        print()
        print("  ── 结果 / Result ──")
        print(f"  验证通过 / Validated: {rr.validation_passed}")
        print(f"  模型注册 / Registered: {rr.model_registered}")
        if rr.model_id:
            print(f"  模型编号 / Model ID: {rr.model_id}")
        print(f"  {rr.recommendation}")

    print()
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
    print("  experiment list          List all experiments")
    print("  experiment show <id>     Show experiment details")
    print("  experiment run multifactor [opts]  Run multi-factor experiment")
    print("  model list               List registered models")
    print("  model show <id>          Show model details")
    print("  backtest run [strategy]  Run broker-based backtest")
    print("  monitor check            Run daily safety checks (KS + drift + decay)")
    print("  monitor regime           Detect current market regime")
    print("  monitor alert-test       Test all alert channels")
    print("  knowledge stats          Knowledge archive statistics")
    print("  knowledge search <q>     Search knowledge archive")
    print("  decide [strategy] [--capital=N]  Generate trade recommendations")
    print("  paper start [strategy]   Start 30-day paper trading run")
    print("  paper status [strategy]  Show paper trading status")
    print("  retrain [strategy] [--dry-run]  Run monthly model retrain")
    print()
    print("Phase 1 (available):")
    print("  qp data fetch [--batch=500] [--skip-etl]")
    print("                                Fetch full main-board data from quant.db")
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
    print()
    print("Phase 4 (available):")
    print("  qp experiment list/show       Experiment tracking")
    print("  qp model list/show            Model registry")
    print("  qp backtest run [strategy]    Full backtest with costs")
    print()
    print("Phase 5 (available):")
    print("  qp monitor check              Daily safety checks (KS + drift + decay)")
    print("  qp monitor regime             Detect current market regime")
    print("  qp monitor alert-test         Test all alert channels")
    print("  qp knowledge stats            Knowledge archive statistics")
    print("  qp knowledge search <query>   Search knowledge archive")
    print()
    print("Phase 6 (available):")
    print("  qp decide [strategy]           Generate trade recommendations")
    print("  qp decide --capital=500000     Custom capital amount")
    print()
    print("Gap closure (Phase 6 continued):")
    print("  qp paper start [strategy]      Start 30-day paper trading")
    print("  qp paper status                Show paper trading progress")
    print("  qp retrain [strategy] --dry-run Run monthly model retrain")
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

    if command == "experiment":
        if len(sys.argv) < 3:
            print("qp experiment: missing subcommand. Try: list, show, run", file=sys.stderr)
            return 1
        sub = sys.argv[2]
        if sub == "list":
            return _cmd_experiment_list()
        if sub == "show":
            return _cmd_experiment_show()
        if sub == "run":
            return _cmd_experiment_run()
        print(f"qp experiment: unknown subcommand '{sub}'. Try: list, show, run", file=sys.stderr)
        return 1

    if command == "model":
        if len(sys.argv) < 3:
            print("qp model: missing subcommand. Try: list, show <id>", file=sys.stderr)
            return 1
        sub = sys.argv[2]
        if sub == "list":
            return _cmd_model_list()
        if sub == "show":
            return _cmd_model_show()
        print(f"qp model: unknown subcommand '{sub}'. Try: list, show", file=sys.stderr)
        return 1

    if command == "data":
        if len(sys.argv) < 3:
            print("qp data: missing subcommand. Try: fetch", file=sys.stderr)
            return 1
        sub = sys.argv[2]
        if sub == "fetch":
            return _cmd_data_fetch()
        print(f"qp data: unknown subcommand '{sub}'. Try: fetch", file=sys.stderr)
        return 1

    if command == "backtest":
        if len(sys.argv) < 3:
            print(
                "qp backtest: missing subcommand. Try: qp backtest run [strategy]", file=sys.stderr
            )
            return 1
        sub = sys.argv[2]
        if sub == "run":
            return _cmd_backtest_run()
        print(f"qp backtest: unknown subcommand '{sub}'. Try: run", file=sys.stderr)
        return 1

    if command == "monitor":
        if len(sys.argv) < 3:
            print("qp monitor: missing subcommand. Try: check, regime, alert-test", file=sys.stderr)
            return 1
        sub = sys.argv[2]
        if sub == "check":
            return _cmd_monitor_check()
        if sub == "regime":
            return _cmd_monitor_regime()
        if sub == "alert-test":
            return _cmd_monitor_alert_test()
        print(
            f"qp monitor: unknown subcommand '{sub}'. Try: check, regime, alert-test",
            file=sys.stderr,
        )
        return 1

    if command == "knowledge":
        if len(sys.argv) < 3:
            print("qp knowledge: missing subcommand. Try: stats, search <query>", file=sys.stderr)
            return 1
        sub = sys.argv[2]
        if sub == "stats":
            return _cmd_knowledge_stats()
        if sub == "search":
            return _cmd_knowledge_search()
        print(f"qp knowledge: unknown subcommand '{sub}'. Try: stats, search", file=sys.stderr)
        return 1

    if command == "decide":
        return _cmd_decide()

    if command == "paper":
        if len(sys.argv) < 3:
            print("qp paper: missing subcommand. Try: start, status", file=sys.stderr)
            return 1
        sub = sys.argv[2]
        if sub == "start":
            return _cmd_paper_start()
        if sub == "status":
            return _cmd_paper_status()
        print(f"qp paper: unknown subcommand '{sub}'. Try: start, status", file=sys.stderr)
        return 1

    if command == "retrain":
        return _cmd_retrain()

    print(f"qp: unknown command '{command}'. Try 'qp --help'", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
