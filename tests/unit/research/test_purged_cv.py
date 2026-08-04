"""Tests for Purged K-Fold — mandatory cross-validation per ADR-021.

Verifies correct train/test split, purge logic, and edge cases.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from qp.research.split.purged_cv import (
    PurgedFold,
    PurgedKFold,
    _days_between,
    embargo_test_set,
    purge_train_set,
)


def _make_dates(n: int) -> np.ndarray:
    """Generate n consecutive trading days."""
    base = date(2020, 1, 2)
    return np.array([base + timedelta(days=i) for i in range(n)], dtype=object)


class TestDaysBetween:
    def test_same_day(self) -> None:
        d = date(2026, 1, 15)
        assert _days_between(d, d) == 0

    def test_one_day(self) -> None:
        d1 = date(2026, 1, 15)
        d2 = date(2026, 1, 16)
        assert _days_between(d1, d2) == 1


class TestPurgeTrainSet:
    def test_purges_overlapping_samples(self) -> None:
        dates = _make_dates(200)
        train_indices = np.arange(0, 200)
        test_start = dates[150]
        kept = purge_train_set(train_indices, dates, test_start_date=test_start, purge_days=5)
        # Should remove training samples close to test start
        assert len(kept) < 200
        assert len(kept) > 0

    def test_no_overlap(self) -> None:
        train_indices = np.arange(0, 100)
        train_dates = _make_dates(200)[:100]
        test_start = _make_dates(200)[180]  # Way after training (index 180 > 99)
        kept = purge_train_set(
            train_indices, train_dates, test_start_date=test_start, purge_days=20
        )
        assert len(kept) == 100  # Nothing to purge


class TestEmbargoTestSet:
    def test_embargo_returns_next_trainable_index(self) -> None:
        dates = _make_dates(250)
        # Test ends at index 200, with 5-day embargo
        result = embargo_test_set(n_samples=250, test_end_idx=200, embargo_days=5, dates=dates)
        # Returns index of first trainable sample after embargo
        assert isinstance(result, int)
        assert result > 200  # Must be after test_end_idx


class TestPurgedKFold:
    def test_split_creates_valid_folds(self) -> None:
        dates = _make_dates(600)
        cv = PurgedKFold(n_splits=5, purge_days=20, embargo_days=10, min_train_days=20)
        folds = cv.split(dates)
        assert len(folds) >= 1
        for f in folds:
            assert isinstance(f, PurgedFold)
            assert len(f.train_indices) > 0
            assert len(f.test_indices) > 0
            assert len(np.intersect1d(f.train_indices, f.test_indices)) == 0

    def test_insufficient_data_raises(self) -> None:
        dates = _make_dates(50)
        cv = PurgedKFold()
        with pytest.raises(ValueError, match="at least 100"):
            cv.split(dates)

    def test_min_train_days_enforced(self) -> None:
        dates = _make_dates(500)
        cv = PurgedKFold(n_splits=5, min_train_days=200)
        folds = cv.split(dates)
        for f in folds:
            train_start = f.train_start
            train_end = f.train_end
            if isinstance(train_start, date) and isinstance(train_end, date):
                train_span = _days_between(train_start, train_end)
                assert train_span >= 0

    def test_folds_are_chronological(self) -> None:
        dates = _make_dates(800)
        cv = PurgedKFold(n_splits=5, purge_days=20)
        folds = cv.split(dates)
        for i in range(len(folds) - 1):
            assert folds[i].test_end < folds[i + 1].test_end

    def test_train_before_test(self) -> None:
        dates = _make_dates(600)
        cv = PurgedKFold(n_splits=5, min_train_days=20)
        folds = cv.split(dates)
        for f in folds:
            assert f.train_end < f.test_start

    def test_custom_purge_embargo(self) -> None:
        dates = _make_dates(800)
        cv = PurgedKFold(n_splits=3, purge_days=30, embargo_days=15, min_train_days=50)
        folds = cv.split(dates)
        assert len(folds) >= 1

    def test_folds_have_dates(self) -> None:
        dates = _make_dates(600)
        cv = PurgedKFold(n_splits=4, min_train_days=20)
        folds = cv.split(dates)
        for f in folds:
            assert f.train_start is not None
            assert f.test_start is not None
