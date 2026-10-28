"""审批守卫测试（qp/strategy/approval_guard.py）。

覆盖 2026-10-28 事故的三条硬拦：缺批准人 / 门禁结论未放行 / 必需检查项非 PASS，
以及 --force 显式越过与「无门禁记录只告警」的边界。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from qp.shared.types import StrategyLifecycle
from qp.strategy.approval_guard import (
    ALLOWED_GATE_DECISIONS,
    ApprovalBlockedError,
    enforce_approval,
    evaluate_approval,
    latest_gate,
)

CLEAN_GATE: dict[str, object] = {
    "strategy_id": "demo",
    "stage": "approved",
    "decision": "proceed",
    "data_integrity": "PASS",
    "factor_validity": "PASS",
    "portfolio_conversion": "PASS",
    "robustness": "PASS",
    "cost_capacity": "PASS",
    "timestamp": "2026-10-28T00:00:00+00:00",
}

# 事故现场的真实形态（momentum_vol_full_20261001_100255_gate.json）
FAILED_GATE: dict[str, object] = {
    "strategy_id": "demo",
    "stage": "backtest_passed",
    "decision": "research_only",
    "data_integrity": "PASS",
    "factor_validity": "PASS",
    "portfolio_conversion": "FAIL",
    "robustness": "NOT_RUN",
    "cost_capacity": "NOT_RUN",
    "timestamp": "2026-10-01T02:02:55+00:00",
}


def _write_gate(directory: Path, name: str, record: dict[str, object]) -> Path:
    path = directory / name
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


class TestEvaluateApproval:
    """纯规则测试（不落盘）。"""

    def test_missing_approver_is_blocking(self) -> None:
        issues = evaluate_approval("demo", "", CLEAN_GATE)
        codes = [issue.code for issue in issues if issue.blocking]
        assert codes == ["MISSING_APPROVER"]

    def test_whitespace_approver_is_blocking(self) -> None:
        issues = evaluate_approval("demo", "   ", CLEAN_GATE)
        assert [issue.code for issue in issues if issue.blocking] == ["MISSING_APPROVER"]

    def test_research_only_decision_is_blocking(self) -> None:
        issues = evaluate_approval("demo", "Wei", FAILED_GATE)
        blocking = {issue.code for issue in issues if issue.blocking}
        assert "GATE_DECISION" in blocking
        assert "GATE_PORTFOLIO_CONVERSION" in blocking

    def test_advisory_checks_do_not_block(self) -> None:
        issues = evaluate_approval("demo", "Wei", FAILED_GATE)
        advisory = {issue.code for issue in issues if not issue.blocking}
        assert "GATE_ROBUSTNESS" in advisory
        assert "GATE_COST_CAPACITY" in advisory

    def test_clean_gate_passes_without_issues(self) -> None:
        assert evaluate_approval("demo", "Wei", CLEAN_GATE) == []

    def test_missing_gate_is_advisory_only(self) -> None:
        issues = evaluate_approval("demo", "Wei", None)
        assert [issue.code for issue in issues] == ["NO_GATE_RECORD"]
        assert not issues[0].blocking

    def test_allowed_decisions_are_explicit(self) -> None:
        """允许集合必须显式列白，reset 时不能悄悄放进 research_only。"""
        assert "research_only" not in ALLOWED_GATE_DECISIONS


class TestEnforceApproval:
    """抛异常 / force 越过 / 门禁文件发现。"""

    def test_blocks_by_default(self) -> None:
        with pytest.raises(ApprovalBlockedError) as err:
            enforce_approval("demo", "Wei", gate=FAILED_GATE)
        assert "research_only" in str(err.value)

    def test_force_bypasses_but_returns_issues(self) -> None:
        issues = enforce_approval("demo", "Wei", force=True, gate=FAILED_GATE)
        assert any(issue.blocking for issue in issues)

    def test_force_bypasses_missing_approver(self) -> None:
        issues = enforce_approval("demo", "", force=True, gate=CLEAN_GATE)
        assert any(issue.code == "MISSING_APPROVER" for issue in issues)

    def test_latest_gate_picks_newest_timestamp(self, tmp_path: Path) -> None:
        older = dict(CLEAN_GATE, timestamp="2026-09-01T00:00:00+00:00", decision="research_only")
        newer = dict(CLEAN_GATE, timestamp="2026-10-01T00:00:00+00:00")
        _write_gate(tmp_path, "demo_20260901_000000_gate.json", older)
        _write_gate(tmp_path, "demo_20261001_000000_gate.json", newer)

        record = latest_gate("demo", search_dir=tmp_path)
        assert record is not None
        assert record["timestamp"] == "2026-10-01T00:00:00+00:00"

    def test_gate_found_on_disk_blocks_approval(self, tmp_path: Path) -> None:
        _write_gate(tmp_path, "demo_20261001_000000_gate.json", FAILED_GATE)
        with pytest.raises(ApprovalBlockedError):
            enforce_approval("demo", "Wei", search_dir=tmp_path)

    def test_no_gate_file_on_disk_allows_approval(self, tmp_path: Path) -> None:
        issues = enforce_approval("demo", "Wei", search_dir=tmp_path)
        assert [issue.code for issue in issues] == ["NO_GATE_RECORD"]


class TestRegistryApprovalGuard:
    """守卫在 StrategyRegistry.approve() 上真的生效。"""

    @staticmethod
    def _registry(tmp_path: Path):
        from qp.strategy.registry import StrategyMeta, StrategyRegistry
        from qp.strategy.simple_rank import SimpleRankStrategy

        registry = StrategyRegistry(registry_path=tmp_path / "registry.json")
        registry.register(
            SimpleRankStrategy(top_n=10),
            meta=StrategyMeta(weights={"F1": -0.25, "F2": 0.15}, parameters={"top_n": 10}),
        )
        return registry

    def test_empty_approver_blocks_registry_approve(self, tmp_path: Path) -> None:
        registry = self._registry(tmp_path)
        with pytest.raises(ApprovalBlockedError, match="MISSING_APPROVER"):
            registry.approve("simple_rank_v1.0", approved_by="")
        assert registry.get_lifecycle("simple_rank_v1.0") != StrategyLifecycle.APPROVED

    def test_force_allows_and_freezes_snapshot(self, tmp_path: Path) -> None:
        registry = self._registry(tmp_path)
        approved = registry.approve("simple_rank_v1.0", approved_by="", force=True)
        assert registry.get_lifecycle("simple_rank_v1.0") == StrategyLifecycle.APPROVED
        assert approved.approved_by == ""  # type: ignore[attr-defined]

    def test_named_approver_without_gate_record_still_approves(self, tmp_path: Path) -> None:
        """研究期策略没有门禁记录时只告警，不阻断（避免误伤既有流程）。"""
        registry = self._registry(tmp_path)
        approved = registry.approve("simple_rank_v1.0", approved_by="researcher")
        assert approved.approved_by == "researcher"  # type: ignore[attr-defined]
        assert registry.get_lifecycle("simple_rank_v1.0") == StrategyLifecycle.APPROVED


class TestApproveParametersOverride:
    """调仓节奏等参数随 approve 一并冻结进快照（不改 registry meta）。"""

    @staticmethod
    def _registry(tmp_path: Path):
        from qp.strategy.registry import StrategyMeta, StrategyRegistry
        from qp.strategy.simple_rank import SimpleRankStrategy

        registry = StrategyRegistry(registry_path=tmp_path / "registry.json")
        registry.register(
            SimpleRankStrategy(top_n=10),
            meta=StrategyMeta(
                weights={"F1": -0.25, "F2": 0.15},
                parameters={"top_n": 10, "rebalance": 20},
            ),
        )
        return registry

    def test_override_merged_into_snapshot_only(self, tmp_path: Path) -> None:
        registry = self._registry(tmp_path)
        approved = registry.approve(
            "simple_rank_v1.0",
            approved_by="Wei",
            parameters_override={"rebalance_cadence": "trading_days", "rebalance_days": 40},
        )

        snapshot_params = approved.parameters  # type: ignore[attr-defined]
        assert snapshot_params["rebalance_cadence"] == "trading_days"
        assert snapshot_params["rebalance_days"] == 40
        assert snapshot_params["top_n"] == 10  # 原有参数保留

        # registry meta 不被改写（避免“没批准但参数变了”的中间态）
        meta = registry.get_meta("simple_rank_v1.0")
        assert "rebalance_cadence" not in (meta.parameters or {})

    def test_no_override_keeps_meta_parameters(self, tmp_path: Path) -> None:
        registry = self._registry(tmp_path)
        approved = registry.approve("simple_rank_v1.0", approved_by="Wei")
        assert approved.parameters.get("rebalance") == 20  # type: ignore[attr-defined]
        assert "rebalance_cadence" not in approved.parameters  # type: ignore[attr-defined]
