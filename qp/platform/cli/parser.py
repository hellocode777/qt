"""Click-based CLI parser for the ``qp`` command.

All argument definitions are centralized here per the Walking Skeleton plan.
Each Click command wraps the existing handler function from
``qp.platform.cli.commands.*`` with lazy imports for fast startup.

``--help`` works for every command and subcommand automatically.
"""

from __future__ import annotations

import click

# ==================================================================
# CLI group
# ==================================================================


@click.group()
@click.version_option(message="%(version)s", package_name="qp")
def cli() -> None:
    """QP — Quantitative Investment Research & Decision Platform.

    All operations go through this single entry point.
    """


# ==================================================================
# Meta commands
# ==================================================================


@cli.command()
def version() -> None:
    """Print QP version info."""
    from qp.platform.cli.commands.meta import cmd_version

    raise SystemExit(cmd_version())


@cli.command()
def doctor() -> None:
    """Run environment self-check."""
    from qp.platform.cli.commands.meta import cmd_doctor

    raise SystemExit(cmd_doctor())


# ==================================================================
# Pipeline commands
# ==================================================================


@cli.command(
    context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
)
@click.pass_context
def ingest(ctx: click.Context) -> None:
    """Ingest market data from configured sources. All args pass through."""
    from qp.platform.cli.commands.ingest import cmd_ingest

    raise SystemExit(cmd_ingest())


@cli.command(
    context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
)
@click.pass_context
def run(ctx: click.Context) -> None:
    """Run a pipeline. All args pass through to handler."""
    from qp.platform.cli.commands.ingest import cmd_run

    raise SystemExit(cmd_run())


@cli.command()
def fundamental() -> None:
    """Fetch fundamental data for all stocks."""
    from qp.platform.cli.commands.ingest import cmd_fundamental

    raise SystemExit(cmd_fundamental())


@cli.command()
def pipeline() -> None:
    """Pipeline subcommands. Try: qp pipeline list"""
    import sys

    if len(sys.argv) > 2 and sys.argv[2] == "list":
        from qp.platform.cli.commands.ingest import cmd_pipeline_list

        raise SystemExit(cmd_pipeline_list())
    click.echo("qp pipeline: try 'qp pipeline list'", err=True)


# ==================================================================
# Validate
# ==================================================================


@cli.command()
def validate() -> None:
    """Run validation gate on strategies or experiments."""
    from qp.platform.cli.commands.validate import cmd_validate

    raise SystemExit(cmd_validate())


# ==================================================================
# Portfolio
# ==================================================================


@cli.group()
def portfolio() -> None:
    """Portfolio operations (report, risk analysis)."""


@portfolio.command("report")
def portfolio_report() -> None:
    """Print portfolio-level KPI dashboard."""
    from qp.platform.cli.commands.portfolio import cmd_portfolio_report

    raise SystemExit(cmd_portfolio_report())


@portfolio.command("risk")
def portfolio_risk() -> None:
    """Run risk analysis on current holdings."""
    from qp.platform.cli.commands.portfolio import cmd_portfolio_risk

    raise SystemExit(cmd_portfolio_risk())


# ==================================================================
# Position
# ==================================================================


@cli.group()
def position() -> None:
    """Position tracking (list, show, close, pnl, history)."""


@position.command("list")
def position_list() -> None:
    """List all positions."""
    from qp.platform.cli.commands.position import cmd_position_list

    raise SystemExit(cmd_position_list())


@position.command("show")
@click.argument("position_id")
def position_show(position_id: str) -> None:
    """Show details for a position."""
    from qp.platform.cli.commands.position import cmd_position_show

    raise SystemExit(cmd_position_show(position_id))


@position.command("close")
@click.argument("position_id")
@click.option("--price", type=float, default=0.0, help="Exit price")
@click.option("--reason", type=str, default="", help="Exit reason")
def position_close(position_id: str, price: float, reason: str) -> None:
    """Close a position."""
    from qp.platform.cli.commands.position import cmd_position_close

    raise SystemExit(cmd_position_close(position_id, exit_price=price, reason=reason))


@position.command("pnl")
def position_pnl() -> None:
    """Show P&L summary."""
    from qp.platform.cli.commands.position import cmd_position_pnl

    raise SystemExit(cmd_position_pnl())


@position.command("history")
@click.argument("limit", type=int, required=False, default=30)
def position_history(limit: int) -> None:
    """Show closed position history."""
    from qp.platform.cli.commands.position import cmd_position_history

    raise SystemExit(cmd_position_history(limit=limit))


# ==================================================================
# Simulation (Shadow Production)
# ==================================================================


@cli.group()
def simulation() -> None:
    """Shadow / paper trading simulation."""


@simulation.command("shadow")
@click.argument("date", required=False, default="")
def simulation_shadow(date: str) -> None:
    """Run or view shadow production."""
    if date:
        from qp.platform.cli.commands.shadow import cmd_shadow_run

        raise SystemExit(cmd_shadow_run(date))
    from qp.platform.cli.commands.shadow import cmd_shadow_summary

    raise SystemExit(cmd_shadow_summary())


# ==================================================================
# Experiment
# ==================================================================


@cli.group()
def experiment() -> None:
    """Experiment management (list, show, run, compare, validate, clean)."""


@experiment.command(
    "list",
    context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
)
@click.pass_context
def experiment_list(ctx: click.Context) -> None:
    """List experiments."""
    from qp.platform.cli.commands.experiment import cmd_experiment_list

    raise SystemExit(cmd_experiment_list())


@experiment.command(
    "show",
    context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
)
@click.pass_context
def experiment_show(ctx: click.Context) -> None:
    """Show experiment details."""
    from qp.platform.cli.commands.experiment import cmd_experiment_show

    raise SystemExit(cmd_experiment_show())


@experiment.command(
    "run",
    context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
)
@click.pass_context
def experiment_run(ctx: click.Context) -> None:
    """Run a multifactor experiment. All args passed through to handler."""
    from qp.platform.cli.commands.experiment import cmd_experiment_run

    raise SystemExit(cmd_experiment_run())


@experiment.command(
    "compare",
    context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
)
@click.pass_context
def experiment_compare(ctx: click.Context) -> None:
    """Compare experiments."""
    from qp.platform.cli.commands.experiment import cmd_experiment_compare

    raise SystemExit(cmd_experiment_compare())


@experiment.command(
    "validate",
    context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
)
@click.pass_context
def experiment_validate(ctx: click.Context) -> None:
    """Validate an experiment against quality gates."""
    from qp.platform.cli.commands.experiment import cmd_experiment_validate

    raise SystemExit(cmd_experiment_validate())


@experiment.command(
    "clean",
    context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
)
@click.pass_context
def experiment_clean(ctx: click.Context) -> None:
    """Clean old experiment files."""
    from qp.platform.cli.commands.experiment import cmd_experiment_clean

    raise SystemExit(cmd_experiment_clean())


# ==================================================================
# Model
# ==================================================================


@cli.group()
def model() -> None:
    """Model management (list, show)."""


@model.command("list")
def model_list() -> None:
    """List registered models."""
    from qp.platform.cli.commands.model import cmd_model_list

    raise SystemExit(cmd_model_list())


@model.command("show")
@click.argument("model_id", required=False)
def model_show(model_id: str | None) -> None:
    """Show model details."""
    from qp.platform.cli.commands.model import cmd_model_show

    raise SystemExit(cmd_model_show())


# ==================================================================
# Data
# ==================================================================


@cli.group()
def data() -> None:
    """Data operations."""


@data.command(
    "fetch",
    context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
)
@click.pass_context
def data_fetch(ctx: click.Context) -> None:
    """Fetch market data. All extra args passed through to handler."""
    from qp.platform.cli.commands.data_cmd import cmd_data_fetch

    raise SystemExit(cmd_data_fetch())


# ==================================================================
# Monitor
# ==================================================================


@cli.group()
def monitor() -> None:
    """System monitoring (check, regime, alert-test)."""


@monitor.command("check")
def monitor_check() -> None:
    """Run all monitoring checks."""
    from qp.platform.cli.commands.monitor import cmd_monitor_check

    raise SystemExit(cmd_monitor_check())


@monitor.command("regime")
def monitor_regime() -> None:
    """Detect current market regime."""
    from qp.platform.cli.commands.monitor import cmd_monitor_regime

    raise SystemExit(cmd_monitor_regime())


@monitor.command("alert-test")
def monitor_alert_test() -> None:
    """Send test alerts to configured channels."""
    from qp.platform.cli.commands.monitor import cmd_monitor_alert_test

    raise SystemExit(cmd_monitor_alert_test())


# ==================================================================
# Knowledge
# ==================================================================


@cli.group()
def knowledge() -> None:
    """Knowledge base (stats, search)."""


@knowledge.command("stats")
def knowledge_stats() -> None:
    """Show knowledge base statistics."""
    from qp.platform.cli.commands.knowledge import cmd_knowledge_stats

    raise SystemExit(cmd_knowledge_stats())


@knowledge.command("search")
@click.argument("query", required=False)
def knowledge_search(query: str | None) -> None:
    """Search knowledge base."""
    from qp.platform.cli.commands.knowledge import cmd_knowledge_search

    raise SystemExit(cmd_knowledge_search())


# ==================================================================
# Decide
# ==================================================================


@cli.command()
def decide() -> None:
    """Generate and review investment decisions."""
    from qp.platform.cli.commands.decide import cmd_decide

    raise SystemExit(cmd_decide())


# ==================================================================
# Paper Trading
# ==================================================================


@cli.group()
def paper() -> None:
    """Paper trading operations."""


@paper.command("start")
def paper_start() -> None:
    """Start paper trading for a strategy."""
    from qp.platform.cli.commands.paper import cmd_paper_start

    raise SystemExit(cmd_paper_start())


@paper.command("status")
def paper_status() -> None:
    """Show paper trading status."""
    from qp.platform.cli.commands.paper import cmd_paper_status

    raise SystemExit(cmd_paper_status())


# ==================================================================
# Proposal (Strategy Lifecycle Approval)
# ==================================================================


@cli.group()
def proposal() -> None:
    """Strategy proposal workflow (list, show, create, approve, reject, withdraw)."""


@proposal.command("list")
@click.option("--status", type=str, default="", help="Filter by status")
def proposal_list(status: str) -> None:
    """List proposals."""
    from qp.platform.cli.commands.proposal import cmd_proposal_list

    raise SystemExit(cmd_proposal_list(status=status))


@proposal.command("show")
@click.argument("proposal_id")
def proposal_show(proposal_id: str) -> None:
    """Show proposal details."""
    from qp.platform.cli.commands.proposal import cmd_proposal_show

    raise SystemExit(cmd_proposal_show(proposal_id))


@proposal.command("create")
@click.option("--strategy", type=str, required=True, help="Strategy ID")
@click.option("--target", type=str, required=True, help="Target lifecycle state")
@click.option("--justification", type=str, default="", help="Rationale")
@click.option("--by", type=str, default="cli", help="Proposer name")
def proposal_create(strategy: str, target: str, justification: str, by: str) -> None:
    """Create a new strategy promotion proposal."""
    from qp.platform.cli.commands.proposal import cmd_proposal_create

    raise SystemExit(cmd_proposal_create(
        strategy_id=strategy, target=target,
        justification=justification, proposed_by=by,
    ))


@proposal.command("approve")
@click.argument("proposal_id")
@click.option("--reviewer", type=str, default="", help="Reviewer name")
@click.option("--notes", type=str, default="", help="Review notes")
def proposal_approve(proposal_id: str, reviewer: str, notes: str) -> None:
    """Approve a proposal."""
    from qp.platform.cli.commands.proposal import cmd_proposal_approve

    raise SystemExit(cmd_proposal_approve(proposal_id, reviewer=reviewer, notes=notes))


@proposal.command("reject")
@click.argument("proposal_id")
@click.option("--reviewer", type=str, default="", help="Reviewer name")
@click.option("--notes", type=str, default="", help="Rejection reason")
def proposal_reject(proposal_id: str, reviewer: str, notes: str) -> None:
    """Reject a proposal."""
    from qp.platform.cli.commands.proposal import cmd_proposal_reject

    raise SystemExit(cmd_proposal_reject(proposal_id, reviewer=reviewer, notes=notes))


@proposal.command("withdraw")
@click.argument("proposal_id")
def proposal_withdraw(proposal_id: str) -> None:
    """Withdraw a proposal."""
    from qp.platform.cli.commands.proposal import cmd_proposal_withdraw

    raise SystemExit(cmd_proposal_withdraw(proposal_id))


# ==================================================================
# Web
# ==================================================================


@cli.group()
def web() -> None:
    """Web UI server."""


@web.command("start")
def web_start() -> None:
    """Start the QP web dashboard."""
    from qp.platform.cli.commands.web import cmd_web_start

    raise SystemExit(cmd_web_start())


# ==================================================================
# Retrain
# ==================================================================


@cli.command()
def retrain() -> None:
    """Trigger model retraining."""
    from qp.platform.cli.commands.retrain import cmd_retrain

    raise SystemExit(cmd_retrain())


# ==================================================================
# Scheduler
# ==================================================================


@cli.command()
@click.argument("subcommand", required=False)
def scheduler(subcommand: str | None) -> None:
    """Job scheduler (long-running). Try: qp scheduler start"""
    if subcommand == "start":
        from qp.platform.cli.commands.scheduler import cmd_scheduler_start

        raise SystemExit(cmd_scheduler_start())
    click.echo("qp scheduler: try 'qp scheduler start'", err=True)
    raise SystemExit(1)
