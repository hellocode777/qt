"""Market Regime Notes — structured market event ↔ strategy performance log.

Per docs/11_12.md Layer 12 §3: Record major market events aligned with
strategy performance. Serves as Ground Truth data for Layer 11's
MarketRegimeEngine calibration.

Each entry captures:
  - Market event description (what happened, when)
  - Regime classification at the time
  - Strategy performance during the event (IC, Sharpe, drawdown)
  - Key observations and lessons

Storage: Markdown files under data/knowledge/market_regime_notes/.

Usage:
    logger = RegimeNoteLogger()
    logger.record_event(
        title="2024.02 Micro-cap Liquidity Crisis",
        event_date="2024-02-05",
        regime="LIQUIDITY_CRUNCH",
        strategy_name="alpha_multi_factor_v2",
        ic_during_event=-0.03,
        max_drawdown_pct=12.5,
        observations="Small-cap factors collapsed, quality factor held.",
        tags=["liquidity-crisis", "micro-cap", "2024"],
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from qp.knowledge.archive import KnowledgeArchive, KnowledgeCategory, KnowledgeEntry

DEFAULT_REGIME_NOTES_DIR = "data/knowledge/market_regime_notes"

REGIME_NOTE_TEMPLATE = """## Market Event

**Date**: {event_date}
**Regime**: {regime}
**Severity**: {severity} (1-5)

## Strategy Impact

| Strategy | IC (during) | Max DD | Sharpe | Notes |
|----------|------------|--------|--------|-------|
{strategy_table}

## Regime Indicators

- **Limit Up/Down Ratio**: {limit_up_down_ratio}
- **Sector Rotation Speed**: {sector_rotation_speed}
- **VIX / Ann Vol**: {annualized_vol}
- **ADX**: {adx}

## Observations

{observations}

## Lessons for Layer 11

{lessons}

## Ground Truth Labels

<!-- For training/calibrating MarketRegimeEngine -->
- **Regime Label**: {regime_label}
- **Confidence**: {confidence}
- **Labeled By**: {labeled_by}
- **Label Date**: {label_date}
"""


@dataclass
class RegimeNote:
    """One market regime event note.

    Attributes:
        title: Event title (e.g., "2024.02 Micro-cap Crash").
        event_date: Date of the event (YYYY-MM-DD).
        regime: Regime classification (LIQUIDITY_CRUNCH, STYLE_REVERSAL, etc.).
        severity: 1-5 severity rating.
        strategy_impacts: Dict of strategy_name → impact metrics.
        indicators: Dict of regime indicator values.
        observations: Free-text observations.
        lessons: Lessons learned for Layer 11 improvement.
        tags: Searchable tags.
        created_at: ISO timestamp.
    """

    title: str = ""
    event_date: str = ""
    regime: str = "UNKNOWN"
    severity: int = 3
    strategy_impacts: dict[str, dict[str, float]] = field(default_factory=dict)
    indicators: dict[str, float] = field(default_factory=dict)
    observations: str = ""
    lessons: str = ""
    tags: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class RegimeNoteLogger:
    """Logger for market regime ↔ strategy performance notes.

    Creates structured Markdown entries under data/knowledge/market_regime_notes/.
    Builds the Ground Truth dataset for Layer 11 regime engine calibration.

    Usage:
        logger = RegimeNoteLogger()
        logger.record_event(
            title="2024.02 Micro-cap Liquidity Crisis",
            event_date="2024-02-05",
            regime="LIQUIDITY_CRUNCH",
            strategy_name="alpha_multi_factor_v2",
            ic_during_event=-0.03,
            max_drawdown_pct=12.5,
        )
        # Query regime history
        events = logger.query_by_regime("LIQUIDITY_CRUNCH")
    """

    def __init__(self, base_dir: str = DEFAULT_REGIME_NOTES_DIR) -> None:
        self._base = Path(base_dir)
        self._base.mkdir(parents=True, exist_ok=True)
        self._archive = KnowledgeArchive()

    # ------------------------------------------------------------------
    # Record API
    # ------------------------------------------------------------------

    def record_event(
        self,
        title: str,
        event_date: str = "",
        regime: str = "UNKNOWN",
        severity: int = 3,
        strategy_name: str = "",
        ic_during_event: float = 0.0,
        sharpe_during_event: float = 0.0,
        max_drawdown_pct: float = 0.0,
        limit_up_down_ratio: float | None = None,
        sector_rotation_speed: float | None = None,
        annualized_vol: float | None = None,
        adx: float | None = None,
        observations: str = "",
        lessons: str = "",
        regime_label: str = "",
        confidence: float = 0.0,
        labeled_by: str = "auto",
        tags: list[str] | None = None,
    ) -> KnowledgeEntry:
        """Record a market regime event with strategy performance alignment.

        Args:
            title: Event title.
            event_date: Date of event (YYYY-MM-DD).
            regime: Regime classification string.
            severity: 1-5 severity.
            strategy_name: Which strategy this impacts.
            ic_during_event: IC during the event period.
            sharpe_during_event: Sharpe during the event period.
            max_drawdown_pct: Max drawdown during event.
            limit_up_down_ratio: Limit-up/down ratio at event time.
            sector_rotation_speed: Sector rotation speed at event time.
            annualized_vol: Annualized vol at event time.
            adx: ADX at event time.
            observations: What was observed.
            lessons: What was learned.
            regime_label: Ground truth label for calibration.
            confidence: Label confidence 0-1.
            labeled_by: Who/what labeled this.
            tags: Searchable tags.

        Returns:
            The created KnowledgeEntry.
        """
        # Build strategy impact table row
        strategy_rows = ""
        if strategy_name:
            strategy_rows = (
                f"| {strategy_name} | {ic_during_event:.4f} | "
                f"{max_drawdown_pct:.1f}% | {sharpe_during_event:.2f} | "
                f" |"
            )

        # Build indicator strings
        lud_str = (
            f"{limit_up_down_ratio:.3f}" if limit_up_down_ratio is not None else "N/A"
        )
        rot_str = (
            f"{sector_rotation_speed:.3f}"
            if sector_rotation_speed is not None
            else "N/A"
        )
        vol_str = f"{annualized_vol:.1%}" if annualized_vol is not None else "N/A"
        adx_str = f"{adx:.1f}" if adx is not None else "N/A"

        content = REGIME_NOTE_TEMPLATE.format(
            event_date=event_date or "TBD",
            regime=regime,
            severity=str(severity),
            strategy_table=strategy_rows or "| (no strategy data) | — | — | — | |",
            limit_up_down_ratio=lud_str,
            sector_rotation_speed=rot_str,
            annualized_vol=vol_str,
            adx=adx_str,
            observations=observations or "(待补充 / TBD)",
            lessons=lessons or "(待补充 / TBD)",
            regime_label=regime_label or regime,
            confidence=f"{confidence:.0%}",
            labeled_by=labeled_by,
            label_date=datetime.now(UTC).strftime("%Y-%m-%d"),
        )

        return self._archive.create_entry(
            category=KnowledgeCategory.RESEARCH_DEBT,  # reuse existing infra
            title=title,
            content=content,
            tags=tags or [],
            metadata={
                "event_date": event_date,
                "regime": regime,
                "severity": str(severity),
            },
        )

    def record_from_regime_result(
        self,
        regime_result: Any,  # RegimeResult
        title: str = "",
        strategy_name: str = "",
        ic_during_event: float = 0.0,
        max_drawdown_pct: float = 0.0,
        observations: str = "",
    ) -> KnowledgeEntry:
        """Record from a RegimeResult dataclass.

        Convenience wrapper that extracts indicators from a RegimeResult.

        Args:
            regime_result: RegimeResult instance.
            title: Event title.
            strategy_name: Strategy name.
            ic_during_event: IC during event.
            max_drawdown_pct: Max DD during event.
            observations: Observations.

        Returns:
            KnowledgeEntry.
        """
        return self.record_event(
            title=title,
            event_date=datetime.now(UTC).strftime("%Y-%m-%d"),
            regime=regime_result.regime.value,
            severity=4 if getattr(regime_result, "is_crisis", False) else 2,
            strategy_name=strategy_name,
            ic_during_event=ic_during_event,
            max_drawdown_pct=max_drawdown_pct,
            limit_up_down_ratio=getattr(regime_result, "limit_up_down_ratio", None),
            sector_rotation_speed=getattr(regime_result, "sector_rotation_speed", None),
            annualized_vol=getattr(regime_result, "annualized_vol", None),
            adx=getattr(regime_result, "trend_strength", None),
            observations=observations,
            lessons="Auto-recorded from monitoring pipeline.",
            regime_label=regime_result.regime.value,
            confidence=getattr(regime_result, "confidence", 0.0),
            labeled_by="auto",
            tags=["auto-recorded", regime_result.regime.value.lower()],
        )

    # ------------------------------------------------------------------
    # Query API
    # ------------------------------------------------------------------

    def query_by_regime(self, regime: str, limit: int = 20) -> list[KnowledgeEntry]:
        """Find all notes for a specific regime type.

        Args:
            regime: Regime value (e.g., "LIQUIDITY_CRUNCH").
            limit: Max entries.

        Returns:
            Matching KnowledgeEntry list.
        """
        return self._archive.search(regime, limit=limit)

    def query_by_date_range(
        self,
        start_date: str,
        end_date: str,
        limit: int = 50,
    ) -> list[KnowledgeEntry]:
        """Find events within a date range.

        Args:
            start_date: Start date (YYYY-MM-DD).
            end_date: End date (YYYY-MM-DD).
            limit: Max entries.

        Returns:
            Matching KnowledgeEntry list.
        """
        all_entries = self._archive.list_entries(limit=limit * 2)
        results = []
        for entry in all_entries:
            event_date = entry.metadata.get("event_date", "")
            if start_date <= event_date <= end_date:
                results.append(entry)
        return results[:limit]

    def get_ground_truth_labels(
        self,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Extract Ground Truth labels for Layer 11 calibration.

        Returns:
            List of {regime, indicator_values, label_date} dicts.
        """
        all_entries = self._archive.list_entries(limit=limit * 2)
        labels = []
        for entry in all_entries:
            regime = entry.metadata.get("regime", "")
            event_date = entry.metadata.get("event_date", "")
            if regime and event_date:
                labels.append(
                    {
                        "regime": regime,
                        "event_date": event_date,
                        "title": entry.title,
                        "tags": entry.tags,
                    }
                )
        return labels[:limit]

    def stats(self) -> dict[str, Any]:
        """Summary statistics of regime notes."""
        all_entries = self._archive.list_entries(limit=1000)
        regime_counts: dict[str, int] = {}
        for entry in all_entries:
            regime = entry.metadata.get("regime", "UNKNOWN")
            regime_counts[regime] = regime_counts.get(regime, 0) + 1

        return {
            "n_events": len(all_entries),
            "regime_distribution": regime_counts,
            "auto_labeled": sum(
                1 for e in all_entries if e.metadata.get("labeled_by") == "auto"
            ),
        }
