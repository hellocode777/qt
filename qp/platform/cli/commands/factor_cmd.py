"""CLI command handlers for the "factor" group.

Usage:
    qp factor list                 List all factors with lifecycle
    qp factor health [name]        Show factor health status
    qp factor report [name]        Generate factor research report
    qp factor validate <name>      Run validation gate on a single factor
    qp factor update-health        Recompute full-history health for all factors
    qp factor catalog              Show factor catalog by category
    qp factor compute              Compute daily factor values → factor_values_daily.parquet
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import polars as pl


def cmd_factor_list() -> int:
    """List all tracked factors with lifecycle and key metrics."""
    try:
        from qp.monitoring.factor_health_logger import FactorHealthLogger
    except ImportError as e:
        print(f"Error: {e}")
        return 1

    logger = FactorHealthLogger()
    latest = logger.load_all_latest()

    if not latest:
        print("No factor health data found. Run an experiment first.")
        print("  qp experiment run multifactor --skip-gate")
        return 0

    print(f"{'Factor':30s} {'Stage':14s} {'IC_30d':>8s} {'IC_IR':>6s} {'N_days':>6s}")
    print("-" * 70)

    stage_order = {
        "production": 0,
        "weakening": 1,
        "validated": 2,
        "research": 3,
        "degraded": 4,
        "retired": 5,
        "archived": 6,
    }

    items = sorted(
        latest.items(),
        key=lambda x: (stage_order.get(x[1].get("stage", ""), 99), -abs(x[1].get("ic_30d", 0))),
    )

    icons = {
        "production": "🚀",
        "weakening": "🟠",
        "validated": "✅",
        "research": "🔬",
        "degraded": "🔴",
        "retired": "💀",
        "archived": "📦",
    }

    for name, record in items:
        stage = record.get("stage", "research")
        icon = icons.get(stage, "❓")
        ic_30d = record.get("ic_30d", 0.0)
        ic_ir = record.get("ic_ir", 0.0)
        n_days = record.get("n_days", 0)
        print(f"{icon} {name:28s} {stage:14s} {ic_30d:>+8.4f} {ic_ir:>6.2f} {n_days:>6d}")

    # Summary
    from collections import Counter

    stage_counts = Counter(r.get("stage", "research") for r in latest.values())
    print()
    print(f"Total: {len(latest)} factors")
    for s in ["production", "weakening", "validated", "research", "degraded", "retired"]:
        n = stage_counts.get(s, 0)
        if n:
            print(f"  {icons.get(s, '❓')} {s}: {n}")

    return 0


def cmd_factor_health(factor_name: str = "") -> int:
    """Show detailed factor health for one factor or overview for all."""
    try:
        from qp.web.services.factor_health_service import FactorHealthService
    except ImportError as e:
        print(f"Error: {e}")
        return 1

    svc = FactorHealthService()

    if factor_name:
        detail = svc.factor_detail(factor_name)
        if detail.get("is_empty"):
            print(f"No health data for factor: {factor_name}")
            return 1

        print(f"=== {factor_name} ===")
        print(f"  Lifecycle:  {detail['icon']} {detail['stage_label']} ({detail['stage']})")
        print(f"  IC Mean:    {detail['ic_mean']:+.4f}")
        print(f"  IC 30d:     {detail['ic_30d']:+.4f}")
        print(f"  IC 90d:     {detail['ic_90d']:+.4f}")
        print(f"  IC IR:      {detail['ic_ir']:.2f}")
        print(f"  Decay Rate: {detail['ic_decay_rate']:+.6f}/day")
        print(f"  IC>0%:      {detail['ic_positive_pct']:.1f}%")
        print(f"  N Days:     {detail['n_days']}")
        action = detail.get("recommended_action", "")
        if action:
            print(f"  Action:     {action}")
        summary = detail.get("summary", "")
        if summary:
            print(f"  Summary:    {summary}")
    else:
        overview = svc.overview()
        if overview.get("is_empty"):
            print("No factor health data found.")
            return 0

        print("=== Factor Health Overview ===")
        print(f"  Factors:    {overview['n_factors']}")
        for stage, label in [
            ("production", "🚀 Production"),
            ("weakening", "🟠 Weakening"),
            ("validated", "✅ Validated"),
            ("research", "🔬 Research"),
            ("degraded", "🔴 Degraded"),
            ("retired", "💀 Retired"),
        ]:
            n = overview["counts"].get(stage, 0)
            if n:
                print(f"  {label}:  {n}")

        # Recommendations
        recs = overview.get("recommendations", [])
        if recs:
            print()
            print("=== Recommendations ===")
            for r in recs[:10]:
                print(f"  [{r['severity']}] {r['message']}")

    return 0


def cmd_factor_report(factor_name: str = "") -> int:
    """Generate a markdown factor research report."""
    try:
        from qp.monitoring.factor_report import FactorReportGenerator
    except ImportError as e:
        print(f"Error: {e}")
        return 1

    gen = FactorReportGenerator()

    if factor_name:
        report = gen.generate_single(factor_name)
        if report is None:
            print(f"No data available for factor: {factor_name}")
            return 1
        path = gen.save_report(report, factor_name)
        print(f"Report saved: {path}")
        print()
        print(report[:2000])
    else:
        # Overview report
        report = gen.generate_overview()
        if report is None:
            print("No factor data available. Run an experiment first.")
            return 1
        path = gen.save_report(report, "overview")
        print(f"Report saved: {path}")
        print()
        print(report[:2000])

    return 0


def _load_full_price() -> pl.DataFrame | None:
    """Load the full daily price dataset (prefers the latest snapshot).

    Priority: daily_price_latest.parquet (registered @latest) over dated
    main snapshots — previously the glob picked the lexicographically last
    file (e.g. daily_price_main_2026-08-14.parquet), silently serving stale
    data to update-health after a newer latest file appeared.
    """
    import polars as pl

    latest = Path("data/dataset/daily_price_latest.parquet")
    if latest.exists():
        return pl.read_parquet(latest)

    price_files = sorted(Path("data/dataset").glob("daily_price_*.parquet"))
    if not price_files:
        return None
    return pl.read_parquet(str(price_files[-1]))


def _compute_factor_scores(
    factor_name: str,
    price_df: pl.DataFrame,
) -> pl.DataFrame | None:
    """Build factor score DataFrame from full price history."""
    import polars as pl

    from qp.research.factor_calculator import _build_index_proxy
    from qp.research.feature.compute import compute_all_factors

    # Residual_Momentum_3M requires a market index (beta adjustment).
    # FactorCalculator builds a proxy automatically; mirror that here so
    # update-health computes the factor instead of skipping it.
    index_df = _build_index_proxy(price_df) if factor_name == "Residual_Momentum_3M" else None

    rows: list[dict] = []
    symbols = price_df["symbol"].unique().to_list()
    for i, symbol in enumerate(symbols):
        stock_df = price_df.filter(pl.col("symbol") == symbol).sort("trade_date")
        if stock_df.height < 60:
            continue
        try:
            factors = compute_all_factors(
                stock_df,
                subset=[factor_name],
                index_df=index_df,
            )
            if factors.is_empty():
                continue
            for row in factors.iter_rows(named=True):
                if factor_name in row:
                    val = row[factor_name]
                    if val is not None and val == val:
                        rows.append(
                            {
                                "trade_date": str(row["trade_date"]),
                                "symbol": symbol,
                                "score": float(val),
                            }
                        )
        except Exception:
            continue
        if (i + 1) % 500 == 0:
            print(f"  ... {i + 1}/{len(symbols)} stocks")

    if len(rows) < 100:
        return None
    return pl.DataFrame(
        rows,
        schema={"trade_date": pl.Utf8, "symbol": pl.Utf8, "score": pl.Float64},
    )


def cmd_factor_validate(
    factor_name: str = "",
    persist: bool = False,
) -> int:
    """Run validation gate checks on a single factor.

    Computes IC, IC_IR, t-stat against the FULL daily price dataset
    (2015-present, ~2700 trading days).

    Usage:
        qp factor validate Momentum_3M
        qp factor validate Momentum_3M --persist   # also save to factor_health.parquet
    """
    if not factor_name:
        print("Usage: qp factor validate <factor_name> [--persist]")
        return 1

    try:
        from qp.research.evaluation.rank_ic import compute_daily_ic_series, evaluate_factor_ic
        from qp.research.feature.compute import ALL_FACTOR_DIRECTIONS
    except ImportError as e:
        print(f"Error: {e}")
        return 1

    if factor_name not in ALL_FACTOR_DIRECTIONS:
        known_valuation = {"PE_TTM", "PB", "PCF_OCF", "Dividend_Yield", "PS_TTM"}
        known_fundamental = {
            "ROE",
            "revenue_growth",
            "net_profit_growth",
            "gross_margin",
            "net_margin",
            "debt_ratio",
            "EPS",
            "NAV",
            "ROE_Level",
            "Profit_Stability",
            "Earnings_Quality",
            "Margin_Composite",
        }
        if factor_name not in known_valuation and factor_name not in known_fundamental:
            print(f"Unknown factor: {factor_name}")
            return 1

    print(f"=== Factor Validation: {factor_name} ===")
    if persist:
        print("   (--persist: results will be saved to factor_health.parquet)")
    print()

    expected_direction = ALL_FACTOR_DIRECTIONS.get(factor_name, 1)
    print(f"  Expected direction: {'+1' if expected_direction > 0 else '-1'}")

    price_df = _load_full_price()
    if price_df is None:
        print("Error: No price dataset found.")
        return 1

    print(
        f"  Data source: full daily price ({price_df['trade_date'].min()} ~ {price_df['trade_date'].max()})"
    )
    print(f"  Stocks:      {price_df['symbol'].n_unique()}")
    print()
    print("Computing cross-sectional Rank IC (full history)...")

    score_df = _compute_factor_scores(factor_name, price_df)
    if score_df is None:
        print("  Insufficient data")
        return 1

    ic_result = evaluate_factor_ic(score_df, price_df, forward_days=5, min_stocks_per_day=10)

    print()
    print(f"  {'IC Mean':20s} {ic_result.ic_mean:+.4f}")
    print(f"  {'IC IR':20s} {ic_result.ic_ir:.2f}")
    print(f"  {'IC t-stat':20s} {ic_result.ic_t_stat:.2f}")
    print(f"  {'IC Std':20s} {ic_result.ic_std:.4f}")
    print(f"  {'IC>0%':20s} {ic_result.ic_positive_pct:.1f}%")
    print(f"  {'N Days':20s} {ic_result.n_days}")
    print()

    checks = [
        ("Rank IC ≥ 0.02", abs(ic_result.ic_mean) >= 0.02, f"{abs(ic_result.ic_mean):.4f}"),
        ("IC IR ≥ 0.30", ic_result.ic_ir >= 0.30, f"{ic_result.ic_ir:.2f}"),
        ("IC t-stat ≥ 2.0", ic_result.ic_t_stat >= 2.0, f"{ic_result.ic_t_stat:.2f}"),
        ("IC>0% ≥ 50%", ic_result.ic_positive_pct >= 50.0, f"{ic_result.ic_positive_pct:.1f}%"),
        (
            "Direction match",
            (ic_result.ic_mean * expected_direction) > 0,
            "matches" if (ic_result.ic_mean * expected_direction) > 0 else "REVERSED",
        ),
    ]

    passed = sum(1 for _, ok, _ in checks if ok)
    for name, ok, val in checks:
        print(f"  {'✅' if ok else '❌'} {name:20s} {val}")

    print()
    print(f"  Passed: {passed}/{len(checks)} checks")
    if passed == len(checks):
        print("  ✅ Factor passes all basic gates — eligible for VALIDATED stage")
    elif passed >= 3:
        print("  ⚠️ Factor needs improvement — keep in RESEARCH stage")
    else:
        print("  ❌ Factor fails critical gates — consider redesign or retirement")

    # ── Persist to factor_health.parquet ──
    if persist:
        print()
        print("Persisting full-history health data...")
        try:
            from datetime import UTC, datetime

            from qp.monitoring.factor_health import FactorHealthMonitor
            from qp.monitoring.factor_health_logger import FactorHealthLogger

            monitor = FactorHealthMonitor()
            health_logger = FactorHealthLogger()
            today_str = datetime.now(UTC).strftime("%Y-%m-%d")

            status = monitor.check_factor(factor_name, ic_result.daily_ics)
            health_logger.log(status, date_str=today_str)
            daily_records = compute_daily_ic_series(
                score_df, price_df, forward_days=5, min_stocks_per_day=10
            )
            health_logger.save_daily_ic_series(factor_name, daily_records)
            print(
                f"  ✅ Written to factor_health.parquet (stage={status.lifecycle.value}, n_days={ic_result.n_days})"
            )
        except Exception as e:
            print(f"  ⚠️ Failed to persist: {e}")

    return 0 if passed == len(checks) else 1


def cmd_factor_update_health() -> int:
    """Recompute full-history factor health for ALL price/volume factors.

    This is the production way to populate factor_health.parquet with
    complete historical data.  Runs ~2 min per factor × 15 factors.

    Usage:
        qp factor update-health
    """
    from qp.research.feature.compute import PRICE_VOLUME_FACTORS

    price_df = _load_full_price()
    if price_df is None:
        print("Error: No price dataset found.")
        return 1

    print("=== Full-History Factor Health Update ===")
    print(f"  Dataset: {price_df['trade_date'].min()} ~ {price_df['trade_date'].max()}")
    print(f"  Stocks:  {price_df['symbol'].n_unique()}")
    print(f"  Factors to update: {len(PRICE_VOLUME_FACTORS)}")
    print()

    try:
        from datetime import UTC, datetime

        from qp.monitoring.factor_health import FactorHealthMonitor
        from qp.monitoring.factor_health_logger import FactorHealthLogger
        from qp.research.evaluation.rank_ic import compute_daily_ic_series, evaluate_factor_ic

        monitor = FactorHealthMonitor()
        health_logger = FactorHealthLogger()
        today_str = datetime.now(UTC).strftime("%Y-%m-%d")

        ok_count = 0
        skip_count = 0

        for idx, fname in enumerate(PRICE_VOLUME_FACTORS):
            print(f"[{idx + 1}/{len(PRICE_VOLUME_FACTORS)}] {fname} ...", end=" ", flush=True)

            score_df = _compute_factor_scores(fname, price_df)
            if score_df is None:
                print("SKIP (insufficient data)")
                skip_count += 1
                continue

            ic_result = evaluate_factor_ic(
                score_df, price_df, forward_days=5, min_stocks_per_day=10
            )
            if ic_result.n_days < 10:
                print("SKIP (< 10 IC days)")
                skip_count += 1
                continue

            status = monitor.check_factor(fname, ic_result.daily_ics)
            health_logger.log(status, date_str=today_str)
            daily_records = compute_daily_ic_series(
                score_df, price_df, forward_days=5, min_stocks_per_day=10
            )
            health_logger.save_daily_ic_series(fname, daily_records)
            print(
                f"OK (IC={ic_result.ic_mean:+.4f} IR={ic_result.ic_ir:.2f} {status.lifecycle.value})"
            )
            ok_count += 1

        print()
        print(
            f"Done: {ok_count} updated, {skip_count} skipped → factor_health.parquet + factor_ic_series.parquet"
        )
        print(
            f"WebUI will now show full-history data ({price_df['trade_date'].min()} ~ {price_df['trade_date'].max()})."
        )
    except Exception as e:
        print(f"Error: {e}")
        return 1

    return 0


def cmd_factor_register(force: bool = False) -> int:
    """Register all BaseFeature classes from qp/research/feature into the
    persisted FeatureRegistry (data/factor_registry.json).

    Direction is overridden from ALL_FACTOR_DIRECTIONS where available —
    production factor classes default to +1, but momentum/volume factors
    are used with direction=-1 (mean-reversion semantics).

    Args:
        force: Re-register even if a registry file already exists.

    Returns:
        0 on success, 1 on error.
    """
    import os

    from qp.research.feature.compute import ALL_FACTOR_DIRECTIONS
    from qp.research.feature.registry import FeatureRegistry

    registry_path = "data/factor_registry.json"
    if os.path.exists(registry_path) and not force:
        print(f"因子注册表已存在: {registry_path}（共 {_count_registered(registry_path)} 个因子）")
        print("如需重新注册: qp factor register --force")
        return 0

    registry = FeatureRegistry()
    classes = registry.scan_feature_classes()
    print(f"扫描到 {len(classes)} 个 BaseFeature 子类")

    registered = registry.auto_register_all(classes)
    print(f"注册 {len(registered)} 个因子")

    # 应用方向覆盖（ALL_FACTOR_DIRECTIONS 是权威方向源）
    overridden = sum(
        1
        for name in registry._features
        if name in ALL_FACTOR_DIRECTIONS
        and ALL_FACTOR_DIRECTIONS[name] != registry._features[name].direction
    )
    if overridden:
        print(f"方向覆盖 {overridden} 个（ALL_FACTOR_DIRECTIONS）")

    registry.save(registry_path, direction_overrides=ALL_FACTOR_DIRECTIONS)
    print()
    # 重新加载以显示覆盖后的方向（类默认 direction 不反映 ALL_FACTOR_DIRECTIONS）
    loaded = FeatureRegistry.load_from_json(registry_path)
    print(loaded.catalog_summary())
    print()
    print(f"已持久化: {registry_path}")
    return 0


def _count_registered(path: str) -> int:
    """Read n_factors from an existing registry JSON without full load."""
    import json

    try:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
        return int(payload.get("n_factors", 0))
    except Exception:
        return 0


def cmd_factor_catalog() -> int:
    """Show factor catalog grouped by category."""
    import os

    registry_path = "data/factor_registry.json"
    if os.path.exists(registry_path):
        from qp.research.feature.registry import FeatureRegistry

        registry = FeatureRegistry.load_from_json(registry_path)
        print(registry.catalog_summary())
        print()
        print(f"来源: {registry_path}（注册因子，`qp factor register` 维护）")
        return 0

    try:
        from qp.research.feature.compute import (
            ALL_FACTOR_DESCRIPTIONS,
            ALL_FACTOR_DIRECTIONS,
            PRICE_VOLUME_FACTORS,
        )
    except ImportError as e:
        print(f"Error: {e}")
        return 1

    # Build catalog
    catalogs: dict[str, list[tuple[str, int, str]]] = {}
    for fname in PRICE_VOLUME_FACTORS:
        direction = ALL_FACTOR_DIRECTIONS.get(fname, 1)
        desc = ALL_FACTOR_DESCRIPTIONS.get(fname, "")

        # Infer category from name
        if "Momentum" in fname or "Reversal" in fname or "Trend" in fname:
            cat = "Momentum"
        elif "Volatility" in fname or "MaxDD" in fname or "Amplitude" in fname:
            cat = "Volatility"
        elif "Volume" in fname or "Amount" in fname or "Price_Volume" in fname:
            cat = "Volume"
        elif "Flow" in fname:
            cat = "MoneyFlow"
        else:
            cat = "Other"

        catalogs.setdefault(cat, []).append((fname, direction, desc))

    print("=== Factor Catalog ===")
    print(f"  Total price/volume factors: {len(PRICE_VOLUME_FACTORS)}")
    print()

    for cat in ["Momentum", "Volatility", "Volume", "MoneyFlow", "Other"]:
        factors = catalogs.get(cat, [])
        if not factors:
            continue
        print(f"[{cat}] ({len(factors)} factors)")
        for fname, direction, desc in sorted(factors):
            arrow = "↑" if direction > 0 else "↓"
            print(f"  {arrow} {fname:35s} {desc}")
        print()

    # Also list valuation/fundamental factors
    print("---")
    print("Valuation factors (external data): PE_TTM, PB, PCF_OCF, Dividend_Yield, PS_TTM")
    print("Fundamental factors (external data): ROE, revenue_growth, net_profit_growth,")
    print("  gross_margin, net_margin, debt_ratio, EPS, NAV, ROE_Level, Profit_Stability,")
    print("  Earnings_Quality, Margin_Composite")

    return 0


def cmd_factor_compute(
    target_date: str = "",
    full_history: bool = False,
    factor_subset: str = "",
    output_dir: str = "data/dataset",
) -> int:
    """Run daily factor computation → factor_values_daily.parquet.

    Computes all 19 price/volume factor values for all stocks using
    fixed factor formulas.  This is the Factor Execution Plane —
    factor formulas are fixed, only the latest market data is substituted.

    Usage:
        qp factor compute                          # incremental: latest date only
        qp factor compute --full                   # full history: all dates
        qp factor compute --date 2026-08-06        # specific date
        qp factor compute --subset Momentum_3M,Volatility_20D  # subset only
    """
    try:
        from qp.pipeline.factor_calc_pipeline import FactorCalcPipeline
        from qp.platform.pipeline.context import PipelineContext
    except ImportError as e:
        print(f"Error: {e}")
        return 1

    subset: list[str] | None = None
    if factor_subset:
        subset = [s.strip() for s in factor_subset.split(",") if s.strip()]

    print("=== Factor Computation (Factor Execution Plane) ===")
    if full_history:
        print("  Mode: full-history (all dates)")
    elif target_date:
        print(f"  Mode: single date ({target_date})")
    else:
        print("  Mode: incremental (latest date only)")
    if subset:
        print(f"  Factors: {len(subset)} selected ({', '.join(subset)})")
    else:
        print("  Factors: all 19 price/volume factors")
    print()

    context = PipelineContext(
        pipeline_name="factor_calc",
        parameters={
            "target_date": target_date or None,
            "full_history": full_history,
            "factor_subset": subset,
            "output_dir": output_dir,
        },
    )
    calc = FactorCalcPipeline()
    result = calc.run(context)

    if result.status.value == "success":
        print(f"  ✅ Done — {result.metrics.get('new_rows', 0)} rows")
        print(f"     Date:     {result.metadata.get('date', 'N/A')}")
        print(f"     Factors:  {result.metrics.get('n_factors', 0)}")
        if result.artifacts:
            print(f"     Output:   {result.artifacts[0]}")
        return 0
    elif result.status.value == "partial":
        print(f"  ⚠️ Partial — {result.metadata.get('warning', 'see details')}")
        return 0
    else:
        print(f"  ❌ Failed: {result.errors}")
        return 1
