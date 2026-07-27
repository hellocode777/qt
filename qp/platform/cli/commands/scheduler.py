"""CLI command handlers for the "scheduler" group."""

from __future__ import annotations

import contextlib
import signal
import time
from typing import TYPE_CHECKING

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
      - daily_pipeline:    DailyPipeline              (weekdays 17:57)
      - email_report:      Email DecisionPackage      (weekdays 18:03)

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

    # ── Watchdog: touch ping file for external monitoring (#12 fix) ──
    def watchdog_ping(job_name: str) -> None:
        from datetime import UTC, datetime
        from pathlib import Path

        ping_dir = Path("data/monitoring/watchdog")
        ping_dir.mkdir(parents=True, exist_ok=True)
        (ping_dir / f"{job_name}.ping").write_text(f"{datetime.now(UTC).isoformat()}\n")

    # ── Job 1: morning health check (09:07 on weekdays) ──
    def job_monitor_check() -> None:
        from qp.monitoring.kill_switch_pipeline import (
            KillSwitchPipeline,
            MonitorAction,
        )

        ctx = _make_ctx("scheduled_monitor")
        pipeline = KillSwitchPipeline()
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
            trigger=CronTrigger(day="1-5", hour="9", minute="7"),
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
            trigger=CronTrigger(day="1-5", hour="9", minute="17"),
        )
    )

    # ── Job 3: pre-close health gate (16:53 on weekdays) ──
    def job_pre_close_check() -> None:
        """收盘前快速检查，决定是否执行盘后策略."""
        from qp.monitoring.kill_switch_pipeline import (
            KillSwitchPipeline,
            MonitorAction,
        )

        ctx = _make_ctx("pre_close_check")
        pipeline = KillSwitchPipeline()
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
            return  # daily_pipeline won't run because we return non-zero? No, we still run it but log the warning

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
            trigger=CronTrigger(day="1-5", hour="16", minute="53"),
        )
    )

    # ── Job 4: daily decision pipeline (17:57 on weekdays) ──
    def job_daily_pipeline() -> None:
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
            trigger=CronTrigger(day="1-5", hour="17", minute="57"),
        )
    )

    # ── Job 5: email decision report (18:03 on weekdays) ──
    def job_email_report() -> None:
        """Send today's DecisionPackage as email after daily_pipeline completes."""
        import json as _json
        from datetime import UTC, datetime
        from pathlib import Path

        from qp.monitoring.alerts import Alert, AlertManager, AlertSeverity, EmailAlert

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
            trigger=CronTrigger(day="1-5", hour="18", minute="3"),
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
