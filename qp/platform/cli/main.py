"""Main entry point for the `qp` CLI.

All operations go through this single entry point (ADR-002).
Command implementations live in qp.platform.cli.commands.*.

The runtime Application (ADR-012) is created for long-running commands
(scheduler) and available on-demand for short-lived commands.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from qp.platform.runtime.application import Application


def _build_app(environment: str = "dev") -> Application:
    """Build the runtime Application (lazy import)."""
    from qp.platform.runtime.builder import build_runtime

    return build_runtime(environment=environment)


def main() -> int:
    """Entry point for the qp CLI."""
    if len(sys.argv) < 2:
        print("qp: missing command. Try 'qp --help'", file=sys.stderr)
        return 1

    command = sys.argv[1]

    # ── Meta commands ──
    if command in ("version", "--version", "-V"):
        from qp.platform.cli.commands.meta import cmd_version

        return cmd_version()
    if command == "doctor":
        from qp.platform.cli.commands.meta import cmd_doctor

        return cmd_doctor()
    if command in ("--help", "-h"):
        from qp.platform.cli.commands.meta import cmd_help

        return cmd_help()

    # ── Pipeline commands ──
    if command == "ingest":
        from qp.platform.cli.commands.ingest import cmd_ingest

        return cmd_ingest()
    if command == "run" and len(sys.argv) > 2 and sys.argv[2] == "daily":
        from qp.platform.cli.commands.ingest import cmd_run

        return cmd_run()
    if command == "pipeline" and len(sys.argv) > 2 and sys.argv[2] == "list":
        from qp.platform.cli.commands.ingest import cmd_pipeline_list

        return cmd_pipeline_list()

    # ── Validate ──
    if command == "validate":
        from qp.platform.cli.commands.validate import cmd_validate

        return cmd_validate()

    # ── Portfolio ──
    if command == "portfolio" and len(sys.argv) > 2:
        sub = sys.argv[2]
        if sub == "report":
            from qp.platform.cli.commands.portfolio import cmd_portfolio_report

            return cmd_portfolio_report()
        if sub == "risk":
            from qp.platform.cli.commands.portfolio import cmd_portfolio_risk

            return cmd_portfolio_risk()
        print(f"qp portfolio: unknown subcommand '{sub}'. Try: report, risk", file=sys.stderr)
        return 1
    if command == "portfolio":
        print("qp portfolio: missing subcommand. Try: qp portfolio report", file=sys.stderr)
        return 1

    # ── Experiment ──
    if command == "experiment":
        if len(sys.argv) < 3:
            print(
                "qp experiment: missing subcommand. Try: list, show, run, compare, clean",
                file=sys.stderr,
            )
            return 1
        sub = sys.argv[2]
        if sub == "list":
            from qp.platform.cli.commands.experiment import cmd_experiment_list

            return cmd_experiment_list()
        if sub == "show":
            from qp.platform.cli.commands.experiment import cmd_experiment_show

            return cmd_experiment_show()
        if sub == "run":
            from qp.platform.cli.commands.experiment import cmd_experiment_run

            return cmd_experiment_run()
        if sub == "compare":
            from qp.platform.cli.commands.experiment import cmd_experiment_compare

            return cmd_experiment_compare()
        if sub == "validate":
            from qp.platform.cli.commands.experiment import cmd_experiment_validate

            return cmd_experiment_validate()
        if sub == "clean":
            from qp.platform.cli.commands.experiment import cmd_experiment_clean

            return cmd_experiment_clean()
        print(
            f"qp experiment: unknown subcommand '{sub}'. "
            "Try: list, show, run, compare, validate, clean",
            file=sys.stderr,
        )
        return 1

    # ── Model ──
    if command == "model":
        if len(sys.argv) < 3:
            print("qp model: missing subcommand. Try: list, show <id>", file=sys.stderr)
            return 1
        sub = sys.argv[2]
        if sub == "list":
            from qp.platform.cli.commands.model import cmd_model_list

            return cmd_model_list()
        if sub == "show":
            from qp.platform.cli.commands.model import cmd_model_show

            return cmd_model_show()
        print(f"qp model: unknown subcommand '{sub}'. Try: list, show", file=sys.stderr)
        return 1

    # ── Data ──
    if command == "data":
        if len(sys.argv) < 3:
            print("qp data: missing subcommand. Try: fetch", file=sys.stderr)
            return 1
        sub = sys.argv[2]
        if sub == "fetch":
            from qp.platform.cli.commands.data_cmd import cmd_data_fetch

            return cmd_data_fetch()
        print(f"qp data: unknown subcommand '{sub}'. Try: fetch", file=sys.stderr)
        return 1

    # ── Backtest ──
    if command == "backtest":
        if len(sys.argv) < 3:
            print(
                "qp backtest: missing subcommand. Try: qp backtest run [strategy]",
                file=sys.stderr,
            )
            return 1
        sub = sys.argv[2]
        if sub == "run":
            from qp.platform.cli.commands.backtest import cmd_backtest_run

            return cmd_backtest_run()
        print(f"qp backtest: unknown subcommand '{sub}'. Try: run", file=sys.stderr)
        return 1

    # ── Monitor ──
    if command == "monitor":
        if len(sys.argv) < 3:
            print(
                "qp monitor: missing subcommand. Try: check, regime, alert-test",
                file=sys.stderr,
            )
            return 1
        sub = sys.argv[2]
        if sub == "check":
            from qp.platform.cli.commands.monitor import cmd_monitor_check

            return cmd_monitor_check()
        if sub == "regime":
            from qp.platform.cli.commands.monitor import cmd_monitor_regime

            return cmd_monitor_regime()
        if sub == "alert-test":
            from qp.platform.cli.commands.monitor import cmd_monitor_alert_test

            return cmd_monitor_alert_test()
        print(
            f"qp monitor: unknown subcommand '{sub}'. Try: check, regime, alert-test",
            file=sys.stderr,
        )
        return 1

    # ── Knowledge ──
    if command == "knowledge":
        if len(sys.argv) < 3:
            print(
                "qp knowledge: missing subcommand. Try: stats, search <query>",
                file=sys.stderr,
            )
            return 1
        sub = sys.argv[2]
        if sub == "stats":
            from qp.platform.cli.commands.knowledge import cmd_knowledge_stats

            return cmd_knowledge_stats()
        if sub == "search":
            from qp.platform.cli.commands.knowledge import cmd_knowledge_search

            return cmd_knowledge_search()
        print(
            f"qp knowledge: unknown subcommand '{sub}'. Try: stats, search",
            file=sys.stderr,
        )
        return 1

    # ── Decide ──
    if command == "decide":
        from qp.platform.cli.commands.decide import cmd_decide

        return cmd_decide()

    # ── Paper ──
    if command == "paper":
        if len(sys.argv) < 3:
            print("qp paper: missing subcommand. Try: start, status", file=sys.stderr)
            return 1
        sub = sys.argv[2]
        if sub == "start":
            from qp.platform.cli.commands.paper import cmd_paper_start

            return cmd_paper_start()
        if sub == "status":
            from qp.platform.cli.commands.paper import cmd_paper_status

            return cmd_paper_status()
        print(f"qp paper: unknown subcommand '{sub}'. Try: start, status", file=sys.stderr)
        return 1

    # ── Web ──
    if command == "web":
        if len(sys.argv) < 3:
            print("qp web: missing subcommand. Try: qp web start", file=sys.stderr)
            return 1
        sub = sys.argv[2]
        if sub == "start":
            from qp.platform.cli.commands.web import cmd_web_start

            return cmd_web_start()
        print(
            f"qp web: unknown subcommand '{sub}'. Try: qp web start",
            file=sys.stderr,
        )
        return 1

    # ── Retrain ──
    if command == "retrain":
        from qp.platform.cli.commands.retrain import cmd_retrain

        return cmd_retrain()

    # ── Scheduler (long-running — uses full Application lifecycle) ──
    if command == "scheduler" and len(sys.argv) > 2 and sys.argv[2] == "start":
        from qp.platform.cli.commands.scheduler import cmd_scheduler_start

        app = _build_app()
        app.start()
        try:
            return cmd_scheduler_start(app)
        finally:
            app.stop()
    if command == "scheduler":
        print("qp scheduler: missing subcommand. Try: qp scheduler start", file=sys.stderr)
        return 1

    print(f"qp: unknown command '{command}'. Try 'qp --help'", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
