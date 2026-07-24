"""ValidationResult & GateResult — output of a Validation Gate run.

See rule.md §10.1-10.2 and ADR-016 for the complete specification.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from qp.shared.types import ValidationStatus

# ------------------------------------------------------------------
# Gate Decision — 系统决策，在 ValidationResult 之上
# ------------------------------------------------------------------


class GateDecision(StrEnum):
    """系统对一次 Gate 评估的决策。

    与 ValidationResult.status (PASS/FAIL) 不同，
    GateDecision 表达了"系统应该怎么做"。
    """

    PASSED = "passed"  # 全通过 → 可进入下一阶段
    RESEARCH_ONLY = "research_only"  # 有预测力但不可交易 → 归档研究
    BLOCKED = "blocked"  # 数据/因子问题 → 修复后重试
    OVERRIDDEN = "overridden"  # 人工跳过 Gate（需记录原因）


# ------------------------------------------------------------------
# Rule / Validation results
# ------------------------------------------------------------------


@dataclass
class RuleResult:
    """Result of a single validation rule check.

    Attributes:
        rule_name: Unique rule identifier (e.g. 'rank_ic', 'sharpe_ratio').
        status: PASS or FAIL.
        score: Numeric score (higher = better).
        threshold: The threshold value that was checked against.
        actual_value: The observed value.
        detail: Human-readable explanation.
    """

    rule_name: str
    status: ValidationStatus
    score: float
    threshold: float | None = None
    actual_value: float | None = None
    detail: str = ""


@dataclass
class ValidationResult:
    """Aggregate result from the Validation Gate.

    A strategy must receive status=PASS on all rules before it can proceed
    to Paper Trading or Production (see StrategyLifecycle enum).

    Attributes:
        status: Overall PASS/FAIL — FAIL if any single rule failed.
        score: Weighted composite score (0–100).
        confidence: Confidence level (0–1) based on data quantity.
        rules: Per-rule results for audit trail.
        failed_rules: Convenience list of rule names that failed.
        recommendation: Human-readable next-step recommendation.
        metrics: Optional additional metrics (e.g. IC mean, Sharpe).
    """

    status: ValidationStatus = ValidationStatus.PASS
    score: float = 0.0
    confidence: float = 0.0
    rules: list[RuleResult] = field(default_factory=list)
    failed_rules: list[str] = field(default_factory=list)
    recommendation: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.status == ValidationStatus.PASS

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "score": self.score,
            "confidence": self.confidence,
            "failed_rules": self.failed_rules,
            "recommendation": self.recommendation,
            "rules": [
                {
                    "rule_name": r.rule_name,
                    "status": r.status.value,
                    "score": r.score,
                    "threshold": r.threshold,
                    "actual_value": r.actual_value,
                    "detail": r.detail,
                }
                for r in self.rules
            ],
            "metrics": self.metrics,
        }


# ------------------------------------------------------------------
# GateResult — 一次完整的 Gate 评估，桥接到实验记录和知识层
# ------------------------------------------------------------------


@dataclass
class GateResult:
    """一次完整的 Gate 评估结果，可持久化到 ExperimentRecord。

    与 ValidationResult（检查结果）的关系：
      ValidationResult → 映射为 GateDecision → 封装为 GateResult

    属性:
        strategy_id: 策略标识
        stage: 生命周期阶段 ("backtest_passed" | "paper_trading" | …)
        decision: 系统决策 (PASSED | RESEARCH_ONLY | BLOCKED | OVERRIDDEN)
        score: 综合评分 0–100
        confidence: 置信度 0–1
        timestamp: ISO 时间戳

        # 5 层 Gate 状态
        data_integrity: PASS | FAIL | NOT_RUN
        factor_validity: PASS | FAIL | NOT_RUN
        portfolio_conversion: PASS | FAIL | NOT_RUN
        robustness: PASS | FAIL | NOT_RUN
        cost_capacity: PASS | FAIL | NOT_RUN

        rules: 逐条检查结果
        recommendation: 人类可读的下一步建议
        artifacts: 产物文件路径列表
    """

    strategy_id: str
    stage: str
    decision: GateDecision
    score: float = 0.0
    confidence: float = 0.0
    timestamp: str = ""

    # 5 层 Gate
    data_integrity: str = "NOT_RUN"
    factor_validity: str = "NOT_RUN"
    portfolio_conversion: str = "NOT_RUN"
    robustness: str = "NOT_RUN"
    cost_capacity: str = "NOT_RUN"

    rules: list[RuleResult] = field(default_factory=list)
    recommendation: str = ""
    artifacts: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(UTC).isoformat()

    @property
    def passed(self) -> bool:
        return self.decision == GateDecision.PASSED

    @property
    def gate_levels(self) -> dict[str, str]:
        """返回五层 Gate 状态字典。"""
        return {
            "data_integrity": self.data_integrity,
            "factor_validity": self.factor_validity,
            "portfolio_conversion": self.portfolio_conversion,
            "robustness": self.robustness,
            "cost_capacity": self.cost_capacity,
        }

    @classmethod
    def from_validation(
        cls,
        strategy_id: str,
        stage: str,
        validation: ValidationResult,
        data_integrity: str = "NOT_RUN",
        robustness: str = "NOT_RUN",
        cost_capacity: str = "NOT_RUN",
    ) -> GateResult:
        """从 ValidationResult 映射为 GateResult。

        映射规则:
          - PASS → GateDecision.PASSED
          - 因子通过 + 组合失败 → RESEARCH_ONLY
          - 数据/因子失败 → BLOCKED
        """
        # Determine factor and portfolio pass status from rules
        factor_rules = [
            r
            for r in validation.rules
            if r.rule_name
            in {
                "rank_ic",
                "ic_ir",
                "ic_t_stat",
                "neutralization",
                "min_sample_period",
            }
        ]
        portfolio_rules = [r for r in validation.rules if r.rule_name in {"stratification"}]

        factor_pass = (
            all(r.status == ValidationStatus.PASS for r in factor_rules) if factor_rules else False
        )
        portfolio_pass = (
            all(r.status == ValidationStatus.PASS for r in portfolio_rules)
            if portfolio_rules
            else False
        )

        if validation.passed:
            decision = GateDecision.PASSED
        elif factor_pass and not portfolio_pass:
            decision = GateDecision.RESEARCH_ONLY
        elif data_integrity == "FAIL" or not factor_pass:
            decision = GateDecision.BLOCKED
        else:
            decision = GateDecision.BLOCKED

        # Build recommendation from failed rules
        if decision == GateDecision.PASSED:
            rec = f"策略 {strategy_id} 通过 {stage} 阶段检验，可推进到下一阶段。"
        elif decision == GateDecision.RESEARCH_ONLY:
            rec = (
                f"策略 {strategy_id} 具有统计预测力 (因子检验通过)，"
                f"但无法转化为投资组合收益。建议归档为研究资产，"
                f"后续进行因子工程改造。"
            )
        else:
            failed_names = ", ".join(validation.failed_rules)
            rec = f"策略 {strategy_id} 未通过检验: {failed_names}。请修复后重新实验。"

        return cls(
            strategy_id=strategy_id,
            stage=stage,
            decision=decision,
            score=validation.score,
            confidence=validation.confidence,
            data_integrity=data_integrity,
            factor_validity="PASS" if factor_pass else ("FAIL" if factor_rules else "NOT_RUN"),
            portfolio_conversion="PASS"
            if portfolio_pass
            else ("FAIL" if portfolio_rules else "NOT_RUN"),
            robustness=robustness,
            cost_capacity=cost_capacity,
            rules=validation.rules,
            recommendation=rec,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "stage": self.stage,
            "decision": self.decision.value,
            "score": self.score,
            "confidence": self.confidence,
            "timestamp": self.timestamp,
            "data_integrity": self.data_integrity,
            "factor_validity": self.factor_validity,
            "portfolio_conversion": self.portfolio_conversion,
            "robustness": self.robustness,
            "cost_capacity": self.cost_capacity,
            "rules": [
                {
                    "rule_name": r.rule_name,
                    "status": r.status.value,
                    "score": r.score,
                    "threshold": r.threshold,
                    "actual_value": r.actual_value,
                    "detail": r.detail,
                }
                for r in self.rules
            ],
            "recommendation": self.recommendation,
            "artifacts": self.artifacts,
        }

    def summary(self) -> str:
        """Print-friendly Gate report."""
        lines = [
            "",
            "=" * 60,
            "  Validation Gate Report",
            "=" * 60,
            f"  Strategy:     {self.strategy_id}",
            f"  Stage:        {self.stage}",
            f"  Decision:     {self.decision.value.upper()}",
            f"  Score:        {self.score:.0f}/100",
            f"  Confidence:   {self.confidence:.0%}",
            "",
            "  Gate Levels:",
        ]
        labels = {
            "data_integrity": "Data Integrity",
            "factor_validity": "Factor Validity",
            "portfolio_conversion": "Portfolio Conversion",
            "robustness": "Robustness",
            "cost_capacity": "Cost & Capacity",
        }
        for key, label in labels.items():
            status = getattr(self, key)
            icon = "[PASS]" if status == "PASS" else ("[FAIL]" if status == "FAIL" else "[SKIP]")
            lines.append(f"    {icon} {label}")
        lines.append("")
        if self.recommendation:
            lines.append(f"  {self.recommendation}")
        lines.append("=" * 60)
        return "\n".join(lines)
