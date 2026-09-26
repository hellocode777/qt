"""Guards ``docs/command_reference.md`` against CLI drift.

The reference is generated from the Click tree in ``qp/platform/cli/parser.py``.
Adding/removing/renaming a command without regenerating used to be invisible;
now it fails here: the generator's ``--check`` mode re-renders the document and
compares it to the committed file.

Fix by running:  .venv/bin/python scripts/maintenance/gen_command_reference.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GENERATOR = REPO / "scripts" / "maintenance" / "gen_command_reference.py"
DOC = REPO / "docs" / "command_reference.md"


def test_command_reference_matches_cli() -> None:
    assert GENERATOR.is_file(), f"missing generator: {GENERATOR}"

    result = subprocess.run(  # noqa: S603 — 参数由测试内部固定构造，无外部输入
        [sys.executable, str(GENERATOR), "--check"],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=300,
    )

    assert result.returncode == 0, (
        "docs/command_reference.md 与当前 CLI 不一致（命令增删改后忘了重跑生成器）。\n"
        f"stdout: {result.stdout.strip()}\nstderr: {result.stderr.strip()}\n"
        "修复：.venv/bin/python scripts/maintenance/gen_command_reference.py"
    )
    assert "up to date" in result.stdout


def test_command_reference_lists_every_runtime_command() -> None:
    """Independent of the generator's own rendering: every runtime command is documented."""
    import click

    from qp.platform.cli.parser import cli

    runtime: set[str] = set()

    def walk(group: click.Group, prefix: tuple[str, ...]) -> None:
        for name, cmd in group.commands.items():
            path = (*prefix, name)
            if isinstance(cmd, click.Group):
                walk(cmd, path)
            else:
                runtime.add("qp " + " ".join(path))

    walk(cli, ())
    runtime.add("qp pipeline list")  # dispatched in the wrapper via sys.argv[2]

    doc = DOC.read_text(encoding="utf-8")
    table = doc.split("## 1. 速查表", 1)[1].split("## 2.", 1)[0]
    documented = {
        line.split("`")[1]
        for line in table.splitlines()
        if line.startswith("| `qp ") and "`" in line
    }

    assert documented == runtime, (
        f"速查表缺失: {sorted(runtime - documented)}；多出: {sorted(documented - runtime)}"
    )
