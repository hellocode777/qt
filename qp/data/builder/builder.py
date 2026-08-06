"""DatasetBuilder — assembles validated DataFrames into published Data Products.

Implements dp.md §7.5-7.9:
  - §7.5: Builder in component chain between Corporate Action Engine and Dataset Registry
  - §7.6: Silver-to-Gold tier transition
  - §7.7: 12-field Dataset Contract
  - §7.9: register_source() / build_dataset() public interface
  - §7.10: Atomic publication (failure never overwrites previous version)
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import polars as pl
from loguru import logger

from qp.data.builder.config import BuildConfig, DatasetMetadata
from qp.data.builder.result import BuildResult
from qp.data.dataset.registry import DatasetRegistry


class DatasetBuilder:
    """Assembles Data Products from cleaned, validated DataFrames.

    Responsibilities:
      1. Accept a Polars DataFrame from upstream (cleaning/validation).
      2. Attach the 12 metadata fields via DatasetMetadata.
      3. Validate the DataFrame against the registered contract.
      4. Persist to parquet with _metadata.json companion.
      5. Register with DatasetRegistry.
      6. Atomic publication: on failure, previous version stays authoritative.

    Usage::

        from qp.data.builder import DatasetBuilder, BuildConfig, DatasetMetadata

        builder = DatasetBuilder()
        builder.register_source("akshare", DailyPriceContract)
        metadata = DatasetMetadata(
            name="daily_price",
            owner="data-layer",
            source="akshare",
            schema={"trade_date": "date", "symbol": "str", "close": "float64"},
            frequency="daily",
            primary_key=["trade_date", "symbol"],
        )
        result = builder.build(df, metadata)
        assert result.success
    """

    def __init__(self, config: BuildConfig | None = None) -> None:
        self.config = config or BuildConfig()
        self._registry = DatasetRegistry(base_dir=self.config.output_dir)
        self._source_contracts: dict[str, type] = {}

    # ── Source registration ──────────────────────────────────────

    def register_source(self, source_name: str, contract_class: type) -> None:
        """Map a source name to its contract class.

        Source names: 'akshare', 'tencent', 'demo', etc.
        Contract classes must have a ``.validate(df) -> list[str]`` interface
        (e.g. DailyPriceContract).

        Args:
            source_name: Adapter name (e.g. 'akshare').
            contract_class: Contract class (e.g. DailyPriceContract).
        """
        self._source_contracts[source_name] = contract_class
        logger.debug(
            "数据源 '{}' 已注册契约类 '{}'",
            source_name,
            contract_class.__name__,
        )

    # ── Main entry point ─────────────────────────────────────────

    def build(self, df: pl.DataFrame, metadata: DatasetMetadata) -> BuildResult:
        """Assemble a DataFrame into a published Dataset.

        Pipeline:
          1. Derive coverage date range from the DataFrame.
          2. Validate metadata completeness.
          3. Validate against registered contract (if source is registered).
          4. Assign version (today's date if not set).
          5. Persist to parquet + optional _metadata.json.
          6. Register with DatasetRegistry.

        Args:
            df: Cleaned, validated DataFrame to publish.
            metadata: DatasetMetadata with at minimum name, owner, source,
                      schema, frequency, primary_key.

        Returns:
            BuildResult with success flag, version, path, and stats.
        """
        errors: list[str] = []

        if df.is_empty():
            msg = "DataFrame 为空，无法构建 Dataset"
            logger.error("Build 失败: {}", msg)
            return BuildResult(success=False, dataset_name=metadata.name, errors=[msg])

        # ── Step 1: Validate metadata ──
        meta_errors = metadata.validate()
        if meta_errors:
            errors.extend(meta_errors)
            logger.error("元数据校验失败: {} 项错误", len(meta_errors))
            return BuildResult(
                success=False,
                dataset_name=metadata.name,
                errors=errors,
                stats={"n_meta_errors": len(meta_errors)},
            )

        # ── Step 2: Derive coverage from data ──
        metadata.coverage_start, metadata.coverage_end = self._derive_coverage(df)
        logger.info(
            "Dataset '{}' 覆盖范围: {} ~ {}",
            metadata.name,
            metadata.coverage_start,
            metadata.coverage_end,
        )

        # ── Step 3: Validate against contract ──
        contract = self._source_contracts.get(metadata.source)
        if self.config.require_contract and contract is None:
            errors.append(
                f"数据源 '{metadata.source}' 未注册契约。"
                f"请先调用 builder.register_source('{metadata.source}', ContractClass)"
            )
            logger.error("Build 失败: 数据源 '{}' 未注册契约", metadata.source)
            return BuildResult(
                success=False,
                dataset_name=metadata.name,
                errors=errors,
                stats={"rows": df.height, "columns": len(df.columns)},
            )
        if contract is not None:
            try:
                validation_errors = contract.validate(df)
            except Exception as e:
                validation_errors = [f"契约校验异常: {e}"]
            if validation_errors:
                errors.extend(validation_errors)
                if self.config.fail_on_validation_error:
                    logger.error(
                        "契约校验失败 ({}): {} 项错误",
                        contract.__name__,
                        len(validation_errors),
                    )
                    return BuildResult(
                        success=False,
                        dataset_name=metadata.name,
                        errors=errors,
                        stats={"rows": df.height, "columns": len(df.columns)},
                    )

        # ── Step 4: Assign version ──
        if not metadata.version:
            metadata.version = date.today().isoformat()

        # ── Step 5: Persist ──
        output_dir = Path(self.config.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{metadata.name}_{metadata.version}.parquet"

        try:
            df.write_parquet(str(output_path))
            if self.config.persist_metadata:
                self._write_metadata_json(output_path, metadata, df)
        except Exception as e:
            # Atomic publication: existing version is untouched on write failure
            errors.append(f"持久化失败: {e}")
            logger.error("Build 持久化失败, 旧版本不受影响: {}", e)
            return BuildResult(
                success=False,
                dataset_name=metadata.name,
                version=metadata.version,
                errors=errors,
            )

        # ── Step 6: Register ──
        self._registry.register(
            name=metadata.name,
            version=metadata.version,
            path=str(output_path),
            metadata=metadata.to_dict(),
        )
        logger.info(
            "Dataset '{}' v'{}' 已注册 ({} 行, {} 列)",
            metadata.name,
            metadata.version,
            df.height,
            len(df.columns),
        )

        return BuildResult(
            success=True,
            dataset_name=metadata.name,
            version=metadata.version,
            path=str(output_path),
            metadata=metadata.to_dict(),
            rows=df.height,
            symbols=df["symbol"].n_unique() if "symbol" in df.columns else 1,
            date_range=(
                str(metadata.coverage_start) if metadata.coverage_start else "",
                str(metadata.coverage_end) if metadata.coverage_end else "",
            ),
            stats={"columns": len(df.columns)},
        )

    # ── Helpers ──────────────────────────────────────────────────

    @staticmethod
    def _derive_coverage(df: pl.DataFrame) -> tuple[date | None, date | None]:
        """Derive date range from a trade_date column."""
        date_col = "trade_date" if "trade_date" in df.columns else None
        if date_col is None:
            return None, None
        min_val = df[date_col].min()
        max_val = df[date_col].max()
        if min_val is None or max_val is None:
            return None, None
        return (
            date.fromisoformat(str(min_val)[:10]),
            date.fromisoformat(str(max_val)[:10]),
        )

    @staticmethod
    def _write_metadata_json(
        output_path: Path,
        metadata: DatasetMetadata,
        df: pl.DataFrame,
    ) -> None:
        """Write a _metadata.json companion file alongside the parquet."""
        meta_path = output_path.with_suffix("").with_name(f"{output_path.stem}_metadata.json")
        payload: dict[str, Any] = {
            **metadata.to_dict(),
            "rows": df.height,
            "symbols": df["symbol"].n_unique() if "symbol" in df.columns else 1,
            "columns": df.columns,
            "last_updated": datetime.now(UTC).isoformat(),
        }
        meta_path.write_text(
            json.dumps(payload, indent=2, default=str, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.debug("元数据已写入: {}", meta_path)


# ── Module-level convenience ─────────────────────────────────────


def build_dataset(df: pl.DataFrame, metadata: dict[str, Any]) -> BuildResult:
    """Convenience function for building a dataset from a metadata dict.

    Args:
        df: DataFrame to publish.
        metadata: Dict with keys matching DatasetMetadata fields.

    Returns:
        BuildResult.
    """
    # Pop only fields that DatasetMetadata accepts
    valid_keys = {f.name for f in __import__("dataclasses").fields(DatasetMetadata)}
    md_kwargs = {k: v for k, v in metadata.items() if k in valid_keys}
    md = DatasetMetadata(**md_kwargs)
    builder = DatasetBuilder(BuildConfig(require_contract=False))
    return builder.build(df, md)
