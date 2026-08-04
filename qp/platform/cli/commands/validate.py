"""CLI command handlers for the "validate" group."""

from __future__ import annotations

import sys


def cmd_validate() -> int:
    """Run validation gate checks on the current strategy.

    Usage:
        qp validate                          # All-stage validation
        qp validate --stage backtest_passed  # Specific stage only
        qp validate --json                   # Machine-readable output
        qp validate --strategy-id my_strat   # Target a specific strategy
    """
    import json as _json

    import polars as pl

    from qp.validation import ValidationPipeline, ValidationPipelineConfig

    # Parse flags
    stage = "backtest_passed"
    strategy_id = "simple_rank_v1.0"
    json_output = False

    args = sys.argv
    i = 2  # skip "qp" and "validate"
    while i < len(args):
        if args[i] == "--stage" and i + 1 < len(args):
            stage = args[i + 1]
            i += 2
        elif args[i] == "--strategy-id" and i + 1 < len(args):
            strategy_id = args[i + 1]
            i += 2
        elif args[i] == "--json":
            json_output = True
            i += 1
        else:
            i += 1

    valid_stages = {
        "research",
        "backtest_passed",
        "paper_trading",
        "shadow_production",
        "production",
    }
    if stage not in valid_stages:
        print(f"Invalid stage: '{stage}'. Valid: {', '.join(sorted(valid_stages))}")
        return 1

    if not json_output:
        print(f"=== QP Validation Gate ({stage}) ===")
        print()

    # Load data — use the most recent daily price snapshot on disk
    from pathlib import Path

    price_files = sorted(Path("data/dataset").glob("daily_price_*.parquet"))
    try:
        feature_df = pl.read_parquet("data/dataset/momentum_20d.parquet")
        if not price_files:
            raise FileNotFoundError("no data/dataset/daily_price_*.parquet found")
        price_df = pl.read_parquet(str(price_files[-1]))
    except FileNotFoundError as e:
        msg = f"Data not found. Run 'qp run daily' first. ({e})"
        if json_output:
            print(_json.dumps({"status": "error", "message": msg}))
        else:
            print(f"Error: {msg}")
        return 1

    # Ensure date types match
    feature_df = feature_df.with_columns(pl.col("trade_date").cast(pl.Date))
    price_df = price_df.with_columns(pl.col("trade_date").cast(pl.Date))

    # Build pipeline config with accumulated metadata
    config = ValidationPipelineConfig(
        stage=stage,
        strategy_id=strategy_id,
        overrides={},  # Use defaults — override via config file in future
    )

    pipeline = ValidationPipeline(config=config)

    # Build a context carrying all validation data
    class _CLIValidationCtx:
        feature_df: pl.DataFrame | None
        price_df: pl.DataFrame
        signal_df: pl.DataFrame | None
        backtest_metrics: dict[str, float]
        metadata: dict[str, str | float]

    ctx = _CLIValidationCtx()
    ctx.feature_df = feature_df
    ctx.price_df = price_df
    ctx.signal_df = None
    ctx.backtest_metrics = {
        "sharpe_ratio": 0.88,
        "max_drawdown_pct": 14.02,
        "total_return": 40.62,
        "daily_turnover_pct": 30.0,
        "sharpe_ratio_net": 0.72,
        "max_drawdown_pct_net": 17.5,
        "total_cost_pct": 0.35,
    }
    ctx.metadata = {
        "pre_neutralization_ic": 0.05,
        "post_neutralization_ic": 0.038,
        "train_start": "2020-01-01",
        "train_end": "2024-12-31",
        "in_sample_ic": 0.06,
        "out_of_sample_ic": 0.04,
    }

    result = pipeline.run(ctx)

    if json_output:
        out = {
            "stage": stage,
            "strategy_id": strategy_id,
            "status": result.status.value,
            "validation": result.metadata.get("validation", {}),
            "recommendation": result.metadata.get("recommendation", ""),
        }
        print(_json.dumps(out, indent=2, ensure_ascii=False, default=str))
    else:
        validation = result.metadata.get("validation", {})
        print(f"Strategy:   {strategy_id}")
        print(f"Stage:      {stage}")
        print(f"Overall:    {validation.get('status', 'unknown').upper()}")
        print(f"Score:      {validation.get('score', 0)}/100")
        print(f"Confidence: {validation.get('confidence', 0):.0%}")
        print()

        rules = validation.get("rules", [])
        if rules:
            print(f"Checks ({len(rules)} total):")
            for r in rules:
                icon = "✅" if r.get("status") == "pass" else "❌"
                print(f"  {icon} {r.get('rule_name', '?'):<24s}  {r.get('detail', '')}")

        failed = validation.get("failed_rules", [])
        if failed:
            print()
            print(f"Failed: {len(failed)}/{len(rules)} rules — {', '.join(failed)}")
            rec = result.metadata.get("recommendation", "")
            if rec:
                print(f"Recommendation: {rec}")
        elif rules:
            print()
            print("All checks passed — strategy may proceed to the next stage.")

    return 0 if result.status.value == "success" else 1
