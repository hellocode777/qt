"""CLI command handlers for the "decide" group."""
from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from qp.decision.decision_package import DecisionPackage


def cmd_decide() -> int:
    """Load or generate daily DecisionPackage.

    Default: loads today's DecisionPackage from data/decisions/.
    Flags:
      --force    Re-run daily pipeline to generate a fresh DecisionPackage
      --review   Open today's DecisionPackage for human review
      --history  List all past decision packages
      --show ID  Display a specific DecisionPackage
    Legacy (without DecisionPackage): strategy_id + --capital
    """
    from datetime import date

    import polars as pl

    from qp.decision.decision_package import DecisionPackage
    from qp.decision.engine import DecisionEngine
    from qp.monitoring.regime import MarketRegimeEngine
    from qp.portfolio.cost_model import CostModel
    from qp.portfolio.risk_manager import PortfolioRiskManager
    from qp.strategy.registry import StrategyRegistry
    from qp.strategy.simple_rank import SimpleRankStrategy

    today = date.today()

    # Parse flags
    force = False
    review = False
    show_history = False
    show_id = ""
    strategy_id = "simple_rank_v1.0"
    total_capital = 1_000_000.0

    args = sys.argv[2:]
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--force":
            force = True
        elif arg == "--review":
            review = True
        elif arg == "--history":
            show_history = True
        elif arg.startswith("--show="):
            show_id = arg.split("=", 1)[1]
        elif arg == "--show" and i + 1 < len(args):
            i += 1
            show_id = args[i]
        elif arg.startswith("--capital="):
            total_capital = float(arg.split("=")[1])
        elif not arg.startswith("--"):
            strategy_id = arg
        i += 1

    # ── --history: list all past decisions ──
    if show_history:
        return cmd_decide_history()

    # ── --show: display a specific package ──
    if show_id:
        return cmd_decide_show(show_id)

    # ── --review: interactive human review ──
    if review:
        return cmd_decide_review(today)

    # ── Default / --force: load or generate DecisionPackage ──
    if not force:
        try:
            pkg = DecisionPackage.load_latest()
            if pkg is not None:
                print_decision_package_summary(pkg)
                return 0
        except Exception:
            pass  # Fall through to legacy/generate

    # ── --force or no cached package: run daily pipeline ──
    if force:
        print("⏳ 重新运行每日管道 / Re-running daily pipeline...")
        from qp.pipeline.daily_pipeline import DailyPipeline
        from qp.platform.pipeline.context import PipelineContext

        context = PipelineContext(
            pipeline_name="daily",
            parameters={"capital": total_capital},
        )
        pipeline = DailyPipeline()
        result = pipeline.run(context)
        if result.status.value != "success":
            print(f"❌ Pipeline failed: {result.errors}")
            return 1
        # Reload the newly created package
        try:
            pkg = DecisionPackage.load_latest()
            if pkg is not None:
                print_decision_package_summary(pkg)
                return 0
        except Exception:
            pass

    # ── Fallback: legacy live generate (no DecisionPackage) ──
    print("═══ QP 交易建议 / Trading Recommendations ═══")
    print()

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
    print(decision_engine.format_bilingual(report))

    return 0


# ------------------------------------------------------------------
# DecisionPackage helpers
# ------------------------------------------------------------------


def print_decision_package_summary(pkg: DecisionPackage) -> None:
    """Print a DecisionPackage summary for terminal display."""

    print("═══ QP 决策包 / Decision Package ═══")
    print(f"  编号 / ID:       {pkg.package_id}")
    print(f"  日期 / Date:      {pkg.date}")
    print(f"  生成时间 / Time:  {pkg.generated_at[:19]}")
    print()

    print("  ── 数据血缘 / Lineage ──")
    print(f"  数据集: {pkg.lineage.dataset_name} v{pkg.lineage.dataset_version}")
    print(f"  覆盖: {pkg.lineage.dataset_symbols} stocks, {pkg.lineage.dataset_rows:,} rows")
    print()

    print("  ── 市场状态 / Regime ──")
    print(f"  状态: {pkg.regime.regime} (置信度 {pkg.regime.confidence:.0%})")
    print(f"  建议敞口: {pkg.regime.suggested_exposure:.0%}")
    print()

    print("  ── 策略执行 / Strategies ──")
    for sid, count in pkg.strategy_signals.items():
        print(f"  {sid}: {count} signals")
    print(f"  融合方式: {pkg.ensemble_method}")
    print()

    # Validation
    if pkg.validation:
        print("  ── 验证状态 / Validation ──")
        for sid, v in pkg.validation.items():
            icon = "✅" if v.get("passed") else "❌"
            print(
                f"  {icon} {sid}: {v.get('score', 0)}/100 ({v.get('rules_failed', 0)}/{v.get('rules_total', 0)} failed)"
            )
        print()

    # Risk audit
    ra = pkg.risk_audit
    print("  ── 风控审计 / Risk Audit ──")
    print(f"  候选: {ra.candidates_in} → {ra.candidates_out}")
    if ra.dropped_symbols:
        print(f"  剔除: {', '.join(ra.dropped_symbols)}")
    if ra.entries:
        print(f"  违规项: {len(ra.entries)}")
        for e in ra.entries[:5]:
            print(f"    ⚠ {e.violation_type}: {e.detail}")
    print()

    # Top recommendations
    report = pkg.report
    if not report.is_empty:
        print("  ── 建议交易 / Top Picks ──")
        for i, rec in enumerate(report.recommendations[:5], 1):
            warnings = " ⚠" if rec.risk_warnings else ""
            print(
                f"  {i}. {rec.symbol} {rec.action} ¥{rec.estimated_price:.2f} x {rec.quantity_shares} ({rec.target_weight_pct:.1f}%){warnings}"
            )
        print(f"  ... 共 {report.n_buys} 条建议")
        print(f"  预估总成本: {pkg.estimated_cost_pct:.2f}%")
    print()

    # Human review status
    hr = pkg.human_review
    print("  ── 人工审核 / Human Review ──")
    if hr.reviewed:
        print(f"  ✅ 已审核 by {hr.reviewer}")
        if hr.executed:
            print(f"  ✅ 已执行 at {hr.execution_time}")
    else:
        print("  ❌ 待审核 — 运行 'qp decide --review' 进行审核")
    print()

    # Commands hint
    print("  操作: qp decide --force | qp decide --review | qp decide --history")


def cmd_decide_history() -> int:
    """List all past decision packages from index.json."""
    from qp.decision.decision_package import DecisionPackage

    entries = DecisionPackage.load_index()
    if not entries:
        print("(empty) — 暂无决策记录。运行 qp run daily 生成第一条。")
        return 0

    print(
        f"{'Package ID':<32s} {'Date':<12s} {'Regime':<14s} {'Recs':>5s} {'Cost%':>7s} {'Risk':>6s} {'Reviewed':>9s}"
    )
    print("-" * 95)
    for e in entries:
        risk_icon = "✅" if e.get("risk_passed") else "⚠️"
        rev_icon = "✅" if e.get("human_reviewed") else "❌"
        print(
            f"{e.get('package_id', ''):<32s} "
            f"{e.get('date', ''):<12s} "
            f"{e.get('regime', ''):<14s} "
            f"{e.get('n_recommendations', 0):>5d} "
            f"{e.get('estimated_cost_pct', 0):>6.2f}% "
            f"{risk_icon:<6s} "
            f"{rev_icon:<9s}"
        )
    print(f"\n共 {len(entries)} 条记录 / {len(entries)} decisions total")
    return 0


def cmd_decide_show(package_id: str) -> int:
    """Display a specific DecisionPackage."""

    from qp.decision.decision_package import DECISIONS_DIR, DecisionPackage

    # Support both full ID and short suffix
    json_path = DECISIONS_DIR / f"{package_id}.json"
    if not json_path.exists():
        # Try glob match
        candidates = sorted(DECISIONS_DIR.glob(f"*{package_id}*.json"))
        if candidates:
            json_path = candidates[0]
        else:
            print(f"❌ DecisionPackage '{package_id}' not found in {DECISIONS_DIR}")
            return 1

    try:
        pkg = DecisionPackage.from_json(json_path)
        print_decision_package_summary(pkg)
        print(f"\n  完整报告: data/decisions/{pkg.date}.md")
        return 0
    except Exception as exc:
        print(f"❌ Failed to load: {exc}")
        return 1


def cmd_decide_review(today: object) -> int:
    """Interactive human review of today's DecisionPackage."""
    from datetime import datetime

    from qp.decision.decision_package import DecisionPackage

    pkg = DecisionPackage.load_latest()
    if pkg is None:
        print("❌ 今天还没有决策包。请先运行 qp run daily 或 qp decide --force")
        print("   No DecisionPackage for today. Run 'qp run daily' first.")
        return 1

    print_decision_package_summary(pkg)

    print("── 人工审核 / Human Review ──")
    print()

    # Prompt user
    try:
        ans = input("  审核通过? [y/n]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\n  已取消。")
        return 0

    if ans not in ("y", "yes"):
        print("  已标记为未通过 / Marked as rejected.")
        pkg.human_review.reviewed = True
        pkg.human_review.reviewer = "user"
        pkg.human_review.notes = "REJECTED — manual review failed"
        pkg.human_review.executed = False
    else:
        try:
            notes = input("  备注 / Notes: ").strip()
        except (EOFError, KeyboardInterrupt):
            notes = ""

        pkg.human_review.reviewed = True
        pkg.human_review.reviewer = "user"
        pkg.human_review.notes = notes
        pkg.human_review.executed = True
        pkg.human_review.execution_time = datetime.now().isoformat()

    # Save updated package
    json_path = pkg.to_json()
    pkg.to_markdown()
    pkg.update_index()

    print()
    status = "✅ 已通过并标记执行" if pkg.human_review.executed else "⚠️ 已标记未通过"
    print(f"  {status}")
    print(f"  已保存至 / Saved to: {json_path}")
    return 0

