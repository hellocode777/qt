"""PanderaValidator — bridge between Pandera schemas and ValidationGate infrastructure.

Pandera provides declarative, self-documenting schema validation for
Pandas and Polars DataFrames. This module wraps Pandera's validate()
calls into the QP native CheckResult / ValidationReport types,
making Pandera schemas a drop-in option within ValidationGate.

Design:
  - Pandera is an *additional* validation path, not a replacement.
  - Our hand-written checks (checks.py) remain primary for business-logic checks.
  - Pandera excels at: schema definition, type checking, null-rate enforcement,
    value-range constraints (gt/ge/lt/le), and self-documenting schemas.
  - The two can coexist: run Pandera for schema, then our checks for logic.

Usage::

    from qp.data.validation.pandera_schemas import DailyPriceSchema
    from qp.data.validation.pandera_validator import PanderaValidator

    result = PanderaValidator.validate(df, DailyPriceSchema)
    # → CheckResult (passed=True/False, severity, detail)
"""

from __future__ import annotations

import polars as pl
from loguru import logger
from pandera.api.polars.model import DataFrameModel
from pandera.errors import SchemaErrors

from qp.data.validation.result import CheckResult, Severity


class PanderaValidator:
    """Validate DataFrames using Pandera schemas, returning CheckResults.

    Bridges Pandera's exception-based API into QP's structured result types.
    """

    @staticmethod
    def validate(
        df: pl.DataFrame,
        schema: type[DataFrameModel],
        schema_name: str | None = None,
    ) -> CheckResult:
        """Validate a Polars DataFrame against a Pandera schema.

        Args:
            df: Polars DataFrame to validate.
            schema: Pandera DataFrameModel class (e.g. DailyPriceSchema).
            schema_name: Override the schema name in the CheckResult.

        Returns:
            CheckResult — passed=True if schema validates, False otherwise.
        """
        name = schema_name or getattr(schema.Config, "name", schema.__name__)
        check_name = f"pandera_{name}"

        try:
            schema.validate(df, lazy=True)
        except SchemaErrors as exc:
            # Lazy mode collects all errors at once
            error_count = len(exc.schema_errors)
            # Categorize: missing columns / wrong types are ERROR, constraint
            # violations are WARNING (business logic, not data corruption)
            severity = Severity.ERROR if error_count > 0 else Severity.WARNING

            detail_parts: list[str] = []
            for err in exc.schema_errors[:5]:  # Show first 5 errors
                detail_parts.append(str(err)[:120])
            if error_count > 5:
                detail_parts.append(f"... and {error_count - 5} more")

            logger.warning(
                "Pandera({}): {} 个 schema 错误 — {}",
                name,
                error_count,
                detail_parts[0] if detail_parts else "?",
            )

            return CheckResult(
                check_name=check_name,
                passed=False,
                severity=severity,
                detail=f"{error_count} schema errors: {'; '.join(detail_parts)}",
                affected_rows=error_count,
                metadata={
                    "schema_name": name,
                    "error_count": error_count,
                    "errors": [str(e) for e in exc.schema_errors],
                },
            )
        except Exception as exc:
            logger.error("Pandera({}): 意外错误 — {}", name, exc)
            return CheckResult(
                check_name=check_name,
                passed=False,
                severity=Severity.ERROR,
                detail=f"Unexpected Pandera error: {exc}",
                metadata={"schema_name": name, "exception": str(exc)},
            )

        logger.info("Pandera({}): 校验通过 ({} 行, {} 列)", name, df.height, len(df.columns))
        return CheckResult(
            check_name=check_name,
            passed=True,
            severity=Severity.INFO,
            detail=f"Schema '{name}' validates: {df.height} rows, {len(df.columns)} columns",
            metadata={"schema_name": name, "rows": df.height, "columns": len(df.columns)},
        )

    @staticmethod
    def validate_or_raise(
        df: pl.DataFrame,
        schema: type[DataFrameModel],
    ) -> None:
        """Strict validation — raises SchemaErrors on failure.

        Use when you want fail-fast behavior (e.g. inside a pipeline step
        where invalid data should halt immediately).
        """
        schema.validate(df, lazy=False)
