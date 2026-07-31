"""Tests for the Decision Layer (Layer 8)."""

from pathlib import Path

import pytest

from qp.decision.engine import DecisionEngine
from qp.decision.models import DecisionReport, TradeRecommendation
from qp.decision.state_machine import (
    DecisionStateError,
    DecisionStatus,
    StatusTransition,
    allowed_transitions,
    approve,
    can_transition,
    close,
    mark_executed,
    modify,
    reject,
    transition,
)


class TestTradeRecommendation:
    """Test TradeRecommendation dataclass."""

    def test_construct_default(self) -> None:
        rec = TradeRecommendation(symbol="600519", action="BUY")
        assert rec.symbol == "600519"
        assert rec.action == "BUY"
        assert rec.target_weight_pct == 0.0

    def test_construct_full(self) -> None:
        rec = TradeRecommendation(
            symbol="000001",
            action="SELL",
            target_weight_pct=5.0,
            current_weight_pct=8.0,
            quantity_shares=1000,
            estimated_price=12.50,
            estimated_cost=25.0,
            reason="动量排名下降",
            risk_warnings=["单仓占比 8% 上限"],
            confidence=0.85,
            strategy="simple_rank_v1.0",
        )
        assert rec.symbol == "000001"
        assert rec.action == "SELL"
        assert rec.target_weight_pct == 5.0
        assert rec.reason == "动量排名下降"
        assert rec.confidence == 0.85
        assert len(rec.risk_warnings) == 1

    def test_trade_value(self) -> None:
        rec = TradeRecommendation(
            symbol="600519",
            action="BUY",
            quantity_shares=500,
            estimated_price=100.0,
        )
        assert rec.trade_value == 50000.0

    def test_cost_pct(self) -> None:
        rec = TradeRecommendation(
            symbol="600519",
            action="BUY",
            quantity_shares=100,
            estimated_price=1000.0,
            estimated_cost=25.0,
        )
        assert rec.cost_pct == 0.025  # 25 / 100000 * 100 = 0.025%

    def test_cost_pct_zero_value(self) -> None:
        rec = TradeRecommendation(action="BUY", symbol="600519")
        assert rec.cost_pct == 0.0

    def test_weight_change_pct(self) -> None:
        rec = TradeRecommendation(
            symbol="600519",
            action="BUY",
            target_weight_pct=8.0,
            current_weight_pct=5.0,
        )
        assert rec.weight_change_pct == 3.0

    def test_risk_warnings_empty(self) -> None:
        rec = TradeRecommendation(action="BUY", symbol="600519")
        assert rec.risk_warnings == []


class TestDecisionReport:
    """Test DecisionReport dataclass."""

    def test_empty_report(self) -> None:
        report = DecisionReport(strategy_id="test_v1.0")
        assert report.is_empty is True
        assert report.n_buys == 0
        assert report.n_sells == 0
        assert report.total_estimated_cost == 0.0

    def test_with_recommendations(self) -> None:
        report = DecisionReport(
            strategy_id="test_v1.0",
            total_capital=1_000_000,
            recommendations=[
                TradeRecommendation(symbol="A", action="BUY", confidence=0.9),
                TradeRecommendation(symbol="B", action="BUY", confidence=0.7),
                TradeRecommendation(action="SELL", symbol="C", confidence=0.5),
            ],
        )
        assert report.n_buys == 2
        assert report.n_sells == 1
        assert report.n_holds == 0
        assert report.is_empty is False

    def test_has_warnings(self) -> None:
        report = DecisionReport(
            recommendations=[
                TradeRecommendation(action="BUY", symbol="A", risk_warnings=["⚠ 风险"]),
                TradeRecommendation(action="BUY", symbol="B"),
            ]
        )
        assert report.has_warnings is True

    def test_no_warnings(self) -> None:
        report = DecisionReport(
            recommendations=[
                TradeRecommendation(action="BUY", symbol="A"),
                TradeRecommendation(action="BUY", symbol="B"),
            ]
        )
        assert report.has_warnings is False

    def test_buys_filter(self) -> None:
        report = DecisionReport(
            recommendations=[
                TradeRecommendation(symbol="A", action="BUY"),
                TradeRecommendation(action="SELL", symbol="B"),
                TradeRecommendation(symbol="C", action="BUY"),
            ]
        )
        assert len(report.buys) == 2
        assert report.buys[0].symbol == "A"

    def test_sells_filter(self) -> None:
        report = DecisionReport(
            recommendations=[
                TradeRecommendation(action="SELL", symbol="A"),
                TradeRecommendation(symbol="B", action="BUY"),
            ]
        )
        assert len(report.sells) == 1

    def test_top_picks(self) -> None:
        report = DecisionReport(
            recommendations=[
                TradeRecommendation(action="BUY", symbol="A", confidence=0.6),
                TradeRecommendation(action="BUY", symbol="B", confidence=0.9),
                TradeRecommendation(action="BUY", symbol="C", confidence=0.3),
                TradeRecommendation(action="BUY", symbol="D", confidence=0.8),
                TradeRecommendation(action="BUY", symbol="E", confidence=0.7),
                TradeRecommendation(action="BUY", symbol="F", confidence=0.5),
            ]
        )
        top = report.top_picks
        assert len(top) == 5
        assert top[0].symbol == "B"  # Highest confidence
        assert top[0].confidence == 0.9

    def test_disclaimer_present(self) -> None:
        report = DecisionReport()
        assert "投资建议" in report.disclaimer or "investment advice" in report.disclaimer


class TestDecisionEngine:
    """Test DecisionEngine."""

    def test_construct(self) -> None:
        engine = DecisionEngine()
        assert engine is not None

    def test_construct_custom_rates(self) -> None:
        engine = DecisionEngine(
            stamp_tax_rate=0.001,
            commission_rate=0.0005,
            slippage_bps=20.0,
        )
        assert engine is not None

    def test_generate_empty_signals(self) -> None:
        import polars as pl

        engine = DecisionEngine()
        empty = pl.DataFrame()
        result = engine.generate(empty, pl.DataFrame())
        assert result.is_empty is True
        assert result.risk_summary != ""
        assert result.cost_summary == "无 / None"

    def test_format_bilingual_empty(self) -> None:
        engine = DecisionEngine()
        report = DecisionReport(strategy_id="test")
        output = engine.format_bilingual(report)
        assert "No recommendations" in output
        assert "交易建议" in output

    def test_to_markdown_empty(self) -> None:
        engine = DecisionEngine()
        report = DecisionReport(strategy_id="test")
        output = engine.to_markdown(report)
        assert "No recommendations" in output

    def test_to_markdown_with_recs(self) -> None:
        engine = DecisionEngine()
        report = DecisionReport(
            strategy_id="test_v1.0",
            total_capital=1_000_000,
            recommendations=[
                TradeRecommendation(
                    symbol="600519",
                    action="BUY",
                    target_weight_pct=8.0,
                    quantity_shares=500,
                    estimated_price=100.0,
                    estimated_cost=25.0,
                    reason="动量排名 #1",
                    confidence=0.95,
                ),
            ],
        )
        output = engine.to_markdown(report)
        assert "600519" in output
        assert "Buy Recommendations" in output


# ==================================================================
# Decision State Machine tests
# ==================================================================


class TestDecisionStatus:
    """Test DecisionStatus enum properties."""

    def test_all_statuses_defined(self) -> None:
        assert len(list(DecisionStatus)) == 7

    def test_labels(self) -> None:
        assert DecisionStatus.PENDING.label == "待审核"
        assert DecisionStatus.APPROVED.label == "已批准"
        assert DecisionStatus.REJECTED.label == "已驳回"
        assert DecisionStatus.MODIFIED.label == "已修改"
        assert DecisionStatus.PARTIALLY_EXECUTED.label == "部分执行"
        assert DecisionStatus.MONITORING.label == "监控中"
        assert DecisionStatus.CLOSED.label == "已关闭"

    def test_terminal_statuses(self) -> None:
        assert DecisionStatus.REJECTED.is_terminal is True
        assert DecisionStatus.CLOSED.is_terminal is True
        for s in DecisionStatus:
            if s not in (DecisionStatus.REJECTED, DecisionStatus.CLOSED):
                assert s.is_terminal is False, f"{s} should not be terminal"

    def test_active_statuses(self) -> None:
        for s in DecisionStatus:
            if s in (DecisionStatus.REJECTED, DecisionStatus.CLOSED):
                assert s.is_active is False, f"{s} should not be active"
            else:
                assert s.is_active is True, f"{s} should be active"

    def test_requires_human_action(self) -> None:
        assert DecisionStatus.PENDING.requires_human_action is True
        assert DecisionStatus.MODIFIED.requires_human_action is True
        for s in (DecisionStatus.APPROVED, DecisionStatus.REJECTED,
                  DecisionStatus.PARTIALLY_EXECUTED, DecisionStatus.MONITORING,
                  DecisionStatus.CLOSED):
            assert s.requires_human_action is False, f"{s} should not require human action"


class TestCanTransition:
    """Test can_transition validation function."""

    def test_valid_transitions(self) -> None:
        assert can_transition(DecisionStatus.PENDING, DecisionStatus.APPROVED) is True
        assert can_transition(DecisionStatus.PENDING, DecisionStatus.REJECTED) is True
        assert can_transition(DecisionStatus.PENDING, DecisionStatus.MODIFIED) is True
        assert can_transition(DecisionStatus.APPROVED, DecisionStatus.PARTIALLY_EXECUTED) is True
        assert can_transition(DecisionStatus.APPROVED, DecisionStatus.MONITORING) is True
        assert can_transition(DecisionStatus.MODIFIED, DecisionStatus.APPROVED) is True
        assert can_transition(DecisionStatus.PARTIALLY_EXECUTED, DecisionStatus.MONITORING) is True
        assert can_transition(DecisionStatus.MONITORING, DecisionStatus.CLOSED) is True

    def test_invalid_transitions(self) -> None:
        assert can_transition(DecisionStatus.REJECTED, DecisionStatus.APPROVED) is False
        assert can_transition(DecisionStatus.CLOSED, DecisionStatus.MONITORING) is False
        assert can_transition(DecisionStatus.APPROVED, DecisionStatus.PENDING) is False
        assert can_transition(DecisionStatus.MONITORING, DecisionStatus.PENDING) is False
        assert can_transition(DecisionStatus.CLOSED, DecisionStatus.PENDING) is False
        assert can_transition(DecisionStatus.REJECTED, DecisionStatus.MODIFIED) is False

    def test_self_transition_always_allowed(self) -> None:
        for s in DecisionStatus:
            assert can_transition(s, s) is True, f"Self-transition for {s} should be allowed"

    def test_terminal_no_outgoing(self) -> None:
        for s in DecisionStatus:
            if s.is_terminal:
                for target in DecisionStatus:
                    if target != s:
                        assert can_transition(s, target) is False, (
                            f"Terminal {s} should not transition to {target}"
                        )


class TestAllowedTransitions:
    """Test allowed_transitions helper."""

    def test_always_includes_self(self) -> None:
        for s in DecisionStatus:
            assert s in allowed_transitions(s)

    def test_pending_allowed(self) -> None:
        allowed = allowed_transitions(DecisionStatus.PENDING)
        assert DecisionStatus.APPROVED in allowed
        assert DecisionStatus.REJECTED in allowed
        assert DecisionStatus.MODIFIED in allowed
        assert DecisionStatus.PENDING in allowed

    def test_terminal_only_self(self) -> None:
        assert allowed_transitions(DecisionStatus.REJECTED) == {DecisionStatus.REJECTED}
        assert allowed_transitions(DecisionStatus.CLOSED) == {DecisionStatus.CLOSED}


class TestTransition:
    """Test transition function with audit records."""

    def test_returns_new_status_and_record(self) -> None:
        new_status, record = transition(
            DecisionStatus.PENDING, DecisionStatus.APPROVED,
            actor="测试员", notes="测试",
        )
        assert new_status == DecisionStatus.APPROVED
        assert isinstance(record, StatusTransition)
        assert record.from_status == DecisionStatus.PENDING
        assert record.to_status == DecisionStatus.APPROVED
        assert record.actor == "测试员"
        assert record.notes == "测试"
        assert record.timestamp != ""

    def test_self_transition(self) -> None:
        new_status, record = transition(DecisionStatus.APPROVED, DecisionStatus.APPROVED)
        assert new_status == DecisionStatus.APPROVED
        assert record.from_status == DecisionStatus.APPROVED
        assert record.to_status == DecisionStatus.APPROVED

    def test_invalid_raises(self) -> None:
        with pytest.raises(DecisionStateError) as exc_info:
            transition(DecisionStatus.REJECTED, DecisionStatus.APPROVED)
        assert "rejected" in str(exc_info.value)
        assert "approved" in str(exc_info.value)


class TestApprove:
    """Test approve convenience function."""

    def test_from_pending(self) -> None:
        new_status, _ = approve(DecisionStatus.PENDING, reviewer="张三")
        assert new_status == DecisionStatus.APPROVED

    def test_from_modified(self) -> None:
        new_status, _ = approve(DecisionStatus.MODIFIED, reviewer="张三")
        assert new_status == DecisionStatus.APPROVED

    def test_from_approved_raises(self) -> None:
        with pytest.raises(DecisionStateError, match="Cannot approve from"):
            approve(DecisionStatus.APPROVED, reviewer="张三")

    def test_from_rejected_raises(self) -> None:
        with pytest.raises(DecisionStateError):
            approve(DecisionStatus.REJECTED)


class TestReject:
    """Test reject convenience function."""

    def test_from_pending(self) -> None:
        new_status, _ = reject(DecisionStatus.PENDING, reviewer="李四", notes="策略失效")
        assert new_status == DecisionStatus.REJECTED

    def test_from_already_approved_raises(self) -> None:
        with pytest.raises(DecisionStateError, match="Cannot reject from"):
            reject(DecisionStatus.APPROVED)


class TestModify:
    """Test modify convenience function."""

    def test_from_pending(self) -> None:
        new_status, _ = modify(DecisionStatus.PENDING, reviewer="王五",
                               notes="移除603986")
        assert new_status == DecisionStatus.MODIFIED

    def test_from_approved_raises(self) -> None:
        with pytest.raises(DecisionStateError, match="Cannot modify from"):
            modify(DecisionStatus.APPROVED)


class TestMarkExecuted:
    """Test mark_executed convenience function."""

    def test_from_approved_to_partially_executed(self) -> None:
        new_status, _ = mark_executed(DecisionStatus.APPROVED, notes="部分成交")
        assert new_status == DecisionStatus.PARTIALLY_EXECUTED

    def test_from_partially_to_monitoring(self) -> None:
        new_status, _ = mark_executed(DecisionStatus.PARTIALLY_EXECUTED,
                                      notes="全部成交")
        assert new_status == DecisionStatus.MONITORING

    def test_from_pending_raises(self) -> None:
        with pytest.raises(DecisionStateError, match="Cannot execute from"):
            mark_executed(DecisionStatus.PENDING)


class TestClose:
    """Test close convenience function."""

    def test_from_monitoring(self) -> None:
        new_status, _ = close(DecisionStatus.MONITORING, notes="所有仓位已平")
        assert new_status == DecisionStatus.CLOSED

    def test_from_pending_raises(self) -> None:
        with pytest.raises(DecisionStateError, match="Cannot close from"):
            close(DecisionStatus.PENDING)


class TestHappyPath:
    """Test complete lifecycle paths."""

    def test_full_lifecycle(self) -> None:
        """PENDING → APPROVED → PARTIALLY_EXECUTED → MONITORING → CLOSED."""
        s = DecisionStatus.PENDING

        s, _ = approve(s, reviewer="张三")
        assert s == DecisionStatus.APPROVED

        s, _ = mark_executed(s, notes="600519 1000股已成交")
        assert s == DecisionStatus.PARTIALLY_EXECUTED

        s, _ = mark_executed(s, notes="剩余全部成交")
        assert s == DecisionStatus.MONITORING

        s, _ = close(s, notes="所有持仓已平")
        assert s == DecisionStatus.CLOSED
        assert s.is_terminal is True

    def test_modified_path(self) -> None:
        """PENDING → MODIFIED → APPROVED."""
        s = DecisionStatus.PENDING

        s, _ = modify(s, reviewer="李四", notes="移除603986(股数不足)")
        assert s == DecisionStatus.MODIFIED

        s, _ = approve(s, reviewer="李四")
        assert s == DecisionStatus.APPROVED

    def test_rejected_path(self) -> None:
        """PENDING → REJECTED (terminal)."""
        s = DecisionStatus.PENDING

        s, _ = reject(s, reviewer="王五", notes="回测验证未通过")
        assert s == DecisionStatus.REJECTED
        assert s.is_terminal is True

    def test_direct_to_monitoring(self) -> None:
        """APPROVED → MONITORING (skip partially_executed if all at once)."""
        s = DecisionStatus.PENDING
        s, _ = approve(s, reviewer="张三")
        assert s == DecisionStatus.APPROVED

        s, _ = transition(DecisionStatus.APPROVED, DecisionStatus.MONITORING,
                          actor="system", notes="批量全部成交")
        assert s == DecisionStatus.MONITORING


class TestStatusTransitionRecord:
    """Test StatusTransition audit record."""

    def test_repr(self) -> None:
        r = StatusTransition(
            from_status=DecisionStatus.PENDING,
            to_status=DecisionStatus.APPROVED,
            actor="测试",
        )
        assert "pending" in repr(r)
        assert "approved" in repr(r)
        assert "测试" in repr(r)

    def test_defaults(self) -> None:
        r = StatusTransition(
            from_status=DecisionStatus.PENDING,
            to_status=DecisionStatus.CLOSED,
        )
        assert r.timestamp != ""
        assert r.actor == ""
        assert r.notes == ""


class TestDecisionStateError:
    """Test DecisionStateError exception."""

    def test_contains_status_info(self) -> None:
        err = DecisionStateError(DecisionStatus.REJECTED, DecisionStatus.APPROVED)
        assert err.from_status == DecisionStatus.REJECTED
        assert err.to_status == DecisionStatus.APPROVED

    def test_is_value_error(self) -> None:
        err = DecisionStateError(DecisionStatus.PENDING, DecisionStatus.CLOSED)
        assert isinstance(err, ValueError)


# ==================================================================
# HumanReview + DecisionPackage integration tests (P0.2)
# ==================================================================


class TestHumanReviewStatus:
    """Test HumanReview with DecisionStatus integration."""

    def test_default_status_is_pending(self) -> None:
        from qp.decision.decision_package import HumanReview

        hr = HumanReview()
        assert hr.status == "pending"
        assert hr.current_status == DecisionStatus.PENDING
        assert hr.is_pending is True
        assert hr.is_terminal is False

    def test_record_transition_updates_status(self) -> None:
        from qp.decision.decision_package import HumanReview

        hr = HumanReview()
        hr.record_transition(DecisionStatus.APPROVED, actor="张三", notes="审核通过")
        assert hr.status == "approved"
        assert hr.current_status == DecisionStatus.APPROVED
        assert hr.reviewed is True  # legacy compat
        assert hr.reviewer == "张三"
        assert hr.notes == "审核通过"

    def test_record_transition_appends_history(self) -> None:
        from qp.decision.decision_package import HumanReview

        hr = HumanReview()
        hr.record_transition(DecisionStatus.APPROVED, actor="张三")
        hr.record_transition(DecisionStatus.PARTIALLY_EXECUTED, notes="部分成交")

        assert len(hr.status_history) == 2
        assert hr.status_history[0]["to_status"] == "approved"
        assert hr.status_history[0]["actor"] == "张三"
        assert hr.status_history[1]["to_status"] == "partially_executed"

    def test_record_transition_legacy_executed_compat(self) -> None:
        from qp.decision.decision_package import HumanReview

        hr = HumanReview()
        hr.record_transition(DecisionStatus.APPROVED)
        hr.record_transition(DecisionStatus.PARTIALLY_EXECUTED)

        assert hr.executed is True
        assert hr.execution_time != ""

    def test_full_lifecycle(self) -> None:
        from qp.decision.decision_package import HumanReview

        hr = HumanReview()
        assert hr.status == "pending"

        hr.record_transition(DecisionStatus.APPROVED, actor="张三")
        assert hr.status == "approved"
        assert hr.reviewed is True

        hr.record_transition(DecisionStatus.PARTIALLY_EXECUTED, notes="600519已成交")
        assert hr.status == "partially_executed"
        assert hr.executed is True

        hr.record_transition(DecisionStatus.MONITORING, notes="全部成交")
        assert hr.status == "monitoring"

        hr.record_transition(DecisionStatus.CLOSED, notes="所有仓位已平")
        assert hr.status == "closed"
        assert hr.is_terminal is True
        assert len(hr.status_history) == 4


class TestDecisionPackageStatusTransitions:
    """Test DecisionPackage status transition methods."""

    def test_approve_from_pending(self) -> None:
        from qp.decision.decision_package import DecisionPackage

        dp = DecisionPackage(package_id="dp-test-001", date="2026-07-30")
        assert dp.status == DecisionStatus.PENDING

        record = dp.approve(reviewer="张三", notes="审核通过")
        assert dp.status == DecisionStatus.APPROVED
        assert dp.human_review.reviewed is True
        assert record.to_status == DecisionStatus.APPROVED

    def test_reject_from_pending(self) -> None:
        from qp.decision.decision_package import DecisionPackage

        dp = DecisionPackage(package_id="dp-test-002", date="2026-07-30")
        dp.reject(reviewer="李四", notes="策略验证未通过")
        assert dp.status == DecisionStatus.REJECTED
        assert dp.human_review.is_terminal is True

    def test_modify_then_approve(self) -> None:
        from qp.decision.decision_package import DecisionPackage

        dp = DecisionPackage(package_id="dp-test-003", date="2026-07-30")
        dp.modify(reviewer="王五", notes="移除603986")
        assert dp.status == DecisionStatus.MODIFIED

        dp.approve(reviewer="王五")
        assert dp.status == DecisionStatus.APPROVED

    def test_invalid_transition_raises(self) -> None:
        from qp.decision.decision_package import DecisionPackage

        dp = DecisionPackage(package_id="dp-test-004", date="2026-07-30")
        dp.approve(reviewer="张三")

        with pytest.raises(DecisionStateError):
            dp.approve()  # Already approved, can't approve again

    def test_executed_then_close(self) -> None:
        from qp.decision.decision_package import DecisionPackage

        dp = DecisionPackage(package_id="dp-test-005", date="2026-07-30")
        dp.approve(reviewer="张三")
        dp.mark_executed(notes="部分成交")
        assert dp.status == DecisionStatus.PARTIALLY_EXECUTED

        dp.mark_executed(notes="全部成交")
        assert dp.status == DecisionStatus.MONITORING

        dp.close(notes="持仓已平")
        assert dp.status == DecisionStatus.CLOSED

    def test_transition_status_with_string(self) -> None:
        from qp.decision.decision_package import DecisionPackage

        dp = DecisionPackage(package_id="dp-test-006", date="2026-07-30")
        dp.transition_status("approved", actor="系统", notes="测试字符串状态")
        assert dp.status == DecisionStatus.APPROVED


class TestDecisionPackageSerialization:
    """Test DecisionPackage JSON round-trip with status fields."""

    def test_round_trip_preserves_status(self) -> None:
        from qp.decision.decision_package import DecisionPackage

        dp = DecisionPackage(package_id="dp-test-serial", date="2026-07-30")
        dp.approve(reviewer="张三", notes="审核通过")
        dp.mark_executed(notes="已成交")

        data = dp.to_dict()
        assert data["human_review"]["status"] == "partially_executed"
        assert len(data["human_review"]["status_history"]) == 2

        # Round-trip
        dp2 = DecisionPackage.from_dict(data)
        assert dp2.human_review.status == "partially_executed"
        assert dp2.human_review.current_status == DecisionStatus.PARTIALLY_EXECUTED
        assert len(dp2.human_review.status_history) == 2

    def test_backward_compat_old_format_no_status(self) -> None:
        """Old JSON without status field defaults to PENDING."""
        from qp.decision.decision_package import DecisionPackage

        data = {
            "package_id": "dp-old-format",
            "date": "2026-06-01",
            "human_review": {
                "reviewed": False,
                "reviewer": "",
                "notes": "",
                "executed": False,
                "execution_time": "",
            },
        }
        dp = DecisionPackage.from_dict(data)
        assert dp.human_review.status == "pending"
        assert dp.human_review.current_status == DecisionStatus.PENDING
        assert dp.human_review.status_history == []

    def test_backward_compat_old_format_reviewed(self) -> None:
        """Old JSON with reviewed=true infers APPROVED."""
        from qp.decision.decision_package import DecisionPackage

        data = {
            "package_id": "dp-old-reviewed",
            "date": "2026-06-02",
            "human_review": {
                "reviewed": True,
                "reviewer": "张三",
                "notes": "已审核",
                "executed": False,
                "execution_time": "",
            },
        }
        dp = DecisionPackage.from_dict(data)
        assert dp.human_review.status == "approved"
        assert dp.human_review.current_status == DecisionStatus.APPROVED
        assert len(dp.human_review.status_history) == 1
        assert dp.human_review.status_history[0]["to_status"] == "approved"
        assert dp.human_review.status_history[0]["notes"] == "Migrated from legacy format"

    def test_backward_compat_old_format_executed(self) -> None:
        """Old JSON with executed=true infers MONITORING."""
        from qp.decision.decision_package import DecisionPackage

        data = {
            "package_id": "dp-old-executed",
            "date": "2026-06-03",
            "human_review": {
                "reviewed": True,
                "reviewer": "张三",
                "notes": "",
                "executed": True,
                "execution_time": "2026-06-03T10:00:00",
            },
        }
        dp = DecisionPackage.from_dict(data)
        assert dp.human_review.status == "monitoring"
        assert dp.human_review.current_status == DecisionStatus.MONITORING

    def test_index_includes_status(self) -> None:
        from qp.decision.decision_package import DecisionPackage

        dp = DecisionPackage(package_id="dp-test-index", date="2026-07-30")
        dp.approve(reviewer="测试员")

        data = dp.to_dict()
        # Index entry is built from to_dict() fields
        # Check that status is in human_review
        assert "status" in data["human_review"]


# ==================================================================
# DecisionService status transition tests (P0.3)
# ==================================================================


class TestDecisionServiceTransitions:
    """Test DecisionService state-machine-backed transitions."""

    @pytest.fixture
    def tmp_dp(self, tmp_path) -> str:
        """Create a temporary DecisionPackage JSON for testing transitions."""
        from qp.decision.decision_package import DecisionPackage

        dp = DecisionPackage(package_id="dp-svc-test-001", date="2026-07-30")
        json_path = tmp_path / "dp-svc-test-001.json"
        dp.to_json(json_path)
        return str(json_path)

    def test_approve_transitions_to_approved(self, monkeypatch, tmp_path) -> None:
        """Approve moves PENDING → APPROVED."""
        from qp.decision.decision_package import DecisionPackage
        from qp.web.services.decision_service import DecisionService

        # Create DP in temp dir
        dp = DecisionPackage(package_id="dp-svc-approve", date="2026-07-30")
        path = tmp_path / "dp-svc-approve.json"
        dp.to_json(path)

        # Patch _resolve_path to point to our temp file
        monkeypatch.setattr(
            "qp.web.services.decision_service._resolve_path",
            lambda pid: tmp_path / f"{pid}.json",
        )
        # Also patch index update to no-op
        monkeypatch.setattr(
            DecisionPackage, "update_index", lambda self: None,
        )

        svc = DecisionService()
        result = svc.approve("dp-svc-approve", reviewer="张三", notes="通过")

        assert result is not None
        assert result["human_review"]["status"] == "approved"
        assert result["human_review"]["status_label"] == "已批准"
        assert result["human_review"]["reviewed"] is True
        assert result["human_review"]["reviewer"] == "张三"

        # Verify on-disk persistence
        dp2 = DecisionPackage.from_json(path)
        assert dp2.human_review.status == "approved"

    def test_reject_transitions_to_rejected(self, monkeypatch, tmp_path) -> None:
        """Reject moves PENDING → REJECTED."""
        from qp.decision.decision_package import DecisionPackage
        from qp.web.services.decision_service import DecisionService

        dp = DecisionPackage(package_id="dp-svc-reject", date="2026-07-30")
        path = tmp_path / "dp-svc-reject.json"
        dp.to_json(path)

        monkeypatch.setattr(
            "qp.web.services.decision_service._resolve_path",
            lambda pid: tmp_path / f"{pid}.json",
        )
        monkeypatch.setattr(DecisionPackage, "update_index", lambda self: None)

        svc = DecisionService()
        result = svc.reject("dp-svc-reject", reviewer="李四", notes="验证未通过")

        assert result is not None
        assert result["human_review"]["status"] == "rejected"
        assert result["human_review"]["is_terminal"] is True

    def test_modify_then_approve(self, monkeypatch, tmp_path) -> None:
        """MODIFIED path: PENDING → MODIFIED → APPROVED."""
        from qp.decision.decision_package import DecisionPackage
        from qp.web.services.decision_service import DecisionService

        dp = DecisionPackage(package_id="dp-svc-modify", date="2026-07-30")
        path = tmp_path / "dp-svc-modify.json"
        dp.to_json(path)

        monkeypatch.setattr(
            "qp.web.services.decision_service._resolve_path",
            lambda pid: tmp_path / f"{pid}.json",
        )
        monkeypatch.setattr(DecisionPackage, "update_index", lambda self: None)

        svc = DecisionService()

        # First: modify
        r1 = svc.modify("dp-svc-modify", reviewer="王五", notes="移除603986")
        assert r1 is not None
        assert r1["human_review"]["status"] == "modified"

        # Then: approve
        r2 = svc.approve("dp-svc-modify", reviewer="王五")
        assert r2 is not None
        assert r2["human_review"]["status"] == "approved"

        # Check status history on disk
        dp2 = DecisionPackage.from_json(path)
        assert len(dp2.human_review.status_history) == 2

    def test_mark_executed_progressive(self, monkeypatch, tmp_path) -> None:
        """First call: APPROVED → PARTIALLY_EXECUTED. Second: → MONITORING."""
        from qp.decision.decision_package import DecisionPackage
        from qp.web.services.decision_service import DecisionService

        dp = DecisionPackage(package_id="dp-svc-exec", date="2026-07-30")
        dp.approve(reviewer="张三")
        path = tmp_path / "dp-svc-exec.json"
        dp.to_json(path)

        monkeypatch.setattr(
            "qp.web.services.decision_service._resolve_path",
            lambda pid: tmp_path / f"{pid}.json",
        )
        monkeypatch.setattr(DecisionPackage, "update_index", lambda self: None)

        svc = DecisionService()

        r1 = svc.mark_executed("dp-svc-exec", notes="部分成交")
        assert r1 is not None
        assert r1["human_review"]["status"] == "partially_executed"

        r2 = svc.mark_executed("dp-svc-exec", notes="全部成交")
        assert r2 is not None
        assert r2["human_review"]["status"] == "monitoring"

    def test_close_from_monitoring(self, monkeypatch, tmp_path) -> None:
        """Full lifecycle: PENDING → APPROVED → PARTIALLY_EXECUTED → MONITORING → CLOSED."""
        from qp.decision.decision_package import DecisionPackage
        from qp.web.services.decision_service import DecisionService

        dp = DecisionPackage(package_id="dp-svc-close", date="2026-07-30")
        dp.approve(reviewer="张三")
        dp.mark_executed(notes="部分成交")  # APPROVED → PARTIALLY_EXECUTED
        dp.mark_executed(notes="全部成交")  # PARTIALLY_EXECUTED → MONITORING
        assert dp.status.value == "monitoring"
        path = tmp_path / "dp-svc-close.json"
        dp.to_json(path)

        monkeypatch.setattr(
            "qp.web.services.decision_service._resolve_path",
            lambda pid: tmp_path / f"{pid}.json",
        )
        monkeypatch.setattr(DecisionPackage, "update_index", lambda self: None)

        svc = DecisionService()

        r = svc.close("dp-svc-close", notes="所有持仓已平")
        assert r is not None
        assert r["human_review"]["status"] == "closed"
        assert r["human_review"]["is_terminal"] is True

    def test_invalid_transition_returns_none(self, monkeypatch, tmp_path) -> None:
        """Invalid transition (e.g. approve already approved) returns None."""
        from qp.decision.decision_package import DecisionPackage
        from qp.web.services.decision_service import DecisionService

        dp = DecisionPackage(package_id="dp-svc-invalid", date="2026-07-30")
        dp.approve(reviewer="张三")
        path = tmp_path / "dp-svc-invalid.json"
        dp.to_json(path)

        monkeypatch.setattr(
            "qp.web.services.decision_service._resolve_path",
            lambda pid: tmp_path / f"{pid}.json",
        )
        monkeypatch.setattr(DecisionPackage, "update_index", lambda self: None)

        svc = DecisionService()
        result = svc.approve("dp-svc-invalid", reviewer="张三")  # Already approved
        assert result is None  # Should fail gracefully

    def test_missing_package_returns_none(self) -> None:
        from qp.web.services.decision_service import DecisionService

        svc = DecisionService()
        result = svc.approve("dp-nonexistent-999")
        assert result is None

    def test_legacy_mark_reviewed_compat(self, monkeypatch, tmp_path) -> None:
        """Legacy mark_reviewed() delegates to approve()."""
        from qp.decision.decision_package import DecisionPackage
        from qp.web.services.decision_service import DecisionService

        dp = DecisionPackage(package_id="dp-svc-legacy", date="2026-07-30")
        path = tmp_path / "dp-svc-legacy.json"
        dp.to_json(path)

        monkeypatch.setattr(
            "qp.web.services.decision_service._resolve_path",
            lambda pid: tmp_path / f"{pid}.json",
        )
        monkeypatch.setattr(DecisionPackage, "update_index", lambda self: None)

        svc = DecisionService()
        result = svc.mark_reviewed("dp-svc-legacy", notes="legacy call")

        assert result is not None
        assert result["human_review"]["status"] == "approved"
        assert result["human_review"]["reviewed"] is True

    def test_status_history_in_output(self, monkeypatch, tmp_path) -> None:
        """Output dict includes status_history and _next fields."""
        from qp.decision.decision_package import DecisionPackage
        from qp.web.services.decision_service import DecisionService

        dp = DecisionPackage(package_id="dp-svc-output", date="2026-07-30")
        path = tmp_path / "dp-svc-output.json"
        dp.to_json(path)

        monkeypatch.setattr(
            "qp.web.services.decision_service._resolve_path",
            lambda pid: tmp_path / f"{pid}.json",
        )
        monkeypatch.setattr(DecisionPackage, "update_index", lambda self: None)

        svc = DecisionService()
        result = svc.approve("dp-svc-output", reviewer="系统")

        assert result is not None
        assert "status_history" in result["human_review"]
        assert len(result["human_review"]["status_history"]) == 1
        assert "_next" in result["human_review"]
        # From APPROVED, next valid transitions are PARTIALLY_EXECUTED and MONITORING
        assert "partially_executed" in result["human_review"]["_next"]
        assert "monitoring" in result["human_review"]["_next"]


# ==================================================================
# Validation rule details tests (P1.3)
# ==================================================================


class TestValidationRuleDetails:
    """Test structured per-rule validation failure details."""

    def test_validation_dict_includes_rules(self) -> None:
        """Simulated pipeline output includes per-rule results."""
        # Simulate what daily_pipeline Step 7 now produces
        validation_results = {
            "momentum_v1.0": {
                "stage": "backtest_passed",
                "score": 16.67,
                "passed": False,
                "rules_total": 12,
                "rules_failed": 10,
                "recommendation": "策略未通过",
                "rules": [
                    {
                        "rule_name": "rank_ic",
                        "status": "fail",
                        "score": 5.0,
                        "threshold": 0.02,
                        "actual_value": 0.008,
                        "detail": "IC below threshold",
                    },
                    {
                        "rule_name": "sharpe_ratio",
                        "status": "fail",
                        "score": 5.0,
                        "threshold": 0.5,
                        "actual_value": -0.2,
                        "detail": "Sharpe ratio too low",
                    },
                    {
                        "rule_name": "code_review",
                        "status": "pass",
                        "score": 25.0,
                        "threshold": None,
                        "actual_value": None,
                        "detail": "Code review completed",
                    },
                ],
            },
        }

        v = validation_results["momentum_v1.0"]
        assert "rules" in v
        rules = v["rules"]
        assert len(rules) == 3
        failed = [r for r in rules if r["status"] == "fail"]
        assert len(failed) == 2
        assert failed[0]["rule_name"] == "rank_ic"
        assert failed[0]["actual_value"] == 0.008

    def test_decision_package_round_trip_with_rules(self) -> None:
        """DecisionPackage preserves per-rule details through JSON round-trip."""
        from qp.decision.decision_package import DecisionPackage

        dp = DecisionPackage(package_id="dp-p13-test", date="2026-07-30")
        dp.validation["test_strategy"] = {
            "stage": "backtest_passed",
            "score": 50.0,
            "passed": False,
            "rules_total": 3,
            "rules_failed": 2,
            "rules": [
                {
                    "rule_name": "sharpe_ratio",
                    "status": "fail",
                    "score": 0.0,
                    "threshold": 0.5,
                    "actual_value": 0.1,
                    "detail": "Insufficient risk-adjusted return",
                },
            ],
        }

        data = dp.to_dict()
        dp2 = DecisionPackage.from_dict(data)

        v2 = dp2.validation["test_strategy"]
        assert "rules" in v2
        assert len(v2["rules"]) == 1
        assert v2["rules"][0]["rule_name"] == "sharpe_ratio"
        assert v2["rules"][0]["status"] == "fail"

    def test_markdown_includes_failed_rules(self) -> None:
        """Markdown report shows which rules failed and why."""
        from qp.decision.decision_package import DecisionPackage

        dp = DecisionPackage(package_id="dp-p13-md", date="2026-07-30")
        dp.validation["momentum_v1.0"] = {
            "stage": "backtest_passed",
            "score": 16.67,
            "passed": False,
            "rules_total": 3,
            "rules_failed": 2,
            "rules": [
                {
                    "rule_name": "rank_ic",
                    "status": "fail",
                    "score": 5.0,
                    "threshold": 0.02,
                    "actual_value": 0.008,
                    "detail": "IC below minimum threshold",
                },
                {
                    "rule_name": "sharpe_ratio",
                    "status": "fail",
                    "score": 0.0,
                    "threshold": 0.5,
                    "actual_value": -0.2,
                    "detail": "",
                },
                {
                    "rule_name": "code_review",
                    "status": "pass",
                    "score": 25.0,
                    "threshold": None,
                    "actual_value": None,
                    "detail": "",
                },
            ],
        }

        md_lines = dp._build_markdown()
        md = "\n".join(md_lines)

        # Should show failed rules section
        assert "2/3 rules failed" in md
        assert "rank_ic" in md
        assert "sharpe_ratio" in md
        assert "IC below minimum threshold" in md
        # passed rule should NOT be in failure list
        assert "code_review" not in md.split("**momentum")[1] if "**momentum" in md else True

    def test_empty_rules_no_crash(self) -> None:
        """Validation without rules list doesn't crash the markdown builder."""
        from qp.decision.decision_package import DecisionPackage

        dp = DecisionPackage(package_id="dp-p13-empty", date="2026-07-30")
        dp.validation["no_rules_strategy"] = {
            "stage": "unknown",
            "score": 0,
            "passed": False,
            "rules_total": 0,
            "rules_failed": 0,
        }

        md_lines = dp._build_markdown()
        md = "\n".join(md_lines)
        # Should render without crashing
        assert "验证门禁" in md
        assert "no_rules_strategy" in md

    def test_validation_no_rules_key_backward_compat(self) -> None:
        """Old format without 'rules' key is handled gracefully."""
        from qp.decision.decision_package import DecisionPackage

        dp = DecisionPackage(package_id="dp-old-format", date="2026-06-01")
        dp.validation["old_strategy"] = {
            "stage": "backtest_passed",
            "score": 80.0,
            "passed": True,
            "rules_total": 10,
            "rules_failed": 0,
            # No "rules" key — old format
        }

        data = dp.to_dict()
        dp2 = DecisionPackage.from_dict(data)
        assert "rules" not in dp2.validation["old_strategy"]
        # Should render without crashing
        md = "\n".join(dp2._build_markdown())
        assert "old_strategy" in md


# ==================================================================
# Position + PositionLedger tests (P2.1)
# ==================================================================


class TestPosition:
    """Test Position dataclass."""

    def test_construct_default(self) -> None:
        from qp.decision.position_ledger import Position
        from qp.shared.types import PositionState

        p = Position(symbol="600519", entry_price=1450.0, shares=100)
        assert p.symbol == "600519"
        assert p.entry_price == 1450.0
        assert p.shares == 100
        assert p.status == PositionState.HOLDING
        assert p.is_active is True

    def test_market_value(self) -> None:
        from qp.decision.position_ledger import Position

        p = Position(symbol="000001", entry_price=12.5, shares=1000)
        assert p.market_value == 12500.0

    def test_realized_pnl_when_closed(self) -> None:
        from qp.decision.position_ledger import Position
        from qp.shared.types import PositionState

        p = Position(symbol="600519", entry_price=100.0, shares=500,
                      status=PositionState.CLOSED, exit_price=110.0)
        assert p.realized_pnl == 5000.0  # (110-100)*500

    def test_realized_pnl_when_active(self) -> None:
        from qp.decision.position_ledger import Position

        p = Position(symbol="600519", entry_price=100.0, shares=500,
                      exit_price=110.0)  # Active, not closed
        assert p.realized_pnl == 0.0  # Not realized until closed

    def test_to_dict_from_dict_round_trip(self) -> None:
        from qp.decision.position_ledger import Position

        p = Position(
            position_id="P-00001", symbol="600519",
            entry_date="2026-07-30", entry_price=1450.0, shares=100,
            strategy_id="momentum_v1.0", decision_id="dp-test-001",
        )
        d = p.to_dict()
        p2 = Position.from_dict(d)
        assert p2.position_id == "P-00001"
        assert p2.symbol == "600519"
        assert p2.entry_price == 1450.0
        assert p2.is_active is True

    def test_is_active_for_holding(self) -> None:
        from qp.decision.position_ledger import Position
        from qp.shared.types import PositionState

        assert Position(status=PositionState.HOLDING).is_active is True
        assert Position(status=PositionState.REDUCING).is_active is True
        assert Position(status=PositionState.CLOSED).is_active is False
        assert Position(status=PositionState.ARCHIVED).is_active is False


class TestPositionLedger:
    """Test PositionLedger CRUD and persistence."""

    def test_open_and_get(self, tmp_path) -> None:
        import qp.decision.position_ledger as mod

        original_dir = str(mod.POSITIONS_DIR)
        try:
            mod.POSITIONS_DIR = tmp_path
            mod.POSITIONS_PARQUET = tmp_path / "positions.parquet"
            mod.POSITIONS_INDEX = tmp_path / "index.json"

            ledger = mod.PositionLedger()
            pos = ledger.open("600519", 1450.0, 100,
                              strategy_id="momentum_v1.0",
                              decision_id="dp-test-001")

            assert pos.position_id.startswith("P-")
            assert pos.symbol == "600519"
            assert pos.is_active is True

            # Load back
            loaded = ledger.get(pos.position_id)
            assert loaded is not None
            assert loaded.symbol == "600519"
            assert loaded.entry_price == 1450.0
        finally:
            mod.POSITIONS_DIR = Path(original_dir)
            mod.POSITIONS_PARQUET = Path(original_dir) / "positions.parquet"
            mod.POSITIONS_INDEX = Path(original_dir) / "index.json"

    def test_open_close_cycle(self, tmp_path) -> None:
        import qp.decision.position_ledger as mod

        original_dir = str(mod.POSITIONS_DIR)
        try:
            mod.POSITIONS_DIR = tmp_path
            mod.POSITIONS_PARQUET = tmp_path / "positions.parquet"
            mod.POSITIONS_INDEX = tmp_path / "index.json"

            ledger = mod.PositionLedger()
            pos = ledger.open("000001", 12.5, 1000, decision_id="dp-test")

            # Close it
            closed = ledger.close(pos.position_id, 15.0, exit_reason="target_reached")
            assert closed is not None
            assert closed.is_active is False
            assert closed.exit_price == 15.0
            assert closed.pnl == pytest.approx(2500.0)  # (15-12.5)*1000
            assert closed.pnl_pct == pytest.approx(0.2)

            # Verify persisted
            loaded = ledger.get(pos.position_id)
            assert loaded is not None
            assert loaded.is_active is False
        finally:
            mod.POSITIONS_DIR = Path(original_dir)
            mod.POSITIONS_PARQUET = Path(original_dir) / "positions.parquet"
            mod.POSITIONS_INDEX = Path(original_dir) / "index.json"

    def test_get_active_only(self, tmp_path) -> None:
        import qp.decision.position_ledger as mod

        original_dir = str(mod.POSITIONS_DIR)
        try:
            mod.POSITIONS_DIR = tmp_path
            mod.POSITIONS_PARQUET = tmp_path / "positions.parquet"
            mod.POSITIONS_INDEX = tmp_path / "index.json"

            ledger = mod.PositionLedger()
            p1 = ledger.open("A", 10.0, 100, decision_id="dp-x")
            ledger.open("B", 20.0, 200, decision_id="dp-x")
            ledger.close(p1.position_id, 12.0)

            active = ledger.get_active()
            assert len(active) == 1
            assert active[0].symbol == "B"
        finally:
            mod.POSITIONS_DIR = Path(original_dir)
            mod.POSITIONS_PARQUET = Path(original_dir) / "positions.parquet"
            mod.POSITIONS_INDEX = Path(original_dir) / "index.json"

    def test_get_by_decision(self, tmp_path) -> None:
        import qp.decision.position_ledger as mod

        original_dir = str(mod.POSITIONS_DIR)
        try:
            mod.POSITIONS_DIR = tmp_path
            mod.POSITIONS_PARQUET = tmp_path / "positions.parquet"
            mod.POSITIONS_INDEX = tmp_path / "index.json"

            ledger = mod.PositionLedger()
            ledger.open("A", 10.0, 100, decision_id="dp-001")
            ledger.open("B", 20.0, 200, decision_id="dp-001")
            ledger.open("C", 30.0, 300, decision_id="dp-002")

            from_dp1 = ledger.get_by_decision("dp-001")
            assert len(from_dp1) == 2
        finally:
            mod.POSITIONS_DIR = Path(original_dir)
            mod.POSITIONS_PARQUET = Path(original_dir) / "positions.parquet"
            mod.POSITIONS_INDEX = Path(original_dir) / "index.json"

    def test_total_active_value(self, tmp_path) -> None:
        import qp.decision.position_ledger as mod

        original_dir = str(mod.POSITIONS_DIR)
        try:
            mod.POSITIONS_DIR = tmp_path
            mod.POSITIONS_PARQUET = tmp_path / "positions.parquet"
            mod.POSITIONS_INDEX = tmp_path / "index.json"

            ledger = mod.PositionLedger()
            ledger.open("A", 10.0, 100, decision_id="dp-x")  # 1000
            ledger.open("B", 20.0, 50, decision_id="dp-x")   # 1000

            assert ledger.total_active_value() == 2000.0
        finally:
            mod.POSITIONS_DIR = Path(original_dir)
            mod.POSITIONS_PARQUET = Path(original_dir) / "positions.parquet"
            mod.POSITIONS_INDEX = Path(original_dir) / "index.json"

    def test_total_realized_pnl(self, tmp_path) -> None:
        import qp.decision.position_ledger as mod

        original_dir = str(mod.POSITIONS_DIR)
        try:
            mod.POSITIONS_DIR = tmp_path
            mod.POSITIONS_PARQUET = tmp_path / "positions.parquet"
            mod.POSITIONS_INDEX = tmp_path / "index.json"

            ledger = mod.PositionLedger()
            p1 = ledger.open("A", 10.0, 100, decision_id="dp-x")
            p2 = ledger.open("B", 20.0, 200, decision_id="dp-x")
            ledger.close(p1.position_id, 15.0)  # +500
            ledger.close(p2.position_id, 18.0)  # -400

            pnl = ledger.total_realized_pnl()
            assert pnl == 100.0  # 500 + (-400)
        finally:
            mod.POSITIONS_DIR = Path(original_dir)
            mod.POSITIONS_PARQUET = Path(original_dir) / "positions.parquet"
            mod.POSITIONS_INDEX = Path(original_dir) / "index.json"

    def test_close_nonexistent_returns_none(self, tmp_path) -> None:
        import qp.decision.position_ledger as mod

        original_dir = str(mod.POSITIONS_DIR)
        try:
            mod.POSITIONS_DIR = tmp_path
            mod.POSITIONS_PARQUET = tmp_path / "positions.parquet"
            mod.POSITIONS_INDEX = tmp_path / "index.json"

            ledger = mod.PositionLedger()
            result = ledger.close("P-99999", 100.0)
            assert result is None
        finally:
            mod.POSITIONS_DIR = Path(original_dir)
            mod.POSITIONS_PARQUET = Path(original_dir) / "positions.parquet"
            mod.POSITIONS_INDEX = Path(original_dir) / "index.json"

    def test_open_from_decision(self, tmp_path) -> None:
        import qp.decision.position_ledger as mod
        from qp.decision.decision_package import DecisionPackage
        from qp.decision.models import TradeRecommendation

        original_dir = str(mod.POSITIONS_DIR)
        try:
            mod.POSITIONS_DIR = tmp_path
            mod.POSITIONS_PARQUET = tmp_path / "positions.parquet"
            mod.POSITIONS_INDEX = tmp_path / "index.json"

            # Create an approved DecisionPackage with recommendations
            dp = DecisionPackage(package_id="dp-bulk-test", date="2026-07-30")
            dp.approve(reviewer="测试")
            dp.report.recommendations = [
                TradeRecommendation(symbol="600519", action="BUY",
                                    estimated_price=1450.0, quantity_shares=100,
                                    target_weight_pct=10.0, strategy="momentum_v1.0",
                                    reason="排名 #1"),
                TradeRecommendation(symbol="000001", action="BUY",
                                    estimated_price=12.5, quantity_shares=1000,
                                    target_weight_pct=8.0, strategy="value_v1.0",
                                    reason="排名 #2"),
                TradeRecommendation(symbol="000002", action="SELL",
                                    estimated_price=50.0, quantity_shares=0),
            ]

            ledger = mod.PositionLedger()
            positions = ledger.open_from_decision(dp)

            assert len(positions) == 2  # SELL skipped
            assert positions[0].symbol == "600519"
            assert positions[1].symbol == "000001"
            assert all(p.decision_id == "dp-bulk-test" for p in positions)

            # Verify persisted
            active = ledger.get_active()
            assert len(active) == 2
        finally:
            mod.POSITIONS_DIR = Path(original_dir)
            mod.POSITIONS_PARQUET = Path(original_dir) / "positions.parquet"
            mod.POSITIONS_INDEX = Path(original_dir) / "index.json"

    def test_sequential_ids(self, tmp_path) -> None:
        import qp.decision.position_ledger as mod

        original_dir = str(mod.POSITIONS_DIR)
        try:
            mod.POSITIONS_DIR = tmp_path
            mod.POSITIONS_PARQUET = tmp_path / "positions.parquet"
            mod.POSITIONS_INDEX = tmp_path / "index.json"

            ledger = mod.PositionLedger()
            p1 = ledger.open("A", 10.0, 100, decision_id="dp-x")
            p2 = ledger.open("B", 20.0, 200, decision_id="dp-x")

            assert p1.position_id == "P-00001"
            assert p2.position_id == "P-00002"
        finally:
            mod.POSITIONS_DIR = Path(original_dir)
            mod.POSITIONS_PARQUET = Path(original_dir) / "positions.parquet"
            mod.POSITIONS_INDEX = Path(original_dir) / "index.json"
