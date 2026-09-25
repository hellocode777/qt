"""CLI 选项接线回归测试（Click 层必须放行 handler 自己要解析的选项）。

背景（2026-09-25）：`validate` / `retrain` / `fundamental` 用普通 `@cli.command()`
注册，handler 却从 `sys.argv` 里解析选项，于是 Click 在进函数体前就报
"No such option '--stage'" —— 文档里写的选项全都不生效。同类 bug 还有
`qp pipeline list`（已修）。这里用 `make_context()` **只解析不执行**，
对每个命令断言其文档化选项能被 Click 接受。
"""

from __future__ import annotations

from typing import Any

import click
import pytest

from qp.platform.cli.parser import cli

# 命令 → 文档化的调用形式（CLI 参数，不含 "qp" 与命令名）
DOCUMENTED_INVOCATIONS: dict[str, list[str]] = {
    "validate": ["--stage", "research", "--strategy-id", "momentum_vol_full", "--json"],
    "retrain": ["momentum_vol_full", "--dry-run"],
    "fundamental": ["--quick"],
    "pipeline": ["list"],
    "run": ["daily", "--demo"],
    "ingest": ["--demo"],
    "decide": ["--history"],
    "capital-flow": ["--quick"],
    "data": ["fetch"],
}


@pytest.mark.parametrize(("command", "args"), sorted(DOCUMENTED_INVOCATIONS.items()))
def test_documented_options_are_accepted_by_click(command: str, args: list[str]) -> None:
    """文档里写的选项，Click 层必须能解析通过（不执行 handler）。"""
    cmd: Any = cli.commands[command]
    try:
        cmd.make_context(command, list(args))
    except click.UsageError as exc:  # pragma: no cover - failure path
        pytest.fail(f"qp {command} {' '.join(args)} 被 Click 拒绝: {exc.format_message()}")


def test_retrain_without_args_resolves_or_errors() -> None:
    """裸跑 qp retrain 由 handler 决定目标策略（不再写死策略名）。"""
    cmd: Any = cli.commands["retrain"]
    ctx = cmd.make_context("retrain", [])

    assert ctx.params["strategy_id"] == ""
    assert ctx.params["dry_run"] is False


def test_unknown_option_is_still_rejected() -> None:
    """fail-safe：真正不存在的选项仍要被 Click 拦住（不能静默吞掉）。"""
    cmd: Any = cli.commands["retrain"]
    with pytest.raises(click.UsageError):
        cmd.make_context("retrain", ["--does-not-exist"])
