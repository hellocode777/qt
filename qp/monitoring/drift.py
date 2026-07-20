"""Drift Detection — monitors distribution shifts in features and predictions.

Covers:
  - PSI (Population Stability Index): feature distribution drift
  - KS (Kolmogorov-Smirnov): prediction distribution drift
  - Wasserstein distance: general distribution distance

Rule §10.3: PSI ≥ 0.25 → significant drift → pause strategy.

Usage:
    monitor = DriftMonitor()
    psi = monitor.compute_psi(reference_features, current_features)
    drift_report = monitor.check_drift(reference, current)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC
from enum import StrEnum
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import pandas as pd


class DriftSeverity(StrEnum):
    """Drift severity levels."""
    NONE = "none"  # PSI < 0.10
    MILD = "mild"  # 0.10 ≤ PSI < 0.25
    SIGNIFICANT = "significant"  # PSI ≥ 0.25 (threshold)


@dataclass
class DriftResult:
    """Result of a drift check on a single feature.

    Attributes:
        feature_name: Name of the feature checked.
        psi: Population Stability Index value.
        severity: Drift severity level.
        reference_mean: Mean of reference distribution.
        current_mean: Mean of current distribution.
        mean_shift_pct: Percentage change in mean.
    """

    feature_name: str
    psi: float = 0.0
    severity: DriftSeverity = DriftSeverity.NONE
    reference_mean: float = 0.0
    current_mean: float = 0.0
    mean_shift_pct: float = 0.0


@dataclass
class DriftReport:
    """Aggregate drift report across all monitored features.

    Attributes:
        timestamp: When the check was performed.
        results: Per-feature drift results.
        any_significant: True if any feature has significant drift.
        summary: One-line summary string.
    """

    timestamp: str = ""
    results: list[DriftResult] = field(default_factory=list)
    any_significant: bool = False
    summary: str = ""


class DriftMonitor:
    """Monitors feature and prediction distribution drift.

    Usage:
        monitor = DriftMonitor(psi_threshold=0.25)
        # Individual feature
        psi = monitor.compute_psi(train_feat, prod_feat)
        # Batch across features
        report = monitor.check_features(reference_df, current_df)
        # Prediction drift (KS test)
        ks_result = monitor.check_prediction_drift(ref_preds, cur_preds)
    """

    def __init__(
        self,
        psi_threshold: float = 0.25,
        psi_mild_threshold: float = 0.10,
        n_bins: int = 10,
    ) -> None:
        self._psi_threshold = psi_threshold
        self._psi_mild = psi_mild_threshold
        self._n_bins = n_bins

    # ------------------------------------------------------------------
    # PSI computation (same core logic as kill_switch.PSITrigger)
    # ------------------------------------------------------------------

    @staticmethod
    def compute_psi(
        expected: np.ndarray,
        actual: np.ndarray,
        bins: int = 10,
        epsilon: float = 1e-6,
    ) -> float:
        """Compute Population Stability Index.

        PSI = Σ[(actual% − expected%) × ln(actual% / expected%)]

        Args:
            expected: Reference (training) distribution values.
            actual: Current (production) distribution values.
            bins: Number of bins for discretization.
            epsilon: Small value to avoid log(0).

        Returns:
            PSI value (0 = identical, > 0.25 = significant drift).
        """
        expected_arr = np.asarray(expected).flatten()
        actual_arr = np.asarray(actual).flatten()

        # Remove NaN/Inf
        expected_arr = expected_arr[np.isfinite(expected_arr)]
        actual_arr = actual_arr[np.isfinite(actual_arr)]

        if len(expected_arr) < 2 or len(actual_arr) < 2:
            return 0.0

        # Combine to get bin edges
        combined = np.concatenate([expected_arr, actual_arr])
        bin_edges = np.percentile(combined, np.linspace(0, 100, bins + 1))
        bin_edges = np.unique(bin_edges)

        if len(bin_edges) < 2:
            return 0.0

        # Count per bin
        exp_counts, _ = np.histogram(expected_arr, bins=bin_edges)
        act_counts, _ = np.histogram(actual_arr, bins=bin_edges)

        # Normalize
        exp_pct = exp_counts / len(expected_arr)
        act_pct = act_counts / len(actual_arr)

        # PSI formula
        psi = 0.0
        for e, a in zip(exp_pct, act_pct, strict=True):
            e = max(e, epsilon)
            a = max(a, epsilon)
            psi += (a - e) * np.log(a / e)

        return float(psi)

    # ------------------------------------------------------------------
    # Kolmogorov-Smirnov test for prediction drift
    # ------------------------------------------------------------------

    @staticmethod
    def compute_ks(
        expected: np.ndarray,
        actual: np.ndarray,
    ) -> tuple[float, float]:
        """Compute two-sample KS statistic and approximate p-value.

        For prediction distribution drift detection. KS > 0.15
        suggests meaningful prediction shift.

        Args:
            expected: Reference (training) predictions.
            actual: Current (production) predictions.

        Returns:
            (ks_statistic, approximate_p_value).
        """
        from scipy.stats import ks_2samp  # type: ignore[import-untyped]

        expected_arr = np.asarray(expected).flatten()
        actual_arr = np.asarray(actual).flatten()

        expected_arr = expected_arr[np.isfinite(expected_arr)]
        actual_arr = actual_arr[np.isfinite(actual_arr)]

        if len(expected_arr) < 2 or len(actual_arr) < 2:
            return 0.0, 1.0

        result = ks_2samp(expected_arr, actual_arr)
        return float(result.statistic), float(result.pvalue)  # type: ignore[arg-type]

    # ------------------------------------------------------------------
    # Wasserstein (Earth Mover's) distance
    # ------------------------------------------------------------------

    @staticmethod
    def compute_wasserstein(
        expected: np.ndarray,
        actual: np.ndarray,
    ) -> float:
        """Compute Wasserstein (Earth Mover's) distance between two distributions.

        More robust than KS for multi-modal distributions.

        Args:
            expected: Reference distribution.
            actual: Current distribution.

        Returns:
            Wasserstein distance.
        """
        from scipy.stats import wasserstein_distance  # type: ignore[import-untyped]

        expected_arr = np.asarray(expected).flatten()
        actual_arr = np.asarray(actual).flatten()

        expected_arr = expected_arr[np.isfinite(expected_arr)]
        actual_arr = actual_arr[np.isfinite(actual_arr)]

        if len(expected_arr) < 2 or len(actual_arr) < 2:
            return 0.0

        return float(wasserstein_distance(expected_arr, actual_arr))

    # ------------------------------------------------------------------
    # Batch feature drift check
    # ------------------------------------------------------------------

    def check_feature(
        self,
        reference: np.ndarray,
        current: np.ndarray,
        feature_name: str = "unknown",
    ) -> DriftResult:
        """Check drift for a single feature.

        Args:
            reference: Reference (training) feature values.
            current: Current (production) feature values.
            feature_name: Name for reporting.

        Returns:
            DriftResult with PSI and severity.
        """
        psi = self.compute_psi(reference, current, bins=self._n_bins)

        ref_mean = float(np.mean(reference[np.isfinite(reference)]))
        cur_mean = float(np.mean(current[np.isfinite(current)]))
        mean_shift = (
            abs(cur_mean - ref_mean) / abs(ref_mean) * 100
            if abs(ref_mean) > 1e-8
            else 0.0
        )

        if psi >= self._psi_threshold:
            severity = DriftSeverity.SIGNIFICANT
        elif psi >= self._psi_mild:
            severity = DriftSeverity.MILD
        else:
            severity = DriftSeverity.NONE

        return DriftResult(
            feature_name=feature_name,
            psi=psi,
            severity=severity,
            reference_mean=ref_mean,
            current_mean=cur_mean,
            mean_shift_pct=mean_shift,
        )

    def check_features(
        self,
        reference: pd.DataFrame,
        current: pd.DataFrame,
    ) -> DriftReport:
        """Check drift for all features in DataFrames.

        Args:
            reference: Reference feature DataFrame (training time).
            current: Current feature DataFrame (production time).

        Returns:
            DriftReport with per-feature results.
        """
        from datetime import datetime

        results: list[DriftResult] = []

        # Find common feature columns
        ref_features = [c for c in reference.columns if c not in ("symbol", "trade_date")]
        cur_features = [c for c in current.columns if c not in ("symbol", "trade_date")]
        common = sorted(set(ref_features) & set(cur_features))

        if not common:
            return DriftReport(
                timestamp=datetime.now(UTC).isoformat(),
                results=[],
                any_significant=False,
                summary="No common feature columns found for drift check",
            )

        for feat in common:
            result = self.check_feature(
                reference[feat].to_numpy(),
                current[feat].to_numpy(),
                feature_name=feat,
            )
            results.append(result)

        any_sig = any(r.severity == DriftSeverity.SIGNIFICANT for r in results)

        sig_features = [r.feature_name for r in results if r.severity == DriftSeverity.SIGNIFICANT]
        summary_parts = [f"{len(results)} features checked"]
        if sig_features:
            summary_parts.append(
                f"SIGNIFICANT DRIFT in: {', '.join(sig_features[:5])}"
            )
        else:
            mild_count = sum(1 for r in results if r.severity == DriftSeverity.MILD)
            summary_parts.append(
                f"OK ({mild_count} mild, {len(results) - mild_count} clean)"
            )

        return DriftReport(
            timestamp=datetime.now(UTC).isoformat(),
            results=results,
            any_significant=any_sig,
            summary=" | ".join(summary_parts),
        )

    def check_prediction_drift(
        self,
        reference_predictions: np.ndarray,
        current_predictions: np.ndarray,
        ks_threshold: float = 0.15,
    ) -> dict[str, float]:
        """Check prediction distribution drift with KS + Wasserstein.

        Args:
            reference_predictions: Training-time model predictions.
            current_predictions: Current production predictions.
            ks_threshold: KS statistic threshold for drift flag.

        Returns:
            Dict with ks_stat, ks_pvalue, wasserstein, drifted (bool).
        """
        ks_stat, ks_pval = self.compute_ks(
            reference_predictions, current_predictions
        )
        ws_dist = self.compute_wasserstein(
            reference_predictions, current_predictions
        )
        psi = self.compute_psi(reference_predictions, current_predictions)

        return {
            "ks_statistic": ks_stat,
            "ks_pvalue": ks_pval,
            "wasserstein": ws_dist,
            "psi": psi,
            "drifted": ks_stat > ks_threshold or psi >= self._psi_threshold,
        }
