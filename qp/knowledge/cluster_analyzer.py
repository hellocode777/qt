"""Failure Cluster Analyzer — pattern mining + blacklist rule generation.

Per docs/11_12.md L12-1.6 + C2-C4 closed-loop feedback:
  1. Mine failure_archive for common failure patterns
  2. Generate blacklist rules → feed back to Layer 2 (Data)
  3. Suggest feature improvements → feed back to Layer 4 (Features)
  4. Recommend strategy parameter adjustments → feed back to Layer 8 (Strategy)

Algorithm: Simple threshold-based clustering on factor feature snapshots.
For production, this can be upgraded to DBSCAN or KMeans via scikit-learn.

Usage:
    analyzer = FailureClusterAnalyzer()
    # Generate blacklist rules from stop-loss patterns
    rules = analyzer.generate_blacklist_rules(min_records=10)
    # → [BlacklistRule("PE_TTM > 100", "High PE stocks frequently hit stop-loss")]
    #
    # Get feature engineering suggestions
    suggestions = analyzer.suggest_features()
    # → [FeatureSuggestion("Liquidity_Risk", "Derived from Volume_Expansion + MaxDD")]
    #
    # Get strategy parameter adjustments
    adjustments = analyzer.suggest_strategy_adjustments()
    # → [StrategyAdjustment("max_positions", "Reduce from 20→15 in LIQUIDITY_CRUNCH")]
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl

from qp.knowledge.failure_archive_logger import FailureArchiveLogger, FailureType
from qp.shared.paths import BLACKLIST_RULES, KNOWLEDGE_DIR

DEFAULT_RULES_DIR = KNOWLEDGE_DIR


@dataclass
class BlacklistRule:
    """A rule to exclude stocks from the investment universe.

    Generated from failure pattern clustering analysis.

    Attributes:
        condition: Rule condition (e.g., "PE_TTM > 100 AND Volume_Expansion > 2.0").
        reason: Why this rule exists.
        source_failures: How many failures support this rule.
        confidence: 0-1 confidence score.
        layer: Which layer should apply this (data / feature / strategy).
        created_at: When generated.
        status: proposed / active / retired.
    """

    condition: str = ""
    reason: str = ""
    source_failures: int = 0
    confidence: float = 0.0
    layer: str = "data"  # data / feature / strategy
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    status: str = "proposed"  # proposed / active / retired

    def to_dict(self) -> dict[str, Any]:
        return {
            "condition": self.condition,
            "reason": self.reason,
            "source_failures": self.source_failures,
            "confidence": self.confidence,
            "layer": self.layer,
            "created_at": self.created_at,
            "status": self.status,
        }


@dataclass
class FeatureSuggestion:
    """A feature engineering suggestion from failure pattern analysis.

    Attributes:
        feature_name: Proposed feature name.
        derivation: How to derive it from existing features.
        rationale: Why this might help.
        priority: 1-5 priority.
    """

    feature_name: str = ""
    derivation: str = ""
    rationale: str = ""
    priority: int = 3


@dataclass
class StrategyAdjustment:
    """A strategy parameter adjustment suggestion.

    Attributes:
        parameter: Parameter name to adjust.
        suggestion: What to change it to.
        reason: Why.
        priority: 1-5.
    """

    parameter: str = ""
    suggestion: str = ""
    reason: str = ""
    priority: int = 3


class FailureClusterAnalyzer:
    """Mines failure_archive data for patterns and generates feedback rules.

    Implements the closed-loop feedback from docs/11_12.md:
      Layer 12 (Knowledge) → Layer 2 (Data/Blacklist)
      Layer 12 (Knowledge) → Layer 4 (Feature Engineering)
      Layer 12 (Knowledge) → Layer 8 (Strategy Iteration)

    Usage:
        analyzer = FailureClusterAnalyzer()
        rules = analyzer.generate_blacklist_rules(min_records=10)
        for rule in rules:
            print(f"BLACKLIST: {rule.condition} — {rule.reason}")
    """

    # Thresholds for pattern detection
    _HIGH_PE = 100.0
    _HIGH_LEVERAGE = 2.0  # D/E ratio
    _LOW_ROE = 0.02
    _HIGH_VOLATILITY = 0.04
    _EXTREME_MOMENTUM = 0.30  # 30% monthly

    def __init__(self, base_dir: str | Path = DEFAULT_RULES_DIR) -> None:
        self._base = Path(base_dir)
        self._archive = FailureArchiveLogger(base_dir=str(self._base))
        self._rules_file = self._base / "blacklist_rules.json"

    # ------------------------------------------------------------------
    # Blacklist Rule Generation (C2: Knowledge → Layer 2)
    # ------------------------------------------------------------------

    def generate_blacklist_rules(
        self,
        min_records: int = 10,
        days: int = 365,
    ) -> list[BlacklistRule]:
        """Generate blacklist rules from stop-loss failure patterns.

        Analyzes feature snapshots at buy time for stocks that later
        hit stop-loss. Finds common threshold exceedances and generates
        exclusion rules.

        Args:
            min_records: Minimum failure count for a rule.
            days: Lookback window.

        Returns:
            List of BlacklistRule sorted by confidence.
        """
        patterns = self._archive.get_feature_patterns(
            failure_type=FailureType.STOP_LOSS,
            min_records=min_records,
            days=days,
        )

        if not patterns:
            return []

        rules: list[BlacklistRule] = []

        # Rule: High PE stocks → frequent stop-loss
        if "PE_TTM" in patterns:
            pe_mean = patterns["PE_TTM"]["mean"]
            pe_count = int(patterns["PE_TTM"]["count"])
            if pe_mean > self._HIGH_PE and pe_count >= min_records:
                rules.append(
                    BlacklistRule(
                        condition=f"PE_TTM > {self._HIGH_PE:.0f}",
                        reason=f"Stocks with PE > {self._HIGH_PE:.0f} account for "
                        f"{pe_count} stop-loss events (mean PE={pe_mean:.1f})",
                        source_failures=pe_count,
                        confidence=min(pe_count / (pe_count + 5), 0.95),
                        layer="data",
                    )
                )

        # Rule: High volatility stocks
        vol_features = ["Volatility_60D", "Volatility_20D"]
        for vf in vol_features:
            if vf in patterns:
                vol_mean = patterns[vf]["mean"]
                vol_count = int(patterns[vf]["count"])
                if vol_mean > self._HIGH_VOLATILITY and vol_count >= min_records:
                    rules.append(
                        BlacklistRule(
                            condition=f"{vf} > {self._HIGH_VOLATILITY:.3f}",
                            reason=f"High-vol stocks: mean {vf}={vol_mean:.4f} "
                            f"across {vol_count} stop-loss events",
                            source_failures=vol_count,
                            confidence=min(vol_count / (vol_count + 5), 0.95),
                            layer="data",
                        )
                    )
                    break  # One vol rule is enough

        # Rule: Extreme momentum (gambling stocks)
        momentum_features = ["Momentum_1M", "Momentum_3M", "Momentum_6M"]
        for mf in momentum_features:
            if mf in patterns:
                mom_mean = abs(patterns[mf]["mean"])
                mom_count = int(patterns[mf]["count"])
                if mom_mean > self._EXTREME_MOMENTUM and mom_count >= min_records:
                    rules.append(
                        BlacklistRule(
                            condition=f"ABS({mf}) > {self._EXTREME_MOMENTUM:.0%}",
                            reason=f"Extreme momentum stocks: mean |{mf}|={mom_mean:.1%} "
                            f"across {mom_count} failures",
                            source_failures=mom_count,
                            confidence=min(mom_count / (mom_count + 5), 0.95),
                            layer="data",
                        )
                    )
                    break

        # Rule: Low ROE (junk stocks)
        if "ROE" in patterns:
            roe_mean = patterns["ROE"]["mean"]
            roe_count = int(patterns["ROE"]["count"])
            if roe_mean < self._LOW_ROE and roe_count >= min_records:
                rules.append(
                    BlacklistRule(
                        condition=f"ROE < {self._LOW_ROE:.2f}",
                        reason=f"Low-quality stocks: mean ROE={roe_mean:.3f} "
                        f"across {roe_count} stop-loss events",
                        source_failures=roe_count,
                        confidence=min(roe_count / (roe_count + 5), 0.95),
                        layer="data",
                    )
                )

        return sorted(rules, key=lambda r: r.confidence, reverse=True)

    def save_rules(self, rules: list[BlacklistRule]) -> None:
        """Persist blacklist rules to JSON for Layer 2 consumption."""
        self._base.mkdir(parents=True, exist_ok=True)
        data = {
            "generated_at": datetime.now(UTC).isoformat(),
            "n_rules": len(rules),
            "rules": [r.to_dict() for r in rules],
        }
        self._rules_file.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def load_rules(self) -> list[BlacklistRule]:
        """Load previously generated blacklist rules."""
        if not self._rules_file.exists():
            return []
        try:
            data = json.loads(self._rules_file.read_text(encoding="utf-8"))
            return [
                BlacklistRule(
                    condition=r.get("condition", ""),
                    reason=r.get("reason", ""),
                    source_failures=r.get("source_failures", 0),
                    confidence=r.get("confidence", 0.0),
                    layer=r.get("layer", "data"),
                    created_at=r.get("created_at", ""),
                    status=r.get("status", "proposed"),
                )
                for r in data.get("rules", [])
            ]
        except (json.JSONDecodeError, KeyError):
            return []

    # ------------------------------------------------------------------
    # Feature Suggestions (C3: Knowledge → Layer 4)
    # ------------------------------------------------------------------

    def suggest_features(
        self,
        min_records: int = 10,
        days: int = 365,
    ) -> list[FeatureSuggestion]:
        """Suggest new features based on failure pattern analysis.

        Identifies factor combinations where failures cluster and
        proposes derived features that might capture the risk.

        Returns:
            List of FeatureSuggestion sorted by priority.
        """
        patterns = self._archive.get_feature_patterns(
            failure_type=FailureType.STOP_LOSS,
            min_records=min_records,
            days=days,
        )

        if not patterns:
            return []

        suggestions: list[FeatureSuggestion] = []

        # If both Volume_Expansion and Volatility are elevated → Liquidity_Risk factor
        if "Volume_Expansion_20_120" in patterns and "Volatility_60D" in patterns:
            suggestions.append(
                FeatureSuggestion(
                    feature_name="Liquidity_Risk",
                    derivation="Volume_Expansion_20_120 * Volatility_60D",
                    rationale="Failures cluster on high-vol + expanding volume: "
                    "potential distribution signal. Combined factor may "
                    "identify stocks being distributed by smart money.",
                    priority=4,
                )
            )

        # If Momentum and PE are both elevated → Bubble_Risk factor
        momentum_keys = [k for k in patterns if k.startswith("Momentum")]
        if momentum_keys and "PE_TTM" in patterns:
            suggestions.append(
                FeatureSuggestion(
                    feature_name="Bubble_Risk",
                    derivation="normalize(Momentum_1M) * normalize(PE_TTM)",
                    rationale="Stocks with both high momentum and high PE "
                    "may be in bubble territory. Combined signal for "
                    "early exit before reversal.",
                    priority=3,
                )
            )

        # If MaxDD is elevated → Tail_Risk factor
        if "MaxDD_60D" in patterns:
            suggestions.append(
                FeatureSuggestion(
                    feature_name="Tail_Risk",
                    derivation="MaxDD_60D / Volatility_60D",
                    rationale="High MaxDD relative to vol suggests "
                    "asymmetric downside risk not captured by vol alone.",
                    priority=3,
                )
            )

        return sorted(suggestions, key=lambda s: s.priority, reverse=True)

    # ------------------------------------------------------------------
    # Strategy Adjustments (C4: Knowledge → Layer 8)
    # ------------------------------------------------------------------

    def suggest_strategy_adjustments(
        self,
        days: int = 365,
    ) -> list[StrategyAdjustment]:
        """Suggest strategy parameter adjustments from failure patterns.

        Analyzes failure distribution across regimes and proposes
        parameter changes.

        Returns:
            List of StrategyAdjustment sorted by priority.
        """
        df = self._archive.load_history(days=days)
        if df.is_empty():
            return []

        adjustments: list[StrategyAdjustment] = []

        # Count failures by regime
        regime_counts: dict[str, int] = {}
        for row in df.iter_rows(named=True):
            regime = row.get("market_regime", "UNKNOWN")
            regime_counts[regime] = regime_counts.get(regime, 0) + 1

        # If many failures in LIQUIDITY_CRUNCH → reduce max_positions
        if regime_counts.get("LIQUIDITY_CRUNCH", 0) >= 3:
            adjustments.append(
                StrategyAdjustment(
                    parameter="max_positions",
                    suggestion="Reduce from 20→15 when regime == LIQUIDITY_CRUNCH",
                    reason=f"{regime_counts['LIQUIDITY_CRUNCH']} failures in "
                    "LIQUIDITY_CRUNCH regime. Smaller portfolio reduces "
                    "exposure to illiquid stocks.",
                    priority=4,
                )
            )

        # If failures in STYLE_REVERSAL → increase rebalance frequency
        if regime_counts.get("STYLE_REVERSAL", 0) >= 3:
            adjustments.append(
                StrategyAdjustment(
                    parameter="rebalance_freq",
                    suggestion="Increase from 20→10 when regime == STYLE_REVERSAL",
                    reason=f"{regime_counts['STYLE_REVERSAL']} failures in "
                    "STYLE_REVERSAL. Faster rebalance captures shifting "
                    "factor premiums.",
                    priority=3,
                )
            )

        # General: if average loss > 15% → tighten sell_buffer
        loss_data = df.filter(pl.col("loss_pct") != 0.0)
        if not loss_data.is_empty():
            avg_loss = abs(float(loss_data["loss_pct"].mean()))  # type: ignore[arg-type]
            if avg_loss > 0.15:
                adjustments.append(
                    StrategyAdjustment(
                        parameter="sell_buffer_multiplier",
                        suggestion="Reduce from 2→1.5 to exit faster",
                        reason=f"Average stop-loss = {avg_loss:.0%}. "
                        "Tighter buffer exits positions before deeper losses.",
                        priority=5,
                    )
                )

        return sorted(adjustments, key=lambda a: a.priority, reverse=True)

    # ------------------------------------------------------------------
    # Aggregated Analysis
    # ------------------------------------------------------------------

    def analyze(self, days: int = 365) -> dict[str, Any]:
        """Run full cluster analysis and return aggregated results.

        One-stop method for the closed-loop feedback:
          rules → Layer 2
          features → Layer 4
          adjustments → Layer 8

        Returns:
            Dict with rules, feature_suggestions, strategy_adjustments, stats.
        """
        rules = self.generate_blacklist_rules(days=days)
        features = self.suggest_features(days=days)
        adjustments = self.suggest_strategy_adjustments(days=days)

        # Save rules for Layer 2 consumption
        if rules:
            self.save_rules(rules)

        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "n_rules": len(rules),
            "rules": [r.to_dict() for r in rules],
            "n_feature_suggestions": len(features),
            "feature_suggestions": [
                {
                    "feature_name": f.feature_name,
                    "derivation": f.derivation,
                    "rationale": f.rationale,
                    "priority": f.priority,
                }
                for f in features
            ],
            "n_strategy_adjustments": len(adjustments),
            "strategy_adjustments": [
                {
                    "parameter": a.parameter,
                    "suggestion": a.suggestion,
                    "reason": a.reason,
                    "priority": a.priority,
                }
                for a in adjustments
            ],
            "feed_consumers": {
                "layer_2_data": BLACKLIST_RULES,
                "layer_4_features": "Manual review of feature_suggestions above",
                "layer_8_strategy": "Manual review of strategy_adjustments above",
            },
        }

    def stats(self) -> dict[str, Any]:
        """Quick stats without running full analysis."""
        return {
            "n_failures": self._archive.stats().get("n_failures", 0),
            "n_existing_rules": len(self.load_rules()),
        }
