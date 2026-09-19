"""CLI command handlers for the "data cmd" group."""

from __future__ import annotations

import sys


def cmd_data_index() -> int:
    """Fetch benchmark index daily data (market filter + regime + benchmark NAV).

    Reports the resulting freshness so a silent stale file is visible:
    reuse only happens while the local last trade_date is recent.
    """
    from qp.data.dataset.index_provider import (
        DEFAULT_MAX_AGE_DAYS,
        INDEX_SYMBOLS,
        fetch_index_data,
        latest_local_date,
    )
    from qp.shared.time import today_cn

    args = sys.argv[3:] if len(sys.argv) > 3 else []
    force = "--force" in args
    symbol = "sh000300"
    for arg in args:
        if arg.startswith("--symbol="):
            symbol = arg.split("=", 1)[1]

    try:
        path = fetch_index_data(force=force, symbol=symbol)
    except Exception as exc:
        print(f"Index fetch failed: {exc}")
        return 1

    print(f"Index data written: {path}")
    print(f"  latest trade_date: {latest_local_date(path)}")

    # Freshness of both index files, so a consumer of a stale series is visible.
    print("  freshness:")
    for sym, fname in INDEX_SYMBOLS.items():
        latest = latest_local_date(path.parent / fname)
        if latest is None:
            print(f"    {sym}: missing / unreadable")
            continue
        age = (today_cn() - latest).days
        mark = "OK" if age <= DEFAULT_MAX_AGE_DAYS else "STALE"
        print(f"    {sym}: {latest} ({age}d, {mark})")
    return 0


def cmd_data_fetch() -> int:
    """Fetch full main-board data through complete Data Layer pipeline."""
    from qp.data.loader.full_pipeline import FullDataPipeline
    from qp.platform.pipeline.context import PipelineContext

    params: dict[str, object] = {}
    args = sys.argv[3:] if len(sys.argv) > 3 else []
    i = 0
    while i < len(args):
        arg = args[i]
        if arg.startswith("--batch="):
            params["batch_size"] = int(arg.split("=", 1)[1])
        elif arg == "--skip-etl":
            params["skip_etl"] = True
        elif arg.startswith("--start="):
            params["start_date"] = arg.split("=", 1)[1]
        elif arg == "--start" and i + 1 < len(args):
            i += 1
            params["start_date"] = args[i]
        elif arg.startswith("--end="):
            params["end_date"] = arg.split("=", 1)[1]
        elif arg == "--end" and i + 1 < len(args):
            i += 1
            params["end_date"] = args[i]
        i += 1

    print("═══ QP Data Fetch ═══")
    context = PipelineContext(pipeline_name="full_data_ingest", parameters=params)
    pipeline = FullDataPipeline()
    result = pipeline.run(context)

    print(f"\nStatus: {result.status.value}")
    if result.artifacts:
        for a in result.artifacts:
            print(f"Output:  {a}")
    if result.metrics:
        n_stocks = result.metrics.get("n_stocks", 0)
        n_rows = result.metrics.get("n_rows", 0)
        print(f"Stocks:  {n_stocks:.0f}")
        print(f"Rows:    {n_rows:.0f}")
        for tier in ["raw", "bronze", "silver", "gold"]:
            mb = result.metrics.get(f"{tier}_mb", 0)
            if mb:
                print(f"  {tier.capitalize()}: {mb:.0f} MB")
    return 0 if result.status.value == "success" else 1
