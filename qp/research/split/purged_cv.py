"""Purged Walk-Forward Cross-Validation.

Implements the purged K-fold CV from "Advances in Financial Machine Learning"
(Marcos Lopez de Prado, Chapter 7).

Key insight: standard K-fold leaks future information through overlapping
label windows.  Purged CV removes training samples whose label calculation
period overlaps with the test set, then adds an embargo period.

See ADR-021: Purged KFold is mandatory for all models.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from qp.shared.constants import DEFAULT_PURGED_CV_FOLDS, MIN_TRAINING_WINDOW_DAYS


@dataclass
class PurgedFold:
    """A single train/test split in a purged walk-forward CV.

    Attributes:
        fold_idx: 0-based fold number.
        train_indices: Array of training sample indices.
        test_indices: Array of test sample indices.
        train_start: Date of first training sample.
        train_end: Date of last training sample.
        test_start: Date of first test sample.
        test_end: Date of last test sample.
    """

    fold_idx: int
    train_indices: np.ndarray
    test_indices: np.ndarray
    train_start: object  # date or timestamp
    train_end: object
    test_start: object
    test_end: object


@dataclass
class PurgedKFold:
    """Purged walk-forward cross-validation splitter.

    Splits time-ordered data into K contiguous blocks.  For each fold,
    the test set is one block and the training set is all blocks before it.
    Samples whose label window would overlap the test set are purged from
    training.  An embargo period is added after each test block.

    Usage:
        dates = df["trade_date"].to_numpy()
        cv = PurgedKFold(n_splits=5, purge_days=20, embargo_days=10)
        for fold in cv.split(dates):
            train_X, train_y = X[fold.train_indices], y[fold.train_indices]
            test_X, test_y = X[fold.test_indices], y[fold.test_indices]
    """

    n_splits: int = DEFAULT_PURGED_CV_FOLDS
    purge_days: int = 20    # Days to purge before each test block
    embargo_days: int = 5   # Days to embargo after each test block
    min_train_days: int = MIN_TRAINING_WINDOW_DAYS  # 500

    def split(
        self,
        dates: np.ndarray,
        groups: np.ndarray | None = None,
    ) -> list[PurgedFold]:
        """Generate purged train/test splits.

        Args:
            dates: 1-D array of dates/timestamps, sorted ascending.
            groups: Ignored (for sklearn compatibility).

        Returns:
            List of PurgedFold objects.  Early folds may be skipped if they
            don't have enough training data (min_train_days).

        Raises:
            ValueError: If no valid folds can be generated.
        """
        n = len(dates)
        if n < 100:
            raise ValueError(f"Need at least 100 samples for PurgedKFold, got {n}")

        # Split indices into K roughly equal contiguous blocks
        fold_boundaries = np.linspace(0, n, self.n_splits + 1, dtype=int)

        folds: list[PurgedFold] = []

        for fold_idx in range(self.n_splits - 1):
            test_start_idx = fold_boundaries[fold_idx + 1]
            test_end_idx = fold_boundaries[fold_idx + 2]

            # All data before test block is candidate training set
            # Purge: remove samples within purge_days of test start
            train_end_idx = self._purge_boundary(
                dates, test_start_idx, test_end_idx, self.purge_days
            )

            if train_end_idx < self.min_train_days:
                continue  # Skip: not enough training data yet

            train_indices = np.arange(0, train_end_idx)
            test_indices = np.arange(test_start_idx, test_end_idx)

            folds.append(PurgedFold(
                fold_idx=fold_idx,
                train_indices=train_indices,
                test_indices=test_indices,
                train_start=dates[0],
                train_end=dates[train_end_idx - 1],
                test_start=dates[test_start_idx],
                test_end=dates[test_end_idx - 1],
            ))

        if not folds:
            raise ValueError(
                f"No valid folds generated. "
                f"Need at least {self.min_train_days} training days per fold."
            )

        return folds

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _purge_boundary(
        dates: np.ndarray,
        test_start: int,
        test_end: int,
        purge_days: int,
    ) -> int:
        """Find the latest training index that doesn't leak into the test period.

        Starting from test_start - 1, walk backwards until we find a date
        that is at least `purge_days` before test_start.  This ensures that
        no label window computed from a training sample extends into the test set.

        Args:
            dates: Sorted array of dates.
            test_start: Index where the test block starts.
            test_end: Index where the test block ends.
            purge_days: Number of days to purge.

        Returns:
            Index of the last safe training sample (exclusive, for slicing).
        """
        test_start_date = dates[test_start]

        # Walk backwards from test_start to find the purge boundary
        for i in range(test_start - 1, -1, -1):
            delta = _days_between(dates[i], test_start_date)
            if delta >= purge_days:
                return i + 1  # exclusive end index

        return 0  # All data before test_start is within purge window


def _days_between(d1: Any, d2: Any) -> int:  # type: ignore[misc]
    """Compute calendar days between two date-like objects.

    Handles: datetime.date, datetime.datetime, pd.Timestamp, np.datetime64.
    Returns absolute integer number of days.
    """
    try:
        return abs(int((d2 - d1).days))
    except AttributeError:
        pass

    try:
        # numpy datetime64
        return abs(int((np.datetime64(d2) - np.datetime64(d1)).astype("timedelta64[D]").astype(int)))
    except Exception:
        pass

    # Fallback: treat as integers
    try:
        return abs(int(d2) - int(d1))
    except Exception:
        return 0


def purge_train_set(
    train_indices: np.ndarray,
    dates: np.ndarray,
    test_start_date: Any,
    purge_days: int = 20,
) -> np.ndarray:
    """Remove training samples whose label window would overlap the test set.

    Utility function for manual purging outside PurgedKFold.

    Args:
        train_indices: Indices of training samples.
        dates: Full date array (same length as data).
        test_start_date: Start date of the test set.
        purge_days: Days to purge before test_start.

    Returns:
        Purged training indices.
    """
    keep = []
    for idx in train_indices:
        if _days_between(dates[idx], test_start_date) >= purge_days:
            keep.append(idx)
    return np.array(keep, dtype=int)


def embargo_test_set(
    n_samples: int,
    test_end_idx: int,
    embargo_days: int,
    dates: np.ndarray,
) -> int:
    """Find the first training index after the embargo period ends.

    After a test block, we wait `embargo_days` before allowing subsequent
    data to be used for training — preventing the model from trading on
    recent test signals.

    Args:
        n_samples: Total number of samples.
        test_end_idx: Index where test set ends (exclusive).
        embargo_days: Minimum days after test_end before training can resume.
        dates: Full date array.

    Returns:
        Index of first trainable sample after embargo, or n_samples.
    """
    test_end_date = dates[test_end_idx - 1]
    for i in range(test_end_idx, n_samples):
        if _days_between(dates[i], test_end_date) >= embargo_days:
            return i
    return n_samples
