"""CLI command handlers for the "scheduler" group."""

from __future__ import annotations

import contextlib
import signal
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from qp.platform.runtime.application import Application


def format_decision_email(data: dict, date_str: str) -> str:
    """Format a DecisionPackage JSON into a readable email body."""
    lines: list[str] = []
    lines.append("QP 每日投资决策报告")
    lines.append(f"日期: {date_str}")
    lines.append("=" * 45)

    # Market regime
    regime = data.get("regime", {})
    if regime:
        lines.append("")
        lines.append("【市场状态】")
        lines.append(f"  状态: {regime.get('regime', 'N/A')}")
        if regime.get("suggested_exposure"):
            lines.append(f"  建议敞口: {regime['suggested_exposure']:.0%}")

    # Strategy signals
    signals = data.get("strategy_signals", {})
    if signals:
        lines.append("")
        lines.append("【策略信号】")
        for sid, count in signals.items():
            lines.append(f"  {sid}: {count} 个信号")

    # Top N stocks
    effective_n = data.get("effective_top_n", 0)
    if effective_n:
        lines.append(f"  有效持仓数: {effective_n}")

    # Risk audit
    risk = data.get("risk_audit", {})
    if risk:
        lines.append("")
        lines.append("【风控审计】")
        passed = risk.get("passed", True)
        lines.append(f"  通过: {'✅' if passed else '❌'}")
        violations = risk.get("violations", [])
        for v in violations[:5]:
            lines.append(f"  ⚠ {v}")

    # Decision report — trade recommendations
    report = data.get("report", {})
    if report:
        lines.append("")
        n_buys = report.get("n_buys", 0)
        n_sells = report.get("n_sells", 0)
        lines.append(f"【交易建议】买入 {n_buys} 只 / 卖出 {n_sells} 只")
        if report.get("total_capital"):
            lines.append(f"  总资金: ¥{report['total_capital']:,.0f}")

        recommendations = report.get("recommendations", [])
        if recommendations:
            lines.append("")
            for rec in recommendations[:20]:
                symbol = rec.get("symbol", "?")
                action = rec.get("action", "?")
                reason = rec.get("reason", "")
                weight = rec.get("target_weight_pct", 0)
                qty = rec.get("quantity_shares", 0)
                price = rec.get("estimated_price", 0)
                cost = rec.get("estimated_cost", 0)
                warnings = rec.get("risk_warnings", [])

                action_icon = "买入" if action == "BUY" else "卖出" if action == "SELL" else action
                qty_str = f" × {qty}股" if qty else ""
                price_str = f" @ ¥{price:.2f}" if price else ""
                cost_str = f"  约¥{cost:.0f}" if cost else ""

                lines.append(
                    f"  {action_icon:<4s} {symbol}  权重{weight:.0f}%{qty_str}{price_str}{cost_str}"
                )
                if reason:
                    lines.append(f"       理由: {reason}")
                for w in warnings[:2]:
                    lines.append(f"       ⚠ {w}")
        else:
            lines.append("  (无具体交易建议，参考 DecisionPackage 详情)")

    # Estimated cost
    cost = data.get("estimated_cost_pct", 0.0)
    if cost:
        lines.append("")
        lines.append(f"【预估成本】{cost:.2%}")

    # Lineage
    lineage = data.get("lineage", {})
    if lineage:
        lines.append("")
        lines.append("【数据血缘】")
        lines.append(f"  数据集版本: {lineage.get('dataset_version', 'N/A')}")

    lines.append("")
    lines.append("-" * 45)
    lines.append("完整报告: data/decisions/")
    lines.append("人工审核: qp decide --review")
    lines.append("⚠️ 本报告仅供学习参考，不构成投资建议。")

    return "\n".join(lines)


def cmd_scheduler_start(app: Application | None = None) -> int:
    """Start the background job scheduler for daily automation.

    Registers and starts:
      - monitor_check:     KillSwitchPipeline full    (weekdays 09:07)
      - retrain_notify:    Check retrain signals      (weekdays 09:17)
      - pre_close_check:   KillSwitchPipeline fast    (weekdays 16:53)
      - daily_pipeline:    DailyPipeline              (weekdays 18:00)
      - email_report:      Email DecisionPackage      (weekdays 18:30)

    When an Application is provided (via CLI main), the scheduler uses
    the runtime's logger, config, and signal handling (ADR-012).

    Runs in foreground until Ctrl+C.
    """
    # Resolve logger: prefer runtime logger, fall back to print
    log = app.context.logger if app is not None else None

    from qp.platform.scheduler.job import Job
    from qp.platform.scheduler.scheduler import QPScheduler
    from qp.platform.scheduler.trigger import CronTrigger

    # Read timezone from config if available
    tz = "Asia/Shanghai"
    if app is not None:
        with contextlib.suppress(Exception):
            tz = app.context.config.scheduler.timezone

    scheduler = QPScheduler(timezone=tz)

    # Register scheduler with runtime for graceful shutdown
    if app is not None:
        app.context.scheduler = scheduler
        app.context.logger.info("Scheduler registered with runtime", module="scheduler")

    # Helper: create PipelineContext with runtime attached when available
    def _make_ctx(name: str, **params):
        from qp.platform.pipeline.context import PipelineContext

        if app is not None:
            return PipelineContext(pipeline_name=name, parameters=params, runtime=app.context)
        return PipelineContext(pipeline_name=name, parameters=params)

    def _build_model_decay_detector():
        """Create ModelDecayDetector using the first registered strategy's
        backtest IC as training reference (fallback 0.035)."""
        from qp.monitoring.model_decay import ModelDecayDetector

        training_ic = 0.035
        try:
            from qp.strategy.registry import StrategyRegistry

            reg = StrategyRegistry()
            for sid in reg.list_strategies():
                ic = reg.get_meta(sid).backtest_ic
                if ic > 0:
                    training_ic = float(ic)
                    break
        except Exception:
            pass
        return ModelDecayDetector(training_ic_mean=training_ic)

    def _build_strategy_monitor():
        """Build a StrategyMonitor seeded from persisted signal history.

        Returns None when no signal history exists — strategy health
        will simply be absent from the report instead of fabricated.
        """
        from pathlib import Path

        import polars as pl

        from qp.monitoring.strategy_monitor import StrategyMonitor

        path = Path("data/monitoring/online_signal_history.parquet")
        if not path.exists():
            return None
        df = pl.read_parquet(path)
        if df.is_empty():
            return None
        monitor = StrategyMonitor("aggregate")
        counts = df.group_by(["strategy_id", "date"]).len().sort("date")
        for row in counts.iter_rows(named=True):
            monitor.record_signal(str(row["date"]), n_signals=int(row["len"]))
        return monitor

    def _load_monitor_price_data():
        """Load per-symbol price dict for online rolling-IC monitoring.

        OnlineSignalMonitor.rolling_ic expects ``{symbol: DataFrame}``,
        NOT the flat frame — passing the flat frame silently disabled the
        realized-IC check (no ``.get(symbol)`` on a DataFrame).
        """
        from qp.pipeline.daily_pipeline import _load_price_data

        try:
            prices_dict, _flat = _load_price_data()
            if prices_dict:
                return prices_dict
        except Exception:
            pass
        return {}

    # ── Watchdog: touch ping file for external monitoring (#12 fix) ──
    def watchdog_ping(job_name: str) -> None:
        from datetime import UTC, datetime
        from pathlib import Path

        ping_dir = Path("data/monitoring/watchdog")
        ping_dir.mkdir(parents=True, exist_ok=True)
        (ping_dir / f"{job_name}.ping").write_text(f"{datetime.now(UTC).isoformat()}\n")

    # ── Per-job log file ──
    from contextlib import contextmanager

    @contextmanager
    def job_log_sink(job_name: str):
        """Add a per-job Loguru file sink for the duration of the job.

        Logs go to ``logs/{date}/{job_name}.log``.  Old date directories
        (>7 days) are cleaned up on each run.
        """
        import shutil as _shutil
        from datetime import date as _date
        from datetime import timedelta as _td
        from pathlib import Path

        from loguru import logger as _loguru

        today_str = _date.today().isoformat()
        jobs_dir = Path("logs")
        day_dir = jobs_dir / today_str
        day_dir.mkdir(parents=True, exist_ok=True)

        # Clean up directories older than 7 days
        cutoff = _date.today() - _td(days=7)
        for d in jobs_dir.iterdir():
            if d.is_dir() and d.name != today_str:
                try:
                    if _date.fromisoformat(d.name) < cutoff:
                        _shutil.rmtree(d)
                except (ValueError, OSError):
                    pass  # skip non-date dirs / permission errors

        log_path = day_dir / f"{job_name}.log"
        sink_id = _loguru.add(
            str(log_path),
            level="DEBUG",
            format="{time:HH:mm:ss.SSS} | {level: <8} | {name: <32} | {message}",
            encoding="utf-8",
        )
        try:
            yield
        finally:
            _loguru.remove(sink_id)

    # ── Job 1: morning health check (09:07 on weekdays) ──
    def job_monitor_check() -> None:
        with job_log_sink("monitor_check"):
            from qp.knowledge.archive import KnowledgeArchive
            from qp.monitoring.kill_switch_pipeline import (
                KillSwitchPipeline,
                MonitorAction,
            )

            # Load price data so regime detection and online rolling-IC
            # monitoring receive real market data (previously the context
            # carried no price_data, so checks silently used defaults).
            # NOTE: rolling_ic needs the {symbol: DataFrame} dict, NOT the
            # flat frame — flat frames made the IC check never run.
            price_data = _load_monitor_price_data()

            # Load recent factor daily IC series so the KillSwitchPipeline's
            # factor-health sub-check actually runs (previously
            # factor_daily_ics was never populated → _check_factor_health
            # silently returned None).
            try:
                from qp.monitoring.factor_health_logger import FactorHealthLogger

                fh_logger = FactorHealthLogger()
                ic_by_factor: dict[str, list[float]] = {}
                for fname, sdf in fh_logger.load_all_ic_series().items():
                    # Last 60 IC days — enough for the health state machine
                    ics = sdf["ic"].tail(60).to_list()
                    if len(ics) >= 10:
                        ic_by_factor[fname] = ics
            except Exception:
                ic_by_factor = {}

            ctx = _make_ctx(
                "scheduled_monitor",
                price_data=price_data,
                factor_daily_ics=ic_by_factor,
                strategy_monitor=_build_strategy_monitor(),
            )
            pipeline = KillSwitchPipeline(
                knowledge_archive=KnowledgeArchive(),
                model_decay_detector=_build_model_decay_detector(),
            )
            result = pipeline.run(ctx)

            if result.status.value != "success":
                print(f"[scheduler] monitor_check FAILED: {result.errors}")
                return

            report = result.metadata.get("report")  # type: ignore[union-attr]
            if report is None:
                return

            action = report.action
            print(
                f"[scheduler] monitor_check: action={action.value} "
                f"regime={report.regime.regime.value if report.regime else '?'} "
                f"psi={report.psi_value:.3f} decay={report.model_decay_stage} "
                f"ks={'YES' if report.kill_switch_triggered else 'no'}"
            )
            if action in (MonitorAction.STOP, MonitorAction.PAUSE_BUY):
                print(f"[scheduler] ⚠️  EMERGENCY: {action.value} — review before trading!")

            # Consume pending retrain signals (#13 fix)
            try:
                from qp.monitoring.retrain_signal import RetrainSignalLogger

                rs_logger = RetrainSignalLogger()
                signals = rs_logger.load_history(days=7)
                actionable = [
                    s
                    for s in signals.iter_rows(named=True)
                    if s.get("action") not in ("NONE", "MONITOR")
                ]
                if actionable:
                    print(f"[scheduler] retrain_signals: {len(actionable)} actionable")
                    for s in actionable[:3]:
                        print(
                            f"  - [{s.get('trigger', '?')}] {s.get('strategy_name', '?')}: {s.get('action', '?')}"
                        )
            except Exception:
                pass

            watchdog_ping("monitor_check")

    scheduler.add_job(
        Job(
            name="monitor_check",
            task=job_monitor_check,
            trigger=CronTrigger(day_of_week="mon-fri", hour="9", minute="7"),
        )
    )

    # ── Job 2: retrain signal check + Telegram alert (09:17 on weekdays) ──
    def job_retrain_notify() -> None:
        """Check retrain_signals.parquet for actionable signals in last 7 days.

        If a signal requires retraining, send a Telegram alert reminding
        the operator to manually trigger retrain. Retraining is NOT automated
        because it requires data re-fetch, CV, and model registration — all
        of which need human oversight.
        """
        with job_log_sink("retrain_notify"):
            try:
                from qp.monitoring.retrain_signal import (
                    RetrainSignalLogger,
                )

                rs_logger = RetrainSignalLogger()
                signals = rs_logger.load_history(days=7)
                actionable = [
                    s
                    for s in signals.iter_rows(named=True)
                    if s.get("action") not in ("NONE", "MONITOR")
                ]

                if not actionable:
                    return  # Nothing to do

                # Build alert
                lines = [f"📢 Retrain Signal ({len(actionable)} actionable)"]
                for s in actionable[:5]:
                    lines.append(
                        f"  [{s.get('trigger', '?')}] {s.get('strategy_name', '?'):>24s} → "
                        f"{s.get('action', '?')}"
                    )
                lines.append(
                    f"  最近信号: {actionable[-1].get('message', '')[:80]}"
                    if len(actionable[-1].get("message", "")) > 0
                    else ""
                )

                alert_text = "\n".join(lines)
                print(f"[scheduler] retrain_notify:\n{alert_text}")

                # Send Email alert
                try:
                    from qp.monitoring.alerts import (
                        Alert,
                        AlertManager,
                        AlertSeverity,
                        EmailAlert,
                    )

                    email = EmailAlert()
                    if email.is_configured:
                        mgr = AlertManager()
                        mgr.add_channel(email)
                        mgr.send(
                            Alert(
                                severity=AlertSeverity.WARNING,
                                title="QP Retrain Signal",
                                message=alert_text,
                                source="retrain_notify",
                            )
                        )
                        print("[scheduler] retrain_notify: Email alert sent")
                except Exception:
                    pass  # Email is optional
            except Exception:
                pass

            watchdog_ping("retrain_notify")

    scheduler.add_job(
        Job(
            name="retrain_notify",
            task=job_retrain_notify,
            trigger=CronTrigger(day_of_week="mon-fri", hour="9", minute="17"),
        )
    )

    # ── Job 3: pre-close health gate (16:53 on weekdays) ──
    def job_pre_close_check() -> None:
        """收盘前快速检查，决定是否执行盘后策略."""
        with job_log_sink("pre_close_check"):
            from qp.knowledge.archive import KnowledgeArchive
            from qp.monitoring.kill_switch_pipeline import (
                KillSwitchPipeline,
                MonitorAction,
            )

            # Same real inputs as the morning check — this job previously
            # ran with an empty context (no price_data, no detector, no
            # monitor), so its report was all defaults.
            price_data = _load_monitor_price_data()
            try:
                from qp.monitoring.factor_health_logger import FactorHealthLogger

                fh_logger = FactorHealthLogger()
                ic_by_factor: dict[str, list[float]] = {}
                for fname, sdf in fh_logger.load_all_ic_series().items():
                    ics = sdf["ic"].tail(60).to_list()
                    if len(ics) >= 10:
                        ic_by_factor[fname] = ics
            except Exception:
                ic_by_factor = {}

            ctx = _make_ctx(
                "pre_close_check",
                price_data=price_data,
                factor_daily_ics=ic_by_factor,
                strategy_monitor=_build_strategy_monitor(),
            )
            pipeline = KillSwitchPipeline(
                knowledge_archive=KnowledgeArchive(),
                model_decay_detector=_build_model_decay_detector(),
            )
            result = pipeline.run(ctx)

            if result.status.value != "success":
                print(f"[scheduler] pre_close_check FAILED: {result.errors}")
                return

            report = result.metadata.get("report")  # type: ignore[union-attr]
            if report is None:
                return

            action = report.action
            if action in (MonitorAction.STOP,):
                print(
                    f"[scheduler] ⛔ pre_close_check: {action.value} — "
                    f"SKIPPING daily pipeline for safety!"
                )
                return

            print(
                f"[scheduler] pre_close_check: {action.value} — "
                f"regime={report.regime.regime.value if report.regime else '?'} "
                f"health={report.strategy_health.health_score:.0f if report.strategy_health else '?'}"
            )
            watchdog_ping("pre_close_check")

    scheduler.add_job(
        Job(
            name="pre_close_check",
            task=job_pre_close_check,
            trigger=CronTrigger(day_of_week="mon-fri", hour="16", minute="53"),
        )
    )

    # ── Job 4: daily decision pipeline (17:57 on weekdays) ──
    def job_daily_pipeline() -> None:
        with job_log_sink("daily_pipeline"):
            from datetime import date, timedelta

            from qp.pipeline.daily_pipeline import DailyPipeline

            # Fetch recent data — incremental merge with existing history
            recent_start = (date.today() - timedelta(days=5)).isoformat()
            ctx = _make_ctx("scheduled_daily", start_date=recent_start)
            pipeline = DailyPipeline()
            result = pipeline.run(ctx)
            status = result.status.value
            package_id = result.metadata.get("decision_package_id", "?")
            watchdog_ping("daily_pipeline")
            print(f"[scheduler] daily_pipeline: {status} → {package_id}")

    scheduler.add_job(
        Job(
            name="daily_pipeline",
            task=job_daily_pipeline,
            trigger=CronTrigger(day_of_week="mon-fri", hour="18", minute="0"),
        )
    )

    # ── Job 4.5: paper trading daily advance (18:05 on weekdays) ──
    def job_paper_trading() -> None:
        """Advance all active paper trading runs by one trading day.

        For each incomplete run in data/paper_trading/*_paper.json:
          1. Load latest market prices (same source as daily_pipeline).
          2. run_day() → execute that day's trades against real prices.
          3. When a run reaches 30 days, auto-evaluate:
             PASS → lifecycle SHADOW_PRODUCTION (paper_trading_checks
                    gate / human review continues to APPROVED per Rule 11)
             FAIL → lifecycle RESEARCH.
        """
        with job_log_sink("paper_trading"):
            from pathlib import Path

            from qp.pipeline.daily_pipeline import _load_price_data
            from qp.shared.types import StrategyLifecycle
            from qp.simulation.paper_trading import PaperTradingTracker
            from qp.strategy.registry import StrategyRegistry

            _, flat_prices = _load_price_data()
            if flat_prices.is_empty():
                print("[scheduler] paper_trading: no price data, skipping")
                watchdog_ping("paper_trading")
                return

            latest_date = str(flat_prices["trade_date"].max())
            tracker = PaperTradingTracker()
            state_dir = Path("data/paper_trading")

            runs = []
            for state_file in state_dir.glob("*_paper.json"):
                strategy_id = state_file.name[: -len("_paper.json")]
                run = tracker.load(strategy_id)
                if run is not None and not run.is_complete:
                    runs.append(run)
            if not runs:
                print("[scheduler] paper_trading: no active runs")
                watchdog_ping("paper_trading")
                return

            registry = StrategyRegistry()
            for run in runs:
                # Idempotency guard: skip if this trading day was already
                # recorded (e.g. scheduler restarts, manual + cron overlap).
                if run.daily_records and str(run.daily_records[-1].date) >= latest_date:
                    print(
                        f"[scheduler] paper_trading: {run.strategy_id} "
                        f"already at {latest_date}, skip"
                    )
                    continue
                try:
                    tracker.run_day(run, latest_date, flat_prices)
                    print(
                        f"[scheduler] paper_trading: {run.strategy_id} "
                        f"day {run.elapsed_days}/30 equity={run.current_equity:,.0f}"
                    )
                    # Auto-evaluate on completion
                    if run.is_complete:
                        result = tracker.evaluate(run)
                        if result.passed:
                            registry.set_lifecycle(
                                run.strategy_id, StrategyLifecycle.SHADOW_PRODUCTION
                            )
                            print(
                                f"[scheduler] paper_trading: {run.strategy_id} PASSED → "
                                f"SHADOW_PRODUCTION ({result.recommendation})"
                            )
                        else:
                            registry.set_lifecycle(run.strategy_id, StrategyLifecycle.RESEARCH)
                            print(
                                f"[scheduler] paper_trading: {run.strategy_id} FAILED → "
                                f"RESEARCH ({result.recommendation})"
                            )
                except Exception as exc:
                    print(f"[scheduler] paper_trading: {run.strategy_id} error: {exc}")

            watchdog_ping("paper_trading")

    scheduler.add_job(
        Job(
            name="paper_trading",
            task=job_paper_trading,
            trigger=CronTrigger(day_of_week="mon-fri", hour="18", minute="5"),
        )
    )

    # ── Job 5: email decision report (18:30 on weekdays) ──
    def job_email_report() -> None:
        """Send today's DecisionPackage as email after daily_pipeline completes."""
        with job_log_sink("email_report"):
            import json as _json
            from datetime import UTC, datetime
            from pathlib import Path

            from qp.monitoring.alerts import (
                Alert,
                AlertManager,
                AlertSeverity,
                EmailAlert,
            )

            email = EmailAlert()
            if not email.is_configured:
                print("[scheduler] email_report: Email not configured, skipping")
                watchdog_ping("email_report")
                return

            # Find today's DecisionPackage
            decisions_dir = Path("data/decisions")
            today_str = datetime.now(UTC).strftime("%Y-%m-%d")

            # Try JSON first, then markdown
            json_files = sorted(decisions_dir.glob(f"dp-{today_str}-*.json"), reverse=True)
            md_file = decisions_dir / f"{today_str}.md"

            subject = f"QP 每日投资决策 — {today_str}"
            body = ""

            if json_files:
                try:
                    data = _json.loads(json_files[0].read_text(encoding="utf-8"))
                    body = format_decision_email(data, today_str)
                except Exception:
                    pass

            if not body and md_file.exists():
                try:
                    body = md_file.read_text(encoding="utf-8")
                    # Truncate if too long for email
                    if len(body) > 15000:
                        body = body[:15000] + "\n\n... (truncated)"
                    subject = f"QP 每日投资决策 — {today_str}"
                except Exception:
                    body = f"DecisionPackage for {today_str}\n\n(no readable content)"

            if not body:
                body = f"QP Daily Pipeline completed for {today_str}.\n\nNo DecisionPackage found — check logs."

            try:
                mgr = AlertManager()
                mgr.add_channel(email)
                mgr.send(
                    Alert(
                        severity=AlertSeverity.INFO,
                        title=subject,
                        message=body,
                        source="email_report",
                    )
                )
                print(f"[scheduler] email_report: sent → {subject}")
            except Exception as e:
                print(f"[scheduler] email_report FAILED: {e}")

            watchdog_ping("email_report")

    scheduler.add_job(
        Job(
            name="email_report",
            task=job_email_report,
            trigger=CronTrigger(day_of_week="mon-fri", hour="18", minute="30"),
        )
    )

    # ── Graceful shutdown ──
    # When running under Application, delegate signal handling to the runtime.
    if app is not None:
        app.context.logger.info("Scheduler starting with runtime lifecycle", module="scheduler")
        _log_jobs(scheduler, log)
        scheduler.start()
        app.context.logger.info("Scheduler running, awaiting signals...", module="scheduler")
        app.run_forever()
        return 0

    # Standalone mode (no Application) — manual signal handling
    shutdown_flag = {"done": False}

    def _shutdown(signum, frame):
        if shutdown_flag["done"]:
            return
        shutdown_flag["done"] = True
        print("\n[scheduler] Shutting down...")
        with contextlib.suppress(Exception):
            scheduler.stop()
        print("[scheduler] Stopped.")

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    _log_jobs(scheduler, None)
    scheduler.start()

    # Keep alive — check shutdown flag every 0.5s for fast exit
    try:
        while not shutdown_flag["done"]:
            time.sleep(0.5)
    except KeyboardInterrupt:
        shutdown_flag["done"] = True
    finally:
        if not shutdown_flag["done"]:
            shutdown_flag["done"] = True
        with contextlib.suppress(Exception):
            scheduler.stop()
    return 0


def _log_jobs(scheduler, log) -> None:
    """Print registered jobs to console or logger."""
    lines = [
        "═══ QP Scheduler ═══",
        "  时区 / Timezone: Asia/Shanghai",
        "  已注册任务 / Jobs:",
    ]
    for name in scheduler.list_jobs():
        lines.append(f"    - {name}")
    lines.extend(["", "  运行中... 按 Ctrl+C 停止", ""])
    text = "\n".join(lines)
    if log is not None:
        log.info(text, module="scheduler")
    else:
        print(text)
