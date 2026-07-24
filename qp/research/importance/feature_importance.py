"""Feature importance analysis — gain-based ranking, SHAP, and drift detection.

Implements rule.md §7.9.7 requirements:
  - Gain-based Feature Importance ranking
  - SHAP local interpretability (quarterly Top-10 review)
  - Feature importance version change comparison
  - Unexpected feature weight surge alerts

Usage:
    from qp.research.importance.feature_importance import (
        compute_shap_importance,
        compare_importance_versions,
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd


@dataclass
class ImportanceRecord:
    """Feature importance snapshot for a model version."""

    model_id: str
    features: dict[str, float]  # feature_name → importance score
    method: str = "gain"  # "gain" | "shap" | "permutation"
    top_n: int = 10
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "features": self.features,
            "method": self.method,
            "top_n": self.top_n,
            "created_at": self.created_at,
        }

    @property
    def top_features(self) -> list[tuple[str, float]]:
        """Return sorted list of (feature, importance) top_n pairs."""
        sorted_items = sorted(self.features.items(), key=lambda x: x[1], reverse=True)
        return sorted_items[: self.top_n]

    @property
    def top_feature_names(self) -> list[str]:
        return [f for f, _ in self.top_features]


@dataclass
class ImportanceDriftReport:
    """Report of feature importance changes between two versions."""

    prev_model_id: str
    curr_model_id: str
    prev_top5: list[str] = field(default_factory=list)
    curr_top5: list[str] = field(default_factory=list)
    overlap_count: int = 0
    new_entrants: list[str] = field(default_factory=list)
    departed: list[str] = field(default_factory=list)
    rank_shifts: dict[str, int] = field(default_factory=dict)
    has_drift: bool = False
    drift_severity: str = "none"  # "none" | "moderate" | "severe"
    surge_alerts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "prev_model_id": self.prev_model_id,
            "curr_model_id": self.curr_model_id,
            "prev_top5": self.prev_top5,
            "curr_top5": self.curr_top5,
            "overlap_count": self.overlap_count,
            "new_entrants": self.new_entrants,
            "departed": self.departed,
            "rank_shifts": self.rank_shifts,
            "has_drift": self.has_drift,
            "drift_severity": self.drift_severity,
            "surge_alerts": self.surge_alerts,
        }

    def summary(self) -> str:
        if not self.has_drift:
            return "Importance stable — no significant drift detected."
        return (
            f"Drift ({self.drift_severity}): {len(self.new_entrants)} new features "
            f"entered top 5, {len(self.departed)} departed. "
            f"Overlap: {self.overlap_count}/5"
        )


def compute_shap_importance(
    model: Any,
    X: pd.DataFrame,
    max_samples: int = 1000,
    top_n: int = 10,
) -> ImportanceRecord:
    """Compute SHAP-based feature importance for a trained model.

    Uses Tree SHAP for LightGBM models.  Falls back to gain-based
    importance if SHAP computation fails.

    This should be run quarterly on the Top 10 features per rule.md §7.9.7.

    Args:
        model: Trained model (LightGBMRankModel or lightgbm.Booster).
        X: Feature matrix sample for SHAP computation.
        max_samples: Maximum samples for SHAP (downsampled for speed).
        top_n: Number of top features to record.

    Returns:
        ImportanceRecord with SHAP-based feature importance.
    """
    features = dict.fromkeys(list(X.columns), 0.0)

    # Downsample if needed
    X_sample = X.sample(n=max_samples, random_state=42) if len(X) > max_samples else X

    try:
        import shap  # type: ignore[import-untyped]

        # Try to get the underlying booster
        booster = model._model if hasattr(model, "_model") else model

        if booster is None:
            raise ValueError("Model not fitted")

        explainer = shap.TreeExplainer(booster)
        shap_values = explainer.shap_values(X_sample)

        # Aggregate SHAP importance: mean(|shap|) per feature
        # Multi-class output → take first class
        shap_arr = np.abs(shap_values[0]) if isinstance(shap_values, list) else np.abs(shap_values)

        for i, col in enumerate(X.columns):
            if i < shap_arr.shape[1]:
                features[col] = round(float(np.mean(shap_arr[:, i])), 6)

        return ImportanceRecord(
            model_id=getattr(model, "name", "unknown"),
            features=features,
            method="shap",
            top_n=top_n,
        )

    except ImportError:
        # SHAP not installed — fall back to gain
        return compute_gain_importance(model, top_n)
    except Exception:
        # Any other SHAP error — fall back to gain
        return compute_gain_importance(model, top_n)


def compute_gain_importance(
    model: Any,
    top_n: int = 10,
) -> ImportanceRecord:
    """Compute gain-based feature importance from a LightGBM model.

    Args:
        model: Trained LightGBMRankModel (must have feature_importance property).
        top_n: Top-N features to record.

    Returns:
        ImportanceRecord with gain-based importance.
    """
    if hasattr(model, "feature_importance"):
        try:
            fi_df = model.feature_importance
            if fi_df.empty:
                return ImportanceRecord(
                    model_id="unknown",
                    features={},
                    method="gain",
                    top_n=top_n,
                )
            features = dict(zip(fi_df["feature"], fi_df["gain"], strict=True))
            return ImportanceRecord(
                model_id=getattr(model, "name", "unknown"),
                features=features,
                method="gain",
                top_n=top_n,
            )
        except Exception:
            pass

    return ImportanceRecord(
        model_id="unknown",
        features={},
        method="gain",
        top_n=top_n,
    )


def compare_importance_versions(
    prev: ImportanceRecord,
    curr: ImportanceRecord,
    top_n: int = 5,
    surge_threshold: float = 0.5,
) -> ImportanceDriftReport:
    """Compare two feature importance versions and detect drift.

    Rule.md §7.9.7: If top 5 features change by >50% (i.e., < 3 overlap),
    flag for human review.  If any individual feature's importance changes
    by >surge_threshold relative to the total, issue a surge alert.

    Args:
        prev: Previous importance record.
        curr: Current importance record.
        top_n: Number of top features to compare.
        surge_threshold: Relative change threshold for surge alerts.

    Returns:
        ImportanceDriftReport with drift analysis.
    """
    prev_sorted = sorted(prev.features.items(), key=lambda x: x[1], reverse=True)
    curr_sorted = sorted(curr.features.items(), key=lambda x: x[1], reverse=True)

    prev_top = [f for f, _ in prev_sorted[:top_n]]
    curr_top = [f for f, _ in curr_sorted[:top_n]]

    prev_set = set(prev_top)
    curr_set = set(curr_top)

    overlap = prev_set & curr_set
    new_entrants = list(curr_set - prev_set)
    departed = list(prev_set - curr_set)

    # Rank shift for features in both
    rank_shifts: dict[str, int] = {}
    for f in overlap:
        prev_rank = prev_top.index(f) + 1
        curr_rank = curr_top.index(f) + 1
        shift = curr_rank - prev_rank  # positive = dropped in rank
        if abs(shift) >= 2:  # Only record shifts of 2+ positions
            rank_shifts[f] = shift

    # Surge alerts: features whose importance relative to max changed significantly
    surge_alerts: list[str] = []
    prev_max = max(prev.features.values()) if prev.features else 1.0
    curr_max = max(curr.features.values()) if curr.features else 1.0

    for f in set(list(prev.features.keys()) + list(curr.features.keys())):
        prev_val = prev.features.get(f, 0.0)
        curr_val = curr.features.get(f, 0.0)
        prev_rel = prev_val / prev_max if prev_max > 0 else 0.0
        curr_rel = curr_val / curr_max if curr_max > 0 else 0.0
        change = abs(curr_rel - prev_rel)
        if change > surge_threshold and curr_val > 0:
            direction = "↑" if curr_rel > prev_rel else "↓"
            surge_alerts.append(f"{f}: {prev_rel:.3f}→{curr_rel:.3f} ({direction}{change:.1%})")

    # Determine drift severity
    overlap_count = len(overlap)
    if overlap_count >= 4:
        severity = "none"
        has_drift = False
    elif overlap_count >= 3:
        severity = "moderate"
        has_drift = True
    else:
        severity = "severe"
        has_drift = True

    return ImportanceDriftReport(
        prev_model_id=prev.model_id,
        curr_model_id=curr.model_id,
        prev_top5=prev_top,
        curr_top5=curr_top,
        overlap_count=overlap_count,
        new_entrants=new_entrants,
        departed=departed,
        rank_shifts=rank_shifts,
        has_drift=has_drift,
        drift_severity=severity,
        surge_alerts=surge_alerts,
    )
