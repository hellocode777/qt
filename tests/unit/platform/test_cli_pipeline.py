"""Regression tests for the `qp pipeline` CLI wiring.

Why this test exists: `pipeline` is a plain Click command whose handler
dispatches on raw ``sys.argv`` (same pattern as ``run`` / ``validate`` /
``decide``). Without ``context_settings={"allow_extra_args": True}`` Click
rejects the extra ``list`` argument *before* the handler body runs, so
``qp pipeline list`` failed with

    Error: Got unexpected extra argument (list)

and the command was permanently unreachable even though
``cmd_pipeline_list()`` was fine. These tests exercise the CLI surface
(argv patched, exactly what the handler reads) so the wiring cannot silently
regress again.
"""

from __future__ import annotations

import sys
from unittest.mock import patch

from click.testing import CliRunner

from qp.platform.cli.parser import cli


def _combined_output(result: object) -> str:
    """Stdout + stderr — Click >= 8.2 captures them separately."""
    return str(getattr(result, "output", "")) + str(getattr(result, "stderr", ""))


def test_pipeline_list_reaches_the_handler() -> None:
    """`qp pipeline list` must run cmd_pipeline_list, not fail Click's arg check."""
    with patch.object(sys, "argv", ["qp", "pipeline", "list"]):
        result = CliRunner().invoke(cli, ["pipeline", "list"])

    assert result.exit_code == 0, _combined_output(result)
    assert result.exception is None
    assert "Registered Pipelines:" in _combined_output(result)
    assert "daily" in _combined_output(result)


def test_pipeline_without_args_only_prints_hint() -> None:
    """`qp pipeline` with no subcommand stays a no-op hint (exit 0)."""
    with patch.object(sys, "argv", ["qp", "pipeline"]):
        result = CliRunner().invoke(cli, ["pipeline"])

    assert result.exit_code == 0, _combined_output(result)
    assert "try 'qp pipeline list'" in _combined_output(result)
    assert "Registered Pipelines:" not in _combined_output(result)
