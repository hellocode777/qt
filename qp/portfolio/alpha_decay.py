"""Alpha Decay Detector — detects when active positions lose their alpha signal.

Checks daily whether held positions still rank in today's top-N. A position
that has fallen out of the signal universe suggests the alpha has decayed
and should be considered for exit.

This integrates with the Exit Engine (P3.1) to produce RANK_DROP exit signals.

Usage:
    detector = AlphaDecayDetector(top_n=20)
    exits = detector.check(
        active_positions=[pos1, pos2, ...],
        today_signals={"600519", "000001", ...},  # Top-N symbols
    )
    # → list of RiskExitSignal with RANK_DROP reason
"""

from __future__ import annotations

from dataclasses import dataclass

from qp.portfolio.risk_exit import Priority, RiskExitSignal, TradeReason


@dataclass
class AlphaDecayConfig:
    """Configuration for alpha decay detection.

    Attributes:
        top_n: Number of top-ranked signals to consider.
        grace_days: Days a position can be out of top-N before signaling.
        min_rank_drop: Minimum rank position to trigger (e.g. 2x top_n).
    """

    top_n: int = 20
    grace_days: int = 3  # Allow brief ranking fluctuations
    min_rank_drop: int = 0  # 0 = any drop triggers


class AlphaDecayDetector:
    """Detects alpha decay by checking positions against today's top-N.

    Usage:
        detector = AlphaDecayDetector(top_n=20)
        exits = detector.check(
            active_positions=[pos1, pos2],
            today_signals={"600519", "000001"},
        )
    """

    def __init__(self, config: AlphaDecayConfig | None = None) -> None:
        self.config = config or AlphaDecayConfig()

    def check(
        self,
        active_positions: list,
        today_signals: set[str],
    ) -> list[RiskExitSignal]:
        """Check active positions against today's top-N signals.

        Args:
            active_positions: List of Position objects with .symbol attribute.
            today_signals: Set of symbols that are in today's top-N.

        Returns:
            RiskExitSignal list for positions no longer in top-N.
        """
        exits: list[RiskExitSignal] = []

        for pos in active_positions:
            if not pos.is_active:
                continue
            if pos.symbol not in today_signals:
                exits.append(
                    RiskExitSignal(
                        symbol=pos.symbol,
                        action="SELL",
                        priority=Priority.LOW,
                        reasons=[TradeReason.RANK_DROP],
                        detail=f"跌出 Top-{self.config.top_n} 排名",
                        execution_time="NEXT_OPEN",
                    )
                )

        return exits

    def check_with_rank(
        self,
        active_positions: list,
        signal_ranks: dict[str, int],  # symbol → rank
    ) -> list[RiskExitSignal]:
        """Check positions against ranked signals with position info.

        Args:
            active_positions: List of Position objects.
            signal_ranks: {symbol: rank} mapping (1 = best).

        Returns:
            RiskExitSignal list with detailed rank info.
        """
        exits: list[RiskExitSignal] = []

        for pos in active_positions:
            if not pos.is_active:
                continue

            rank = signal_ranks.get(pos.symbol)
            if rank is None or rank > self.config.top_n:
                detail_parts = []
                if rank is None:
                    detail_parts.append(f"跌出 Top-{self.config.top_n}")
                else:
                    detail_parts.append(f"排名 #{rank} (阈值 Top-{self.config.top_n})")
                detail_parts.append(f"持仓成本 ¥{pos.entry_price:.2f}")

                exits.append(
                    RiskExitSignal(
                        symbol=pos.symbol,
                        action="SELL",
                        priority=Priority.LOW,
                        reasons=[TradeReason.RANK_DROP],
                        detail="; ".join(detail_parts),
                        execution_time="NEXT_OPEN",
                    )
                )

        return exits


# ==================================================================
# Convenience: compute today's signal set from pipeline output
# ==================================================================


def top_n_symbols(signals_df, top_n: int = 20) -> set[str]:
    """Extract top-N symbols from a signals DataFrame.

    Args:
        signals_df: Polars DataFrame with 'symbol' and optionally 'rank' column.
        top_n: Number of top symbols to return.

    Returns:
        Set of top-N symbol strings.
    """
    if signals_df is None or signals_df.is_empty():
        return set()

    if "rank" in signals_df.columns:
        sorted_df = signals_df.sort("rank").head(top_n)
    elif "aggregated_score" in signals_df.columns:
        sorted_df = signals_df.sort("aggregated_score", descending=True).head(top_n)
    elif "raw_score" in signals_df.columns:
        sorted_df = signals_df.sort("raw_score", descending=True).head(top_n)
    else:
        sorted_df = signals_df.head(top_n)

    return {str(s) for s in sorted_df["symbol"].to_list()}
