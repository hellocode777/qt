"""CashManager — dynamic cash reserve with defense triggers.

Per docs/8_Capital_Allocation_Layer.md §第四部分 + 建议2:
  "现金不仅是剩余资金的归宿，更是平台风险态度的缓冲垫。"

Defense triggers:
  1. Candidate scarcity: N passed < scarcity_threshold →
     target equity = N × standard_position_weight, rest = cash
  2. Volatility defense: market vol > volatility_percentile →
     force defensive_cash ratio
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, cast

import pandas as pd

from qp.portfolio.cash.reserve_policy import ReservePolicy


@dataclass
class CashDecision:
    """Result of cash management evaluation.

    Attributes:
        final_cash_ratio: The cash reserve ratio to apply.
        equity_exposure: Resulting equity exposure (1 - cash_ratio).
        cash_mode: "normal" | "defensive" | "scarcity".
        triggers: List of trigger descriptions that fired.
        candidate_adjusted: True if cash was increased from policy min.
    """

    final_cash_ratio: float = 0.05
    equity_exposure: float = 0.95
    cash_mode: str = "normal"
    triggers: list[str] = field(default_factory=list)
    candidate_adjusted: bool = False

    @property
    def is_defensive(self) -> bool:
        return self.cash_mode in ("defensive", "scarcity")


class CashManager:
    """Dynamic cash reserve manager with defense triggers.

    Evaluates market conditions and Layer 7 output to decide the
    appropriate cash reserve level.

    Usage:
        policy = ReservePolicy()
        manager = CashManager(policy)
        decision = manager.evaluate(
            n_candidates=3,
            current_market_vol=0.35,
            vol_percentile=0.92,
            risk_report=risk_report,
        )
    """

    def __init__(self, policy: ReservePolicy | None = None) -> None:
        self._policy = policy or ReservePolicy()

    # ------------------------------------------------------------------
    # Main API
    # ------------------------------------------------------------------

    def evaluate(
        self,
        n_candidates: int,
        current_market_vol: float = 0.20,
        vol_percentile: float = 0.50,
        risk_report: dict[str, Any] | None = None,
        total_capital: float = 100_000,
    ) -> CashDecision:
        """Determine the appropriate cash reserve ratio.

        Args:
            n_candidates: Number of Layer 7 approved candidates.
            current_market_vol: Current estimated market volatility (annualized).
            vol_percentile: Current volatility's percentile rank (0.0–1.0) relative
                to historical distribution. 0.95 = top 5% most volatile days.
            risk_report: Layer 7 risk report (may contain violations, concentration).
            total_capital: Total portfolio capital (for logging/context only).

        Returns:
            CashDecision with final cash ratio and trigger information.
        """
        triggers: list[str] = []
        cash_mode = "normal"
        cash_ratio = self._policy.min_cash

        # ── Trigger 1: Candidate scarcity ──
        if n_candidates < self._policy.scarcity_threshold:
            cash_mode = "scarcity"
            # Target equity = N × standard_weight, rest = cash
            target_equity = n_candidates * self._policy.standard_position_weight
            # Clamp to not exceed max_equity_exposure
            target_equity = min(target_equity, self._policy.max_equity_exposure)
            cash_ratio = max(self._policy.defensive_cash, 1.0 - target_equity)
            triggers.append(
                f"候选不足: {n_candidates}/{self._policy.scarcity_threshold} 只, "
                f"目标仓位 {target_equity:.0%}"
            )

        # ── Trigger 2: Volatility defense ──
        if vol_percentile >= self._policy.volatility_percentile:
            if cash_mode == "normal":
                cash_mode = "defensive"
            # Raise cash to at least defensive_cash
            cash_ratio = max(cash_ratio, self._policy.defensive_cash)
            triggers.append(
                f"波动率防御: vol={current_market_vol:.1%}, "
                f"分位={vol_percentile:.0%} ≥ {self._policy.volatility_percentile:.0%}, "
                f"现金提升至 {cash_ratio:.0%}"
            )

        # ── Trigger 3: Risk report violations ──
        if risk_report:
            violations = risk_report.get("violations", [])
            if violations and len(violations) > 0:
                if cash_mode == "normal":
                    cash_mode = "defensive"
                cash_ratio = max(cash_ratio, self._policy.defensive_cash * 0.8)
                triggers.append(f"风控告警: {len(violations)} 项违规, 现金提升")

        # ── Clamp ──
        # 正常/防御模式: 现金上限受 max_cash 约束。
        # scarcity 模式: 候选不足时 target_equity = N × standard_weight 是明确的
        # 防御意图（如 3 只 × 8% = 24% 仓位 → 76% 现金）。此时若仍被 max_cash
        # (默认 50%) 截断，会把"该留 76% 现金"变成"只留 50%"，削弱防御效果。
        # 因此 scarcity 模式允许现金突破 max_cash，只受 100% 上限约束。
        if cash_mode == "scarcity":
            cash_ratio = max(self._policy.min_cash, min(1.0, cash_ratio))
        else:
            cash_ratio = max(self._policy.min_cash, min(self._policy.max_cash, cash_ratio))

        return CashDecision(
            final_cash_ratio=round(cash_ratio, 4),
            equity_exposure=round(1.0 - cash_ratio, 4),
            cash_mode=cash_mode,
            triggers=triggers,
            candidate_adjusted=(cash_ratio > self._policy.min_cash),
        )

    # ------------------------------------------------------------------
    # Apply to positions
    # ------------------------------------------------------------------

    def apply_to_positions(
        self,
        positions: pd.DataFrame,
        cash_decision: CashDecision,
        total_capital: float,
        weight_col: str = "target_weight",
        cap_col: str = "max_weight_limit",
    ) -> pd.DataFrame:
        """Scale position weights to match the cash decision.

        If the cash decision increased cash reserve beyond what the
        normalizer already accounted for, scale down equity weights.

        ⚠️ 缩放**不得突破单票上限**：若「各票 cap 之和」小于目标仓位
        （如 5 只 × 8% cap = 总权重 40%，而 cash manager 想要 95% 仓位），
        则以 cap 总额为上限，缺口留作现金。单票上限是硬约束，
        不能为了用满权益而放大 —— 反例：50% 敞口 × 5 只 × 16% cap，
        无保护时会被放大到 19%/只，等于单票 9.5% 总资产，突破 8% 风控线。

        Args:
            positions: Position DataFrame with [symbol, target_weight, target_capital].
            cash_decision: CashDecision from evaluate().
            total_capital: Total portfolio capital.
            weight_col: Name of the weight column.
            cap_col: Per-position cap column (optional).

        Returns:
            Adjusted positions DataFrame.
        """
        if positions.empty:
            return positions

        df = positions.copy()
        current_equity = df[weight_col].sum()
        target_equity = cash_decision.equity_exposure

        # 单票上限之和 = 不突破 cap 前提下可投入的最大权重总额
        if cap_col in df.columns and not bool(df[cap_col].isna().all()):
            cap_total = float(cast("float", df[cap_col].fillna(1.0).clip(lower=0.0).sum()))
            target_equity = min(target_equity, cap_total)

        if current_equity > 0 and abs(current_equity - target_equity) > 0.001:
            scale = target_equity / current_equity
            df[weight_col] = df[weight_col] * scale
            if "target_capital" in df.columns:
                df["target_capital"] = df[weight_col] * total_capital

        return df

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def policy(self) -> ReservePolicy:
        return self._policy
