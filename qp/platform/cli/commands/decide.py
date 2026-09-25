"""CLI command handlers for the "decide" group."""

from __future__ import annotations

from typing import TYPE_CHECKING

from qp.shared.paths import resolve_daily_price_path
from qp.shared.time import today_cn

if TYPE_CHECKING:
    from qp.decision.decision_package import DecisionPackage


def cmd_decide(
    force: bool = False,
    review: bool = False,
    history: bool = False,
    show: str = "",
    capital: float = 0.0,
    action: str = "",
    notes: str = "",
    strategy_id: str = "simple_rank_v1.0",
) -> int:
    """Load or generate daily DecisionPackage.

    Default: loads today's DecisionPackage from data/decisions/.
    Flags:
      --force    Re-run daily pipeline to generate a fresh DecisionPackage
      --review   Open today's DecisionPackage for human review
      --history  List all past decision packages
      --show ID  Display a specific DecisionPackage
    Legacy (without DecisionPackage): strategy_id + --capital
    """

    import polars as pl

    from qp.decision.decision_package import DecisionPackage
    from qp.decision.engine import DecisionEngine
    from qp.monitoring.regime import MarketRegimeEngine
    from qp.portfolio.cost_model import CostModel
    from qp.portfolio.risk_manager import PortfolioRiskManager
    from qp.strategy.registry import StrategyRegistry
    from qp.strategy.simple_rank import SimpleRankStrategy

    today = today_cn()
    total_capital = capital if capital > 0 else 100_000.0
    show_history = history
    show_id = show

    # ── --history: list all past decisions ──
    if show_history:
        return cmd_decide_history()

    # ── --show: display a specific package ──
    if show_id:
        return cmd_decide_show(show_id)

    # ── --review [--action approve|reject|modify] [--notes ...]: human review ──
    if review:
        return cmd_decide_review(today, action=action, notes=notes)

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
        prices = pl.read_parquet(str(resolve_daily_price_path()))
    except FileNotFoundError as e:
        print(f"❌ 未找到价格数据 / No daily price data: {e}")
        print("   请先运行 qp run daily / Run 'qp run daily' first.")
        return 1

    # Market regime
    regime_str = ""
    try:
        engine = MarketRegimeEngine()
        regime_result = engine.classify_panel(prices)
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
        registry.register(SimpleRankStrategy(top_n=10), persist=False)
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

    # Human review status (P0.4 — state-machine aware)
    hr = pkg.human_review
    status = pkg.status
    print("  ── 人工审核 / Human Review ──")
    print(f"  状态: {status.label} ({status.value})")
    if hr.reviewed:
        print(f"  审核人: {hr.reviewer}")
    if hr.notes:
        print(f"  备注: {hr.notes}")
    if hr.status_history:
        print(f"  状态历史: {len(hr.status_history)} 条记录")
        for entry in hr.status_history[-3:]:
            print(f"    {entry['from_status']} → {entry['to_status']} ({entry['timestamp'][:19]})")
    if not hr.reviewed:
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
        f"{'Package ID':<32s} {'Date':<12s} {'Regime':<14s} "
        f"{'Recs':>5s} {'Cost%':>7s} {'Risk':>6s} {'Status':<12s}"
    )
    print("-" * 100)
    for e in entries:
        risk_icon = "✅" if e.get("risk_passed") else "⚠️"
        status_val = e.get("status", "pending")
        status_label = _status_label(status_val)
        print(
            f"{e.get('package_id', ''):<32s} "
            f"{e.get('date', ''):<12s} "
            f"{e.get('regime', ''):<14s} "
            f"{e.get('n_recommendations', 0):>5d} "
            f"{e.get('estimated_cost_pct', 0):>6.2f}% "
            f"{risk_icon:<6s} "
            f"{status_label:<12s}"
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
        print(f"\n  完整报告: {DECISIONS_DIR}/{pkg.date}.md")
        return 0
    except Exception as exc:
        print(f"❌ Failed to load: {exc}")
        return 1


def cmd_decide_review(
    today: object,
    action: str = "",
    notes: str = "",
) -> int:
    """Interactive human review of today's DecisionPackage.

    Args:
        today: Current date.
        action: If set, skip interactive prompt and use this action.
                One of: approve, reject, modify.
        notes: Optional review notes.
    """
    from qp.decision.decision_package import DecisionPackage

    pkg = DecisionPackage.load_latest()
    if pkg is None:
        print("❌ 今天还没有决策包。请先运行 qp run daily 或 qp decide --force")
        print("   No DecisionPackage for today. Run 'qp run daily' first.")
        return 1

    # If --action is provided, execute directly (non-interactive)
    if action:
        return _execute_review_action(pkg, action, notes)

    # Interactive mode
    print_decision_package_summary(pkg)

    print("── 人工审核 / Human Review ──")
    print(f"  当前状态: {pkg.status.label} ({pkg.status.value})")
    print()

    if not pkg.human_review.is_pending and pkg.status.value != "modified":
        print("  ⚠️ 当前状态不支持审核 (需为待审核或已修改状态)")
        print(f"     当前: {pkg.status.label}")
        print("     可用操作: qp decide --history 查看历史")
        return 1

    # Show available actions
    print("  可选操作:")
    print("    [a] 批准 / Approve")
    print("    [r] 驳回 / Reject")
    print("    [m] 修改 / Modify")
    print()

    try:
        ans = input("  选择操作 [a/r/m]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\n  已取消。")
        return 0

    action_map = {
        "a": "approve",
        "y": "approve",  # legacy compat
        "yes": "approve",
        "r": "reject",
        "n": "reject",  # legacy compat
        "no": "reject",
        "m": "modify",
    }
    resolved = action_map.get(ans, "")
    if not resolved:
        print(f"  ❌ 无效操作: {ans}")
        return 1

    # Get notes
    if resolved == "modify":
        try:
            notes = input("  修改说明 / Modification notes: ").strip()
        except (EOFError, KeyboardInterrupt):
            notes = ""
    elif resolved == "reject":
        try:
            notes = input("  驳回原因 / Rejection reason (可选): ").strip()
        except (EOFError, KeyboardInterrupt):
            notes = ""
    else:
        try:
            notes = input("  备注 / Notes (可选): ").strip()
        except (EOFError, KeyboardInterrupt):
            notes = ""

    return _execute_review_action(pkg, resolved, notes)


def _execute_review_action(
    pkg: DecisionPackage,
    action: str,
    notes: str,
) -> int:
    """Execute a review action using the state machine, then save."""
    from qp.decision.state_machine import DecisionStateError

    try:
        if action == "approve":
            pkg.approve(reviewer="cli", notes=notes)
        elif action == "reject":
            pkg.reject(reviewer="cli", notes=notes)
        elif action == "modify":
            pkg.modify(reviewer="cli", notes=notes)
        else:
            print(f"  ❌ 未知操作: {action}")
            return 1
    except DecisionStateError as e:
        print(f"  ❌ 状态转换失败: {e}")
        return 1

    # Save
    json_path = pkg.to_json()
    pkg.to_markdown()
    pkg.update_index()

    # P2.3: Auto-apply positions on approve (SELL closes + BUY opens)
    if action == "approve":
        try:
            from qp.decision.position_ledger import PositionLedger

            ledger = PositionLedger()
            closed = ledger.close_from_decision(pkg)
            positions = ledger.open_from_decision(pkg)
            if closed:
                print(f"  📉 自动平仓 {len(closed)} 条持仓")
            if positions:
                print(f"  📊 自动创建 {len(positions)} 条持仓记录")
        except Exception as exc:
            print(f"  ⚠️ 持仓同步失败: {exc}")

    labels = {
        "approve": "✅ 已批准",
        "reject": "🚫 已驳回",
        "modify": "📝 已标记修改",
    }
    print(f"\n  {labels.get(action, action)} / {action}")
    print(f"  新状态: {pkg.status.label}")
    if notes:
        print(f"  备注: {notes}")
    print(f"  已保存至 / Saved to: {json_path}")
    return 0


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _parse_flag_arg(args: list[str], flag: str, default: str = "") -> str:
    """Extract a flag value from args list.

    Supports both --flag=value and --flag value forms.
    Removes consumed args in-place.
    """
    for i, arg in enumerate(args):
        if arg.startswith(f"{flag}="):
            args.pop(i)
            return arg.split("=", 1)[1]
        if arg == flag and i + 1 < len(args):
            args.pop(i)
            return args.pop(i)
    return default


def _status_label(status_value: str) -> str:
    """Return a compact Chinese label for a status value."""
    labels = {
        "pending": "待审核",
        "approved": "已批准",
        "rejected": "已驳回",
        "modified": "已修改",
        "partially_executed": "部分执行",
        "monitoring": "监控中",
        "closed": "已关闭",
    }
    return labels.get(status_value, status_value)
