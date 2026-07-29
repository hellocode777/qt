"""DecisionEngine — converts strategy signals into user-actionable trade recommendations.

This is the core of Layer 8. It takes raw strategy output (DataFrames with signals),
risk analysis (RiskReport), cost estimates (CostModel), and produces structured
TradeRecommendations with reasons, warnings, and cost breakdowns.

The output is designed for manual execution: the user reads the recommendations
and places orders themselves through their brokerage account.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

from qp.decision.models import DecisionReport, TradeRecommendation
from qp.portfolio.cost_model import CostBreakdown, CostModel

if TYPE_CHECKING:
    from qp.portfolio.risk_manager import RiskReport


class DecisionEngine:
    """Converts strategy signals → risk-filtered trade recommendations.

    Usage:
        engine = DecisionEngine()
        report = engine.generate(
            signals=aggregated_df,
            prices=daily_prices_df,
            risk_report=risk_report,
            total_capital=1_000_000,
        )
        print(engine.format_bilingual(report))
    """

    def __init__(
        self,
        stamp_tax_rate: float = 0.0005,
        commission_rate: float = 0.00025,
        slippage_bps: float = 10.0,
    ) -> None:
        self._cost_model = CostModel(
            stamp_tax_rate=stamp_tax_rate,
            commission_rate=commission_rate,
            slippage_bps=slippage_bps,
        )

    # ------------------------------------------------------------------
    # Main API
    # ------------------------------------------------------------------

    def generate(
        self,
        signals: pl.DataFrame,
        prices: pl.DataFrame,
        risk_report: RiskReport | None = None,
        current_positions: dict[str, float] | None = None,
        total_capital: float = 1_000_000,
        strategy_id: str = "default",
        market_regime: str = "",
    ) -> DecisionReport:
        """Generate trade recommendations from strategy signals.

        Args:
            signals: Strategy output with [symbol, aggregated_score, rank, action].
            prices: Daily price data with [symbol, close].
            risk_report: Risk analysis output (optional, for warnings and context).
            current_positions: symbol → current weight mapping (optional).
            total_capital: Total portfolio capital in CNY.
            strategy_id: Source strategy identifier.
            market_regime: Current market regime description.

        Returns:
            DecisionReport ready for display and audit logging.
        """
        import uuid

        current_positions = current_positions or {}
        recommendations: list[TradeRecommendation] = []

        if signals.is_empty():
            return DecisionReport(
                report_id=f"dr-{uuid.uuid4().hex[:8]}",
                strategy_id=strategy_id,
                total_capital=total_capital,
                risk_summary="无信号 / No signals generated",
                market_regime=market_regime,
                cost_summary="无 / None",
            )

        # Extract signal data
        symbols = signals["symbol"].to_list()
        ranks = (
            signals["rank"].to_list()
            if "rank" in signals.columns
            else list(range(1, len(symbols) + 1))
        )
        scores = (
            signals["aggregated_score"].to_list()
            if "aggregated_score" in signals.columns
            else [0.0] * len(symbols)
        )

        # Build price lookup
        price_lookup: dict[str, float] = {}
        if not prices.is_empty():
            for row in prices.iter_rows(named=True):
                price_lookup[str(row["symbol"])] = float(row.get("close", 0.0))

        # Build position weights from risk report or signals
        if risk_report and risk_report.position_weights:
            pos_weights = risk_report.position_weights
        else:
            n = max(len(symbols), 1)
            pos_weights = dict.fromkeys(symbols, 1.0 / n)

        n_stocks = len(symbols)
        per_stock_weight = 1.0 / max(n_stocks, 1)

        for i, sym in enumerate(symbols):
            price = price_lookup.get(sym, 10.0)
            target_wt = pos_weights.get(sym, per_stock_weight) * 100
            current_wt = (current_positions.get(sym, 0.0)) * 100

            # Calculate share quantity
            target_amount = total_capital * target_wt / 100
            quantity = max(int(target_amount / price // 100 * 100), 0)

            # Estimate costs
            trade_value = price * quantity
            cost: CostBreakdown | None = None
            if trade_value > 0:
                try:
                    cost = self._cost_model.estimate_trade(
                        symbol=sym,
                        trade_value=trade_value,
                        side="BUY",
                    )
                except Exception:
                    cost = None

            est_cost = cost.total_cost if cost else 0.0

            # Build reason
            rank = ranks[i] if i < len(ranks) else i + 1
            score = scores[i] if i < len(scores) else 0.0
            reason = f"多策略融合排名 #{rank} (score={score:.3f})"

            # Build confidence (higher rank = higher confidence)
            confidence = max(0.5, 1.0 - (rank - 1) / max(n_stocks * 2, 1))

            # Risk warnings
            warnings: list[str] = []
            if target_wt >= 7.5:
                warnings.append(f"单仓占比 {target_wt:.1f}% 接近 8% 上限")
            if quantity < 100:
                warnings.append(f"建议股数 {quantity} 不足1手(100股)")
            if est_cost / trade_value > 0.005 if trade_value > 0 else False:
                warnings.append(f"交易成本偏高: {est_cost / trade_value * 100:.2f}%")

            # Check if risk report flagged this symbol
            if risk_report and sym in risk_report.dropped_symbols:
                warnings.append("⚠ 风控标记: 该标的存在相关性/行业风险")

            recommendations.append(
                TradeRecommendation(
                    symbol=sym,
                    action="BUY",
                    target_weight_pct=target_wt,
                    current_weight_pct=current_wt,
                    quantity_shares=quantity,
                    estimated_price=price,
                    estimated_cost=est_cost,
                    reason=reason,
                    risk_warnings=warnings,
                    confidence=confidence,
                    strategy=strategy_id,
                )
            )

        # Build report summary fields
        risk_summary = self._build_risk_summary(risk_report, recommendations, n_stocks)
        cost_summary = self._build_cost_summary(recommendations)

        return DecisionReport(
            report_id=f"dr-{uuid.uuid4().hex[:8]}",
            strategy_id=strategy_id,
            total_capital=total_capital,
            recommendations=recommendations,
            risk_summary=risk_summary,
            market_regime=market_regime,
            cost_summary=cost_summary,
        )

    # ------------------------------------------------------------------
    # Output formatters
    # ------------------------------------------------------------------

    def format_bilingual(self, report: DecisionReport) -> str:
        """Format report as bilingual (Chinese + English) terminal output.

        Args:
            report: The decision report to format.

        Returns:
            Formatted string for terminal display.
        """
        lines: list[str] = []
        sep = "═" * 60
        sub = "─" * 52

        # Header
        lines.append(sep)
        lines.append("  QP 交易建议 / Trading Recommendations")
        lines.append(sep)
        lines.append(f"  生成时间 / Generated:  {report.generated_at[:19]}")
        lines.append(f"  报告编号 / Report ID:  {report.report_id}")
        lines.append(f"  策略来源 / Strategy:   {report.strategy_id}")
        lines.append(f"  资金规模 / Capital:    ¥{report.total_capital:,.0f}")
        if report.market_regime:
            lines.append(f"  市场状态 / Regime:     {report.market_regime}")
        lines.append("")

        if report.is_empty:
            lines.append("  ⚠ 无交易建议 / No recommendations generated.")
            lines.append(sep)
            return "\n".join(lines)

        # Buy recommendations
        lines.append(f"  {sub}")
        lines.append(f"  建议买入 / BUY ({report.n_buys} 只)")
        lines.append(f"  {sub}")
        lines.append("")

        for i, rec in enumerate(report.buys, 1):
            lines.append(self._format_one_recommendation(i, rec))

        # Sell recommendations (if any)
        if report.n_sells > 0:
            lines.append(f"  {sub}")
            lines.append(f"  建议卖出 / SELL ({report.n_sells} 只)")
            lines.append(f"  {sub}")
            lines.append("")
            for i, rec in enumerate(report.sells, 1):
                lines.append(self._format_one_recommendation(i, rec))

        # Risk summary
        lines.append(f"  {sub}")
        lines.append("  风险概述 / Risk Summary")
        lines.append(f"  {sub}")
        lines.append(f"  {report.risk_summary}")
        if report.has_warnings:
            all_warnings: set[str] = set()
            for rec in report.recommendations:
                all_warnings.update(rec.risk_warnings)
            for w in sorted(all_warnings):
                lines.append(f"    ⚠ {w}")
        lines.append("")

        # Cost summary
        lines.append(f"  {sub}")
        lines.append("  成本估算 / Cost Estimate")
        lines.append(f"  {sub}")
        lines.append(f"  {report.cost_summary}")
        lines.append("")

        # Disclaimer
        lines.append(f"  {sub}")
        lines.append("  免责声明 / Disclaimer")
        lines.append(f"  {sub}")
        for dl_line in report.disclaimer.strip().split("\n"):
            lines.append(f"  {dl_line}")
        lines.append("")
        lines.append(sep)

        return "\n".join(lines)

    def to_markdown(self, report: DecisionReport) -> str:
        """Format report as Markdown for audit trail / knowledge archive.

        Args:
            report: The decision report to format.

        Returns:
            Markdown string suitable for saving to a file.
        """
        lines: list[str] = [
            f"# QP Decision Report — {report.report_id}",
            "",
            f"**Generated**: {report.generated_at[:19]}",
            f"**Strategy**: {report.strategy_id}",
            f"**Capital**: ¥{report.total_capital:,.0f}",
        ]
        if report.market_regime:
            lines.append(f"**Regime**: {report.market_regime}")
        lines.append("")

        if report.is_empty:
            lines.append("*No recommendations generated.*")
            return "\n".join(lines)

        # Buy table
        if report.n_buys > 0:
            lines.extend(
                [
                    "## Buy Recommendations",
                    "",
                    "| # | Symbol | Weight | Shares | Price | Cost | Confidence | Reason |",
                    "|---|--------|--------|--------|-------|------|------------|--------|",
                ]
            )
            for i, rec in enumerate(report.buys, 1):
                warnings = " ⚠" if rec.risk_warnings else ""
                lines.append(
                    f"| {i} | {rec.symbol} | {rec.target_weight_pct:.1f}% | "
                    f"{rec.quantity_shares} | ¥{rec.estimated_price:.2f} | "
                    f"¥{rec.estimated_cost:.0f} | {rec.confidence:.0%}{warnings} | "
                    f"{rec.reason} |"
                )
            lines.append("")

        # Warnings
        if report.has_warnings:
            lines.append("## Risk Warnings")
            lines.append("")
            seen: set[str] = set()
            for rec in report.recommendations:
                for w in rec.risk_warnings:
                    if w not in seen:
                        lines.append(f"- ⚠ {rec.symbol}: {w}")
                        seen.add(w)
            lines.append("")

        # Summary
        lines.extend(
            [
                "## Summary",
                "",
                f"- **Risk**: {report.risk_summary}",
                f"- **Cost**: {report.cost_summary}",
                "",
                "---",
                "",
                report.disclaimer.replace("\n", "\n\n"),
            ]
        )

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal formatters
    # ------------------------------------------------------------------

    @staticmethod
    def _format_one_recommendation(index: int, rec: TradeRecommendation) -> str:
        """Format a single recommendation for bilingual terminal output."""
        lines: list[str] = []
        lines.append(
            f"  {index:2d}. {rec.symbol:<8s} "
            f"建议权重: {rec.target_weight_pct:.1f}% | "
            f"¥{rec.trade_value:,.0f} | "
            f"{rec.quantity_shares} 股"
        )
        lines.append(f"      理由: {rec.reason} | 置信度: {rec.confidence:.0%}")
        if rec.estimated_cost > 0:
            lines.append(
                f"      预估成本: ¥{rec.estimated_cost:.0f} "
                f"({rec.cost_pct:.2f}%) | "
                f"成交价: ¥{rec.estimated_price:.2f}"
            )
        for w in rec.risk_warnings:
            lines.append(f"      ⚠ {w}")
        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _build_risk_summary(
        risk_report: RiskReport | None,
        recommendations: list[TradeRecommendation],
        n_stocks: int,
    ) -> str:
        """Build a one-line risk summary."""
        if risk_report is None:
            return f"持仓数: {n_stocks} | 未执行风控检查"

        parts: list[str] = []
        if risk_report.passed:
            parts.append("风控通过 / Risk OK")
        else:
            parts.append(f"风控告警 / Risk Warning ({len(risk_report.violations)}项)")

        parts.append(f"持仓 {risk_report.candidates_out}/{risk_report.candidates_in}")

        # Sector concentration
        if risk_report.sector_exposure:
            max_sector = max(
                risk_report.sector_exposure,
                key=risk_report.sector_exposure.get,  # type: ignore[arg-type]
            )
            max_wt = risk_report.sector_exposure[max_sector]
            parts.append(f"最大行业: {max_sector} {max_wt:.0%}")

        return " | ".join(parts)

    @staticmethod
    def _build_cost_summary(
        recommendations: list[TradeRecommendation],
    ) -> str:
        """Build a one-line cost estimate summary."""
        total_cost = sum(r.estimated_cost for r in recommendations)
        total_value = sum(r.trade_value for r in recommendations)
        avg_pct = (total_cost / total_value * 100) if total_value > 0 else 0.0
        return (
            f"预估总成本: ¥{total_cost:,.0f} ({avg_pct:.2f}%) | "
            f"交易额: ¥{total_value:,.0f} | "
            f"含印花税+佣金+滑点"
        )
