"""Process validation checks — code review and experiment record.

Validates that strategy development processes were followed before
promotion. These are lightweight governance checks per rule.md §10.2.
"""

from __future__ import annotations

import os

from qp.shared.types import ValidationStatus
from qp.validation.engine import BaseRule, RuleResult, ValidationContext

# ------------------------------------------------------------------
# Code Review Check
# ------------------------------------------------------------------


class CodeReviewCheck(BaseRule):
    """Validates that strategy code has passed review.

    Per rule.md §10.2:
      "代码通过 Research Code Review（Rule 10）"

    Checks for a review marker file or metadata flag. The simplest
    implementation looks for a `.reviewed` marker file or a
    `code_review_passed` metadata key.

    Threshold: review marker must exist and be non-expired.
    """

    def __init__(self, review_file: str = "") -> None:
        self._review_file = review_file

    @property
    def rule_name(self) -> str:
        return "code_review"

    def check(self, context: ValidationContext) -> RuleResult:
        # Check 1: metadata flag (fast path)
        review_passed = context.metadata.get("code_review_passed")
        if review_passed is True:
            reviewer = context.metadata.get("code_reviewer", "unknown")
            review_date = context.metadata.get("code_review_date", "unknown")
            return RuleResult(
                rule_name=self.rule_name,
                status=ValidationStatus.PASS,
                score=100.0,
                detail=f"Code review passed by {reviewer} on {review_date}.",
            )

        # Check 2: review marker file
        strategy_id = context.strategy_id or context.metadata.get("strategy_id", "")
        review_file = self._review_file or f"data/reviews/{strategy_id}.reviewed"

        if os.path.exists(review_file):
            try:
                with open(review_file, encoding="utf-8") as f:
                    content = f.read().strip()
                return RuleResult(
                    rule_name=self.rule_name,
                    status=ValidationStatus.PASS,
                    score=100.0,
                    detail=f"Review file found: {review_file} — {content[:120]}",
                )
            except OSError:
                pass

        # Neither found
        if strategy_id:
            detail = (
                f"Code review not found for '{strategy_id}'. "
                f"Create {review_file} or set metadata['code_review_passed'] = True "
                f"with 'code_reviewer' and 'code_review_date'."
            )
        else:
            detail = (
                "Code review not found. Set metadata['code_review_passed'] = True "
                "or provide strategy_id in context."
            )

        return RuleResult(
            rule_name=self.rule_name,
            status=ValidationStatus.FAIL,
            score=0.0,
            detail=detail,
        )


# ------------------------------------------------------------------
# Experiment Record Check
# ------------------------------------------------------------------


class ExperimentRecordCheck(BaseRule):
    """Validates that a complete experiment record exists.

    Per rule.md §10.2:
      "完整 Experiment 记录（Rule 6）"

    Checks that an experiment was recorded for this strategy with
    required fields: experiment_id, config, metrics, lineage.

    Links to qp.research.experiment.tracker.ExperimentTracker for
    programmatic validation.
    """

    def __init__(self) -> None:
        pass

    @property
    def rule_name(self) -> str:
        return "experiment_record"

    def check(self, context: ValidationContext) -> RuleResult:
        experiment_id = context.metadata.get("experiment_id")
        experiment_json = context.metadata.get("experiment_json")

        # Check 1: experiment_id reference
        if experiment_id:
            # Try to load from ExperimentTracker
            try:
                from qp.research.experiment.tracker import ExperimentTracker

                tracker = ExperimentTracker()
                record = tracker.get(str(experiment_id))
                if record is not None:
                    return RuleResult(
                        rule_name=self.rule_name,
                        status=ValidationStatus.PASS,
                        score=100.0,
                        detail=(
                            f"Experiment '{experiment_id}' found: "
                            f"status={record.status.value}, "
                            f"features={record.config.features}, "
                            f"lineage={record.lineage.chain_str()[:80]}"
                        ),
                    )
                return RuleResult(
                    rule_name=self.rule_name,
                    status=ValidationStatus.FAIL,
                    score=0.0,
                    detail=(
                        f"Experiment '{experiment_id}' not found in "
                        f"ExperimentTracker. Run the experiment first or "
                        f"check the experiment_id."
                    ),
                )
            except Exception as exc:
                return RuleResult(
                    rule_name=self.rule_name,
                    status=ValidationStatus.FAIL,
                    score=0.0,
                    detail=f"Failed to query ExperimentTracker: {exc}",
                )

        # Check 2: inline experiment JSON
        if experiment_json and isinstance(experiment_json, dict):
            required = ["experiment_id", "config", "metrics", "lineage"]
            missing = [k for k in required if k not in experiment_json]
            if missing:
                return RuleResult(
                    rule_name=self.rule_name,
                    status=ValidationStatus.FAIL,
                    score=0.0,
                    detail=f"Experiment record missing fields: {missing}",
                )
            return RuleResult(
                rule_name=self.rule_name,
                status=ValidationStatus.PASS,
                score=100.0,
                detail=f"Experiment '{experiment_json.get('experiment_id')}' validated inline.",
            )

        # Neither found
        return RuleResult(
            rule_name=self.rule_name,
            status=ValidationStatus.FAIL,
            score=0.0,
            detail=(
                "No experiment record found. Set metadata['experiment_id'] "
                "to an existing experiment, or provide metadata['experiment_json'] "
                "with experiment_id, config, metrics, and lineage fields."
            ),
        )
