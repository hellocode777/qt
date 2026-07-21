"""Circuit Breaker — halts the data pipeline when quality thresholds are breached.

Implements data_layer.md §1.3 core principle:
  "断路器机制（Circuit Breaker）：在数据进入核心存储前，设置严苛的
   质量闸门（Data Quality Gate），防止污染后续管道。"

Pattern:
  1. Validation checks produce CheckResults with severities.
  2. CircuitBreaker evaluates results against configured thresholds.
  3. If tripped → pipeline is HALTED; data does NOT enter Silver/Gold.
  4. Tripped state requires manual reset (or auto-reset on next clean batch).

The breaker is "fail-closed" — when in doubt, block the data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from loguru import logger

from qp.data.validation.result import CheckResult, Severity

# ------------------------------------------------------------------
# Breaker state machine
# ------------------------------------------------------------------


class BreakerState(StrEnum):
    """Circuit breaker lifecycle states."""

    CLOSED = "closed"         # Normal operation — data flows through
    OPEN = "open"             # Tripped — data is blocked
    HALF_OPEN = "half_open"   # Testing — one batch allowed, then re-evaluate


# ------------------------------------------------------------------
# Configuration
# ------------------------------------------------------------------


@dataclass
class BreakerConfig:
    """Configuration for the circuit breaker.

    Attributes:
        max_critical_failures: Max ERROR-severity failures before tripping.
        max_warnings: Max WARNING-severity failures before tripping.
        auto_reset_after_seconds: If > 0, auto-close after this many seconds
                                  of no failures.  0 = manual reset only.
        require_all_checks: If True, ALL registered checks must pass (even WARNING
                           severity blocks).
    """

    max_critical_failures: int = 0    # 0 = any ERROR failure trips the breaker
    max_warnings: int = 10            # More than this many warnings trips it
    auto_reset_after_seconds: float = 0.0  # 0 = manual reset
    require_all_checks: bool = False


# ------------------------------------------------------------------
# Circuit Breaker
# ------------------------------------------------------------------


@dataclass
class BreakerResult:
    """Outcome of evaluating the circuit breaker.

    Attributes:
        tripped: True if the breaker is now OPEN (pipeline halted).
        state: Current breaker state.
        reason: Human-readable reason for trip.
        blocked_checks: Which checks caused the trip.
    """

    tripped: bool
    state: BreakerState = BreakerState.CLOSED
    reason: str = ""
    blocked_checks: list[str] = field(default_factory=list)


class CircuitBreaker:
    """Data quality circuit breaker — fail-closed by default.

    Usage::

        breaker = CircuitBreaker(BreakerConfig(max_critical_failures=0))
        report = gate.validate(df)          # produces list[CheckResult]
        result = breaker.evaluate(report)   # → BreakerResult
        if result.tripped:
            raise DataQualityException(result.reason)
    """

    def __init__(self, config: BreakerConfig | None = None) -> None:
        self.config = config or BreakerConfig()
        self._state: BreakerState = BreakerState.CLOSED
        self._trip_count: int = 0
        self._last_trip_at: datetime | None = None
        self._trip_history: list[dict] = []

    # -- properties --

    @property
    def state(self) -> BreakerState:
        self._maybe_auto_reset()
        return self._state

    @property
    def is_open(self) -> bool:
        return self.state == BreakerState.OPEN

    # -- core logic --

    def evaluate(self, results: list[CheckResult]) -> BreakerResult:
        """Evaluate validation results and decide whether to trip.

        Args:
            results: List of CheckResult from ValidationGate or manual checks.

        Returns:
            BreakerResult indicating whether pipeline should be halted.
        """
        errors = [r for r in results if r.severity == Severity.ERROR and not r.passed]
        warnings = [r for r in results if r.severity == Severity.WARNING and not r.passed]

        # --- Determine if breaker should trip ---
        trip_reasons: list[str] = []

        if self.config.require_all_checks:
            all_failed = [r for r in results if not r.passed]
            if all_failed:
                trip_reasons.append(
                    f"require_all_checks=True: {len(all_failed)} check(s) failed"
                )

        if len(errors) > self.config.max_critical_failures:
            trip_reasons.append(
                f"{len(errors)} critical failures (max allowed: "
                f"{self.config.max_critical_failures})"
            )

        if len(warnings) > self.config.max_warnings:
            trip_reasons.append(
                f"{len(warnings)} warnings (max allowed: {self.config.max_warnings})"
            )

        if trip_reasons:
            return self._trip(errors + warnings, "; ".join(trip_reasons))

        # --- No trip — mark half-open as closed ---
        if self._state == BreakerState.HALF_OPEN:
            logger.info("断路器: HALF_OPEN → CLOSED (批次校验通过)")
            self._state = BreakerState.CLOSED

        return BreakerResult(tripped=False, state=self._state)

    def reset(self) -> None:
        """Manually reset the breaker to CLOSED state."""
        logger.info("断路器: 手动复位 → CLOSED")
        self._state = BreakerState.CLOSED
        self._trip_count = 0
        self._last_trip_at = None

    def test_half_open(self) -> None:
        """Set breaker to HALF_OPEN for testing after a trip."""
        self._state = BreakerState.HALF_OPEN
        logger.info("断路器: → HALF_OPEN (下一批次将决定是否关闭)")

    # -- internals --

    def _trip(self, failed_checks: list[CheckResult], reason: str) -> BreakerResult:
        """Trip the breaker to OPEN state."""
        self._state = BreakerState.OPEN
        self._trip_count += 1
        self._last_trip_at = datetime.now(tz=UTC)

        check_names = [c.check_name for c in failed_checks]
        trip_record = {
            "time": self._last_trip_at.isoformat(),
            "reason": reason,
            "checks": check_names,
            "trip_count": self._trip_count,
        }
        self._trip_history.append(trip_record)

        logger.error("断路器触发! 原因: {}", reason)
        logger.error("  失败检查: {}", ", ".join(check_names))
        logger.error("  累计触发次数: {}", self._trip_count)

        return BreakerResult(
            tripped=True,
            state=BreakerState.OPEN,
            reason=reason,
            blocked_checks=check_names,
        )

    def _maybe_auto_reset(self) -> None:
        """Auto-reset if enough time has passed since the last trip."""
        if self._state != BreakerState.OPEN:
            return
        if self.config.auto_reset_after_seconds <= 0:
            return
        if self._last_trip_at is None:
            return

        elapsed = (datetime.now(tz=UTC) - self._last_trip_at).total_seconds()
        if elapsed >= self.config.auto_reset_after_seconds:
            logger.info(
                "断路器: 自动复位 ({}s 后无新故障)",
                self.config.auto_reset_after_seconds,
            )
            self._state = BreakerState.CLOSED
