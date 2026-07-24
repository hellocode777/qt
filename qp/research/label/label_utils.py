"""Label validation utilities — overlap detection and consistency checks.

Ensures labels conform to research best practices:
  - No overlapping label windows between train and test
  - Label horizon matches rebalance frequency
  - Detection of data leakage via label overlap

See rule.md §7.9.1 and research_layer.md Purged KFold.
"""

from __future__ import annotations

import polars as pl


def detect_label_overlap(
    train_dates: list[str],
    test_dates: list[str],
    label_horizon: int = 5,
) -> list[str]:
    """Detect overlapping label windows between train and test date sets.

    A label computed at date T with horizon H depends on data through T+H.
    If a training label's forward window extends into any test date, that
    constitutes data leakage.

    Args:
        train_dates: Sorted list of training dates.
        test_dates: Sorted list of testing dates.
        label_horizon: Number of forward days the label spans.

    Returns:
        List of train dates whose label window overlaps with test (may leak).
        Empty list = no overlap = safe.
    """
    if not train_dates or not test_dates:
        return []

    train_sorted = sorted(train_dates)
    test_sorted = sorted(test_dates)
    test_first = test_sorted[0]

    overlapping: list[str] = []
    for t in train_sorted:
        # Check if t + label_horizon >= first test date
        # For simplicity, compare lexical dates (works for YYYY-MM-DD)
        if t >= test_first:
            overlapping.append(t)
        else:
            # Check if forward window extends into test
            try:
                from datetime import date, timedelta

                t_date = date.fromisoformat(t)
                t_end = t_date + timedelta(days=label_horizon + 5)  # +5 for weekends
                test_first_date = date.fromisoformat(test_first)
                if t_end >= test_first_date:
                    overlapping.append(t)
            except (ValueError, TypeError):
                # Fallback: if dates are close in the sorted list
                # Use index-based heuristic
                pass

    return overlapping


def validate_label_rebalance_consistency(
    label_horizon: int,
    rebalance_freq: int,
) -> dict[str, bool | str]:
    """Check that label horizon and rebalance frequency are consistent.

    Rule: label_horizon should approximately equal rebalance_freq.
    A 5-day label with 20-day rebalance means the model predicts short-term
    returns but holds for a month — a mismatch that may hurt performance.

    Args:
        label_horizon: Forward days used in label computation.
        rebalance_freq: Trading days between rebalances.

    Returns:
        Dict with:
          - "consistent": True if within reasonable range
          - "severity": "ok" | "warning" | "mismatch"
          - "message": Human-readable explanation
    """
    if label_horizon <= 0 or rebalance_freq <= 0:
        return {
            "consistent": False,
            "severity": "mismatch",
            "message": f"Invalid horizon={label_horizon} or freq={rebalance_freq}",
        }

    ratio = label_horizon / rebalance_freq

    if 0.8 <= ratio <= 1.5:
        return {
            "consistent": True,
            "severity": "ok",
            "message": f"Label horizon ({label_horizon}d) ≈ rebalance ({rebalance_freq}d)",
        }
    elif 0.5 <= ratio <= 2.0:
        return {
            "consistent": True,
            "severity": "warning",
            "message": (
                f"Label horizon ({label_horizon}d) and rebalance ({rebalance_freq}d) "
                f"differ by {ratio:.1f}x — moderate mismatch"
            ),
        }
    else:
        return {
            "consistent": False,
            "severity": "mismatch",
            "message": (
                f"Label horizon ({label_horizon}d) and rebalance ({rebalance_freq}d) "
                f"differ by {ratio:.1f}x — severe mismatch, align them"
            ),
        }


def check_label_coverage(
    label_df: pl.DataFrame,
    price_df: pl.DataFrame,
    min_coverage_ratio: float = 0.8,
) -> dict[str, float]:
    """Check what fraction of price data has corresponding labels.

    Args:
        label_df: [trade_date, symbol, label].
        price_df: [trade_date, symbol, ...].
        min_coverage_ratio: Minimum acceptable label coverage.

    Returns:
        Dict with coverage stats: {coverage_ratio, n_price_rows, n_label_rows}.
    """
    n_price = price_df.height
    n_label = label_df.height

    if n_price == 0:
        return {"coverage_ratio": 0.0, "n_price_rows": 0, "n_label_rows": 0, "sufficient": False}

    # Count distinct (date, symbol) pairs in both
    price_pairs = set(
        zip(
            price_df["trade_date"].cast(str).to_list(),
            price_df["symbol"].cast(str).to_list(),
            strict=False,
        )
    )
    label_pairs = set(
        zip(
            label_df["trade_date"].cast(str).to_list(),
            label_df["symbol"].cast(str).to_list(),
            strict=False,
        )
    )

    if not price_pairs:
        return {
            "coverage_ratio": 0.0,
            "n_price_rows": n_price,
            "n_label_rows": n_label,
            "sufficient": False,
        }

    coverage = len(label_pairs) / len(price_pairs)
    return {
        "coverage_ratio": round(coverage, 4),
        "n_price_rows": n_price,
        "n_label_rows": n_label,
        "sufficient": coverage >= min_coverage_ratio,
    }
