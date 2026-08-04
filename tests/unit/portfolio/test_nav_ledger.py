"""Tests for NAVLedger — daily NAV tracking with Parquet persistence."""

from __future__ import annotations

from pathlib import Path

from qp.portfolio.nav_ledger import NAV_DIR, NAV_PARQUET, NAVLedger


class TestNAVLedger:
    def test_record_and_load(self, tmp_path: Path) -> None:
        """Record daily NAVs and load them back sorted by date."""
        original_dir = str(NAV_DIR)
        original_parquet = str(NAV_PARQUET)
        try:
            # Redirect to tmp
            import qp.portfolio.nav_ledger as mod

            mod.NAV_DIR = tmp_path / "portfolio"
            mod.NAV_PARQUET = mod.NAV_DIR / "nav_history.parquet"

            ledger = NAVLedger()
            ledger.record_daily("2026-07-01", total_value=1_000_000.0, cash=100_000.0)
            ledger.record_daily("2026-07-02", total_value=1_010_000.0, cash=90_000.0)
            ledger.record_daily("2026-07-03", total_value=1_005_000.0, cash=95_000.0)

            df = ledger.load_history()
            assert df.height == 3
            assert df["date"].to_list() == ["2026-07-01", "2026-07-02", "2026-07-03"]
            assert df["total_nav"].to_list() == [1_000_000.0, 1_010_000.0, 1_005_000.0]
        finally:
            mod.NAV_DIR = Path(original_dir)
            mod.NAV_PARQUET = Path(original_parquet)

    def test_idempotent_record(self, tmp_path: Path) -> None:
        """Recording the same date twice replaces the old value."""
        import qp.portfolio.nav_ledger as mod

        mod.NAV_DIR = tmp_path / "portfolio"
        mod.NAV_PARQUET = mod.NAV_DIR / "nav_history.parquet"

        try:
            ledger = NAVLedger()
            ledger.record_daily("2026-07-01", total_value=1_000_000.0)
            ledger.record_daily("2026-07-01", total_value=1_100_000.0)  # Overwrite

            df = ledger.load_history()
            assert df.height == 1
            assert df["total_nav"][0] == 1_100_000.0
        finally:
            mod.NAV_DIR = NAV_DIR
            mod.NAV_PARQUET = NAV_PARQUET

    def test_get_latest(self, tmp_path: Path) -> None:
        """get_latest returns most recent record."""
        import qp.portfolio.nav_ledger as mod

        mod.NAV_DIR = tmp_path / "portfolio"
        mod.NAV_PARQUET = mod.NAV_DIR / "nav_history.parquet"

        try:
            ledger = NAVLedger()
            assert ledger.get_latest() is None  # Empty

            ledger.record_daily("2026-07-01", total_value=1_000_000.0)
            ledger.record_daily("2026-07-05", total_value=1_050_000.0)

            latest = ledger.get_latest()
            assert latest is not None
            assert latest["date"] == "2026-07-05"
            assert latest["total_nav"] == 1_050_000.0
        finally:
            mod.NAV_DIR = NAV_DIR
            mod.NAV_PARQUET = NAV_PARQUET

    def test_empty_history(self, tmp_path: Path) -> None:
        """Empty history returns empty DataFrame."""
        import qp.portfolio.nav_ledger as mod

        mod.NAV_DIR = tmp_path / "portfolio"
        mod.NAV_PARQUET = mod.NAV_DIR / "nav_history.parquet"

        try:
            ledger = NAVLedger()
            df = ledger.load_history()
            assert df.is_empty() if hasattr(df, "is_empty") else df.height == 0
            assert ledger.get_latest() is None
            assert ledger.row_count() == 0
        finally:
            mod.NAV_DIR = NAV_DIR
            mod.NAV_PARQUET = NAV_PARQUET

    def test_with_positions_and_decision(self, tmp_path: Path) -> None:
        """Record with optional metadata fields."""
        import qp.portfolio.nav_ledger as mod

        mod.NAV_DIR = tmp_path / "portfolio"
        mod.NAV_PARQUET = mod.NAV_DIR / "nav_history.parquet"

        try:
            ledger = NAVLedger()
            ledger.record_daily(
                "2026-07-15",
                total_value=1_200_000.0,
                cash=200_000.0,
                benchmark_value=1_050_000.0,
                n_positions=8,
                decision_id="dp-2026-07-15-abc12345",
            )

            df = ledger.load_history()
            row = df.row(0, named=True)
            assert row["n_positions"] == 8
            assert row["decision_id"] == "dp-2026-07-15-abc12345"
            assert row["benchmark_value"] == 1_050_000.0
            assert row["positions_value"] == 1_000_000.0
        finally:
            mod.NAV_DIR = NAV_DIR
            mod.NAV_PARQUET = NAV_PARQUET
