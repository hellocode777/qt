"""Factor Store — three-tier factor persistence (DP-002 §4.3).

Tiers:
  raw/     — raw factor outputs (S1: experiment snapshots)
  refined/ — post-refinery factor values (S2)
  feature/ — versioned feature matrices for model training (S3)

Each tier stores Parquet files with metadata (version, date_range,
hash, row_count) for reproducibility and audit (S4).

Directory structure (S5):
  data/factor_store/
  ├── raw/
  ├── refined/
  └── feature/
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl
from loguru import logger

# ------------------------------------------------------------------
# Default paths
# ------------------------------------------------------------------

DEFAULT_STORE_ROOT = Path("data/factor_store")
RAW_TIER = "raw"
REFINED_TIER = "refined"
FEATURE_TIER = "feature"
TIERS = [RAW_TIER, REFINED_TIER, FEATURE_TIER]


# ------------------------------------------------------------------
# Store metadata (S4)
# ------------------------------------------------------------------


@dataclass
class TierMetadata:
    """Metadata for a factor store tier (DP-002 §4.3, S4).

    Attributes:
        version: Schema version (e.g. "2.0").
        date_range: (start_date, end_date) inclusive.
        hash: Content hash for reproducibility.
        row_count: Total number of rows.
        n_factors: Number of factors stored.
        n_days: Number of trading days covered.
        created_at: ISO timestamp of creation.
        factors: List of factor names in this tier.
    """

    version: str = "1.0.0"
    date_range: tuple[str, str] = ("", "")
    hash: str = ""
    row_count: int = 0
    n_factors: int = 0
    n_days: int = 0
    created_at: str = ""
    factors: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(UTC).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "date_start": self.date_range[0],
            "date_end": self.date_range[1],
            "hash": self.hash,
            "row_count": self.row_count,
            "n_factors": self.n_factors,
            "n_days": self.n_days,
            "created_at": self.created_at,
            "factors": self.factors,
        }

    @classmethod
    def from_df(
        cls,
        df: pl.DataFrame,
        version: str = "1.0.0",
        factors: list[str] | None = None,
    ) -> TierMetadata:
        """Build metadata from a factor DataFrame.

        Args:
            df: DataFrame with [trade_date, symbol, ...factor columns].
            version: Schema version string.
            factors: Explicit factor name list.

        Returns:
            TierMetadata populated from the data.
        """
        import hashlib

        dates = df["trade_date"].unique().sort()
        date_range = (
            str(dates.min()) if not dates.is_empty() else "",
            str(dates.max()) if not dates.is_empty() else "",
        )

        # Identify factor columns (not trade_date, symbol)
        factor_cols = factors or [
            c for c in df.columns if c not in ("trade_date", "symbol")
        ]
        content = df.select(factor_cols).to_pandas().to_csv(index=False).encode()
        content_hash = hashlib.sha256(content).hexdigest()[:16]

        return cls(
            version=version,
            date_range=date_range,
            hash=content_hash,
            row_count=df.height,
            n_factors=len(factor_cols),
            n_days=len(dates),
            factors=factor_cols,
        )


# ------------------------------------------------------------------
# Factor Store (S2-S5)
# ------------------------------------------------------------------


class FactorStore:
    """Three-tier factor persistence.

    Usage:
        store = FactorStore()
        store.ensure_dirs()

        # Save raw factors from experiment
        store.save_raw("momentum", raw_df, metadata)

        # Save refined factors after winsorize→neutralize→normalize
        store.save_refined("momentum", refined_df)

        # Build and save feature matrix
        store.save_feature_matrix("v2", feature_df, factor_names)
    """

    def __init__(self, root: Path | str | None = None) -> None:
        self._root = Path(root) if root else DEFAULT_STORE_ROOT

    @property
    def root(self) -> Path:
        return self._root

    @property
    def raw_dir(self) -> Path:
        return self._root / RAW_TIER

    @property
    def refined_dir(self) -> Path:
        return self._root / REFINED_TIER

    @property
    def feature_dir(self) -> Path:
        return self._root / FEATURE_TIER

    # ------------------------------------------------------------------
    # Directory management (S5)
    # ------------------------------------------------------------------

    def ensure_dirs(self) -> FactorStore:
        """Create the three-tier directory structure if it doesn't exist."""
        for tier in TIERS:
            (self._root / tier).mkdir(parents=True, exist_ok=True)
        return self

    def exists(self, tier: str, name: str) -> bool:
        """Check if a factor file exists in a tier."""
        path = self._path_for(tier, name)
        return path.exists()

    # ------------------------------------------------------------------
    # Raw tier (S1 — experiment snapshots)
    # ------------------------------------------------------------------

    def save_raw(
        self,
        name: str,
        df: pl.DataFrame,
        meta: TierMetadata | None = None,
    ) -> Path:
        """Save raw factor output.

        Args:
            name: Factor or dataset name (e.g. "momentum_raw").
            df: DataFrame with [trade_date, symbol, ...factor columns].
            meta: Optional metadata. Generated from df if None.

        Returns:
            Path to the saved Parquet file.
        """
        self.ensure_dirs()
        path = self._path_for(RAW_TIER, name)
        df.write_parquet(path)

        if meta is None:
            meta = TierMetadata.from_df(df)
        self._save_meta(RAW_TIER, name, meta)

        logger.info(
            "FactorStore(raw): saved '{}' — {} rows, {} factors, {}→{}",
            name,
            meta.row_count,
            meta.n_factors,
            meta.date_range[0],
            meta.date_range[1],
        )
        return path

    def load_raw(self, name: str) -> pl.DataFrame:
        """Load raw factor data."""
        path = self._path_for(RAW_TIER, name)
        if not path.exists():
            raise FileNotFoundError(f"Raw factor '{name}' not found at {path}")
        return pl.read_parquet(path)

    # ------------------------------------------------------------------
    # Refined tier (S2)
    # ------------------------------------------------------------------

    def save_refined(
        self,
        name: str,
        df: pl.DataFrame,
        meta: TierMetadata | None = None,
    ) -> Path:
        """Save post-refinery factor values.

        Factors have been through winsorize → normalize → neutralize
        and are ready for strategy consumption.

        Args:
            name: Factor or dataset name (e.g. "momentum_refined").
            df: DataFrame with [trade_date, symbol, ...factor columns].
            meta: Optional metadata.

        Returns:
            Path to the saved Parquet file.
        """
        self.ensure_dirs()
        path = self._path_for(REFINED_TIER, name)
        df.write_parquet(path)

        if meta is None:
            meta = TierMetadata.from_df(df, version="2.0")
        self._save_meta(REFINED_TIER, name, meta)

        logger.info(
            "FactorStore(refined): saved '{}' — {} rows, {} factors",
            name,
            meta.row_count,
            meta.n_factors,
        )
        return path

    def load_refined(self, name: str) -> pl.DataFrame:
        """Load refined factor data."""
        path = self._path_for(REFINED_TIER, name)
        if not path.exists():
            raise FileNotFoundError(f"Refined factor '{name}' not found at {path}")
        return pl.read_parquet(path)

    # ------------------------------------------------------------------
    # Feature tier (S3)
    # ------------------------------------------------------------------

    def save_feature_matrix(
        self,
        version: str,
        df: pl.DataFrame,
        factor_names: list[str] | None = None,
        meta: TierMetadata | None = None,
    ) -> Path:
        """Save a versioned feature matrix for model training.

        The feature matrix is the final product: all factors joined
        on (trade_date, symbol), ready for ML model input.

        Args:
            version: Feature matrix version (e.g. "v2.0").
            df: DataFrame with [trade_date, symbol, factor_1, factor_2, ...].
            factor_names: Explicit factor column names.
            meta: Optional metadata.

        Returns:
            Path to the saved Parquet file.
        """
        self.ensure_dirs()
        name = f"feature_matrix_{version}"
        path = self._path_for(FEATURE_TIER, name)
        df.write_parquet(path)

        if meta is None:
            meta = TierMetadata.from_df(df, version=version, factors=factor_names)
        self._save_meta(FEATURE_TIER, name, meta)

        logger.info(
            "FactorStore(feature): saved '{}' v{} — {} rows, {} factors",
            name,
            version,
            meta.row_count,
            meta.n_factors,
        )
        return path

    def load_feature_matrix(self, version: str) -> pl.DataFrame:
        """Load a versioned feature matrix."""
        name = f"feature_matrix_{version}"
        path = self._path_for(FEATURE_TIER, name)
        if not path.exists():
            raise FileNotFoundError(f"Feature matrix v{version} not found at {path}")
        return pl.read_parquet(path)

    def list_feature_versions(self) -> list[str]:
        """List available feature matrix versions."""
        versions: list[str] = []
        for f in self.feature_dir.glob("feature_matrix_*.parquet"):
            stem = f.stem  # feature_matrix_v2.0
            v = stem.replace("feature_matrix_", "")
            versions.append(v)
        return sorted(versions)

    # ------------------------------------------------------------------
    # Query (S4)
    # ------------------------------------------------------------------

    def get_meta(self, tier: str, name: str) -> TierMetadata | None:
        """Load metadata for a stored factor."""
        meta_path = self._meta_path_for(tier, name)
        if not meta_path.exists():
            return None
        import json

        data = json.loads(meta_path.read_text())
        return TierMetadata(
            version=data.get("version", "1.0.0"),
            date_range=(data.get("date_start", ""), data.get("date_end", "")),
            hash=data.get("hash", ""),
            row_count=data.get("row_count", 0),
            n_factors=data.get("n_factors", 0),
            n_days=data.get("n_days", 0),
            created_at=data.get("created_at", ""),
            factors=data.get("factors", []),
        )

    def list_tier(self, tier: str) -> list[str]:
        """List all factor names in a tier."""
        tier_dir = self._root / tier
        if not tier_dir.exists():
            return []
        return sorted(
            f.stem
            for f in tier_dir.glob("*.parquet")
            if not f.stem.startswith("_meta_")
        )

    def tier_summary(self, tier: str) -> dict[str, Any]:
        """Return summary of all factors in a tier."""
        names = self.list_tier(tier)
        total_rows = 0
        total_factors = 0
        metas: dict[str, dict[str, Any]] = {}

        for name in names:
            meta = self.get_meta(tier, name)
            if meta:
                total_rows += meta.row_count
                total_factors += meta.n_factors
                metas[name] = meta.to_dict()

        return {
            "tier": tier,
            "n_datasets": len(names),
            "total_rows": total_rows,
            "total_factors": total_factors,
            "datasets": names,
            "metadata": metas,
        }

    def full_summary(self) -> dict[str, Any]:
        """Return summary of all three tiers."""
        return {tier: self.tier_summary(tier) for tier in TIERS}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _path_for(self, tier: str, name: str) -> Path:
        return self._root / tier / f"{name}.parquet"

    def _meta_path_for(self, tier: str, name: str) -> Path:
        return self._root / tier / f"_meta_{name}.json"

    def _save_meta(self, tier: str, name: str, meta: TierMetadata) -> None:
        import json

        meta_path = self._meta_path_for(tier, name)
        meta_path.write_text(json.dumps(meta.to_dict(), ensure_ascii=False, indent=2))
