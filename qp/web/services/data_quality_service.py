"""DataQualityService — read-only access to dataset and data source health.

Bridges the QP Data layer (Layer 2) to the Web layer.
Provides metrics about data freshness, stock counts, row counts,
and data source health.
"""

from __future__ import annotations

import contextlib
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl
from loguru import logger


class DataQualityService:
    """Read-only service for data quality and freshness metrics.

    Usage:
        svc = DataQualityService()
        summary = svc.today_summary()
        sources = svc.source_health()
    """

    def __init__(self) -> None:
        self._registry_path = Path("data/dataset/registry.json")
        self._dataset_dir = Path("data/dataset")
        self._sources_path = Path("data/metadata/sources.json")

    # ------------------------------------------------------------------
    # Today's Data Summary
    # ------------------------------------------------------------------

    def today_summary(self) -> dict[str, Any]:
        """Get data quality summary for today.

        Returns:
            Dict with today's datasets, stock counts, row counts, freshness.
        """
        today_str = date.today().isoformat()

        # 1. Read registry for today's entries
        registry_entries = self._read_registry()

        today_entries: list[dict[str, Any]] = []
        total_stocks = 0
        total_rows = 0
        datasets_today = 0

        for key, entry in registry_entries.items():
            version = entry.get("version", "")
            registered = entry.get("registered_at", "")
            # Check if this entry is for today
            is_today = version == today_str or today_str in registered
            if is_today:
                meta = entry.get("metadata", {})
                n_stocks = meta.get("stocks", 0)
                n_rows = meta.get("rows", 0)
                today_entries.append(
                    {
                        "name": entry.get("name", key),
                        "version": version,
                        "path": entry.get("path", ""),
                        "stocks": n_stocks,
                        "rows": n_rows,
                        "start_date": meta.get("start_date", ""),
                        "end_date": meta.get("end_date", ""),
                        "source": meta.get("source", ""),
                    }
                )
                total_stocks = max(total_stocks, n_stocks)  # take max across datasets
                total_rows += n_rows
                datasets_today += 1

        # 2. Scan the latest daily_price parquet for today & full stats
        latest_parquet = self._dataset_dir / "daily_price_latest.parquet"
        if not latest_parquet.exists():
            latest_parquet = self._find_latest_parquet("daily_price")  # fallback to old files
        today_stocks = 0
        today_rows = 0
        main_stocks = 0
        main_rows = 0
        daily_end_date = ""

        if latest_parquet:
            try:
                df = pl.read_parquet(str(latest_parquet))
                main_rows = df.height
                if "symbol" in df.columns:
                    main_stocks = df["symbol"].n_unique()
                # Find latest trade_date
                if "trade_date" in df.columns:
                    dates = (
                        df.select(pl.col("trade_date").cast(pl.Utf8)).unique().sort("trade_date")
                    )
                    daily_end_date = str(dates.tail(1).item() if not dates.is_empty() else "")
                    # Today's rows: count rows matching latest trade_date
                    today_df = df.filter(pl.col("trade_date").cast(pl.Utf8) == daily_end_date)
                    today_rows = today_df.height
                    if "symbol" in today_df.columns:
                        today_stocks = today_df["symbol"].n_unique()
            except Exception as e:
                logger.warning("Failed to read daily_price parquet: {}", e)

        # 3. Quality report (for validation checks)
        qr: Any = None
        report_path = Path("data/reports") / f"data_quality_{today_str}.json"
        if report_path.exists():
            with contextlib.suppress(Exception):
                qr = json.loads(report_path.read_text(encoding="utf-8"))

        # 4. Fallback: if no today data from parquet, try report
        if today_rows == 0 and qr:
            today_rows = qr.get("new_rows", 0)
            today_stocks = qr.get("symbols", main_stocks)

        # 4. Freshness: how recent is the data (trading-day aware)
        freshness_status = "fresh"
        freshness_label = "数据新鲜"
        if daily_end_date:
            try:
                end_dt = datetime.strptime(daily_end_date, "%Y-%m-%d").date()
                trading_days_old = self._trading_days_old(end_dt, date.today())
                if trading_days_old == 0:
                    freshness_status = "fresh"
                    freshness_label = f"今日已更新 ({daily_end_date})"
                elif trading_days_old == 1:
                    freshness_status = "stale"
                    freshness_label = f"最近交易日: {daily_end_date} (1个交易日前)"
                elif trading_days_old <= 3:
                    freshness_status = "stale"
                    freshness_label = f"最近交易日: {daily_end_date} ({trading_days_old}个交易日前)"
                else:
                    freshness_status = "outdated"
                    freshness_label = f"数据滞后 ({daily_end_date}, {trading_days_old}个交易日前)"
            except ValueError:
                freshness_status = "unknown"
                freshness_label = f"最新: {daily_end_date}"

        # 5. Validation checks from quality report (already loaded above)
        quality_checks: dict[str, str] = qr.get("checks", {}) if qr else {}

        # Read registry for hash and status
        data_hash = ""
        pipeline_run_id = ""
        registry_entries = self._read_registry()
        dp_entry = registry_entries.get("daily_price@latest", {})
        if dp_entry:
            meta = dp_entry.get("metadata", {})
            data_hash = meta.get("sha256", "")[:8]
            pipeline_run_id = meta.get("pipeline_run_id", "")[:8]

        return {
            "today": today_str,
            "datasets_today": datasets_today,
            "daily_stocks": today_stocks,
            "daily_rows": today_rows,
            "daily_rows_fmt": f"{today_rows:,}",
            "main_stocks": main_stocks,
            "main_rows": main_rows,
            "main_rows_fmt": f"{main_rows:,}",
            "daily_end_date": daily_end_date,
            "freshness_status": freshness_status,
            "freshness_label": freshness_label,
            "today_entries": today_entries,
            "quality_checks": quality_checks,
            "data_hash": data_hash,
            "pipeline_run_id": pipeline_run_id,
            "all_checks_pass": all(v == "pass" for v in quality_checks.values())
            if quality_checks
            else False,
        }

    # ------------------------------------------------------------------
    # Source Health
    # ------------------------------------------------------------------

    def source_health(self) -> list[dict[str, Any]]:
        """Get health status for all data sources.

        Checks ``data/metadata/sources.json`` first; falls back to health
        inferred from the dataset registry's source metadata.
        """
        if self._sources_path.exists():
            try:
                data = json.loads(self._sources_path.read_text(encoding="utf-8"))
                file_sources = data.get("sources", [])
                if file_sources:
                    return self._format_sources(file_sources)
            except Exception:
                pass

        # Fallback: infer health from dataset registry
        return self._inferred_source_health()

    def _format_sources(self, raw_sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Format raw source dicts from sources.json."""
        result = []
        for s in raw_sources:
            status = s.get("health_status", "healthy")
            result.append(
                {
                    "source_name": s.get("source_name", ""),
                    "description": s.get("description", ""),
                    "data_kind": s.get("data_kind", ""),
                    "health_status": status,
                    "status_label": _health_label(status),
                    "last_success": _format_time(s.get("last_fetch_success", "")),
                    "last_attempt": _format_time(s.get("last_fetch_attempt", "")),
                    "consecutive_failures": s.get("consecutive_failures", 0),
                    "fetch_error_count": s.get("fetch_error_count", 0),
                    "avg_latency": s.get("avg_latency_seconds", 0.0),
                    "health_notes": s.get("health_notes", ""),
                    "icon": _health_icon(status),
                    "badge_class": _health_badge(status),
                }
            )
        return result

    def _inferred_source_health(self) -> list[dict[str, Any]]:
        """Infer source health from the dataset registry.

        Builds the source list from each dataset's current (newest-version)
        ``metadata.source`` field instead of a hardcoded sina+tencent pair.
        Stale dataset versions do not count — e.g. ``daily_price_main``
        migrated from ``quant_trading_db`` to ``akshare``, so only akshare
        is shown. Demo entries (``source == "demo"``) are excluded.

        Status is NOT a live health probe — it is inferred from registry
        freshness. A source whose newest dataset was registered recently is
        marked healthy; older registrations are marked degraded with the
        data date shown, never a fabricated "normal".
        """
        registry = self._read_registry()
        # Per dataset name, keep the source + registered_at of the newest version.
        # "latest" beats any dated version; dated versions compare by ISO string.
        newest_source: dict[str, str] = {}
        newest_version: dict[str, str] = {}
        newest_registered: dict[str, str] = {}
        for entry in registry.values():
            name = entry.get("name", "")
            version = entry.get("version", "")
            src = entry.get("metadata", {}).get("source", "")
            if not name or not src or src == "demo":
                continue
            if name not in newest_version:
                newest_source[name] = src
                newest_version[name] = version
                newest_registered[name] = entry.get("registered_at", "")
            else:
                old = newest_version[name]
                if version == "latest" or (old != "latest" and version > old):
                    newest_source[name] = src
                    newest_version[name] = version
                    newest_registered[name] = entry.get("registered_at", "")

        # source -> (description, data_kind, last_registered_at)
        seen: dict[str, tuple[str, str, str]] = {}
        for name, src in newest_source.items():
            if src not in seen:
                desc, kind = _SOURCE_INFO.get(src, ("外部数据源", "unknown"))
                seen[src] = (desc, kind, newest_registered.get(name, ""))
        if not seen:
            return []
        result = []
        for src, (desc, kind, last_registered) in seen.items():
            status, notes = _infer_source_status(last_registered, kind)
            result.append(
                {
                    "source_name": src,
                    "description": desc,
                    "data_kind": kind,
                    "health_status": status,
                    "status_label": _health_label(status),
                    "last_success": _format_time(last_registered),
                    "last_attempt": "",
                    "consecutive_failures": 0,
                    "fetch_error_count": 0,
                    "avg_latency": 0.0,
                    "health_notes": notes,
                    "icon": _health_icon(status),
                    "badge_class": _health_badge(status),
                }
            )
        return result

    # ------------------------------------------------------------------
    # Dataset inventory
    # ------------------------------------------------------------------

    def dataset_inventory(self) -> list[dict[str, Any]]:
        """Get all datasets from the registry with basic info."""
        entries = self._read_registry()
        result = []
        for key, entry in entries.items():
            meta = entry.get("metadata", {})
            result.append(
                {
                    "key": key,
                    "name": entry.get("name", ""),
                    "version": entry.get("version", ""),
                    "stocks": meta.get("stocks", 0),
                    "rows": meta.get("rows", 0),
                    "start_date": meta.get("start_date", ""),
                    "end_date": meta.get("end_date", ""),
                    "registered_at": _format_time(entry.get("registered_at", "")),
                }
            )
        # Sort by version descending
        result.sort(key=lambda x: x["version"], reverse=True)
        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _read_registry(self) -> dict[str, Any]:
        """Read the dataset registry JSON."""
        if not self._registry_path.exists():
            return {}
        try:
            data = json.loads(self._registry_path.read_text(encoding="utf-8"))
            return data.get("entries", {})
        except Exception as e:
            logger.warning("Failed to read dataset registry: {}", e)
            return {}

    def _find_latest_parquet(self, prefix: str) -> Path | None:
        """Find the latest parquet file matching a prefix in dataset dir.

        Uses strict pattern matching: ``{prefix}_[0-9]*.parquet`` to avoid
        matching files like ``daily_price_main_*.parquet`` when prefix is
        ``daily_price``.
        """
        if not self._dataset_dir.exists():
            return None
        candidates = sorted(
            self._dataset_dir.glob(f"{prefix}_[0-9]*.parquet"),
            reverse=True,
        )
        return candidates[0] if candidates else None

    @staticmethod
    def _trading_days_old(data_date: date, today: date) -> int:
        """Count trading days (Mon-Fri) between data_date and today.

        On Monday, data from Friday is 1 trading day old, not 3 calendar days.
        A value of 0 means today's data is available; 1 means yesterday's data.
        """
        if data_date >= today:
            return 0
        days = 0
        d = data_date + timedelta(days=1)
        while d <= today:
            if d.weekday() < 5:  # Mon-Fri
                days += 1
            d += timedelta(days=1)
        return days


# ------------------------------------------------------------------
# Display helpers
# ------------------------------------------------------------------

# Known data source labels: source -> (description, data_kind).
# Unknown sources fall back to ("外部数据源", "unknown").
_SOURCE_INFO: dict[str, tuple[str, str]] = {
    "tencent": ("腾讯财经 API — 日线行情", "daily_ohlcv"),
    "sina": ("新浪财经 API — 资金流", "capital_flow"),
    "akshare": ("AKShare 开放数据接口", "multi"),
    "eastmoney": ("东方财富 API", "multi"),
    "quant_trading_db": ("QuantTrading 旧库导出", "multi"),
}

# Freshness threshold (days) per data_kind. A dataset registered more than
# this many days ago means the source is not being updated → degraded, not
# a fabricated "normal". daily data goes stale fast; batch data has slack.
_FRESHNESS_DAYS: dict[str, int] = {
    "daily_ohlcv": 3,
    "capital_flow": 3,
    "multi": 30,
}
_DEFAULT_FRESHNESS_DAYS = 30


def _infer_source_status(last_registered: str, data_kind: str) -> tuple[str, str]:
    """Infer source status from the newest dataset's registration time.

    Returns (status, notes). Status is one of healthy/degraded/unknown.
    No registered_at → unknown (nothing measured, never "normal").
    """
    if not last_registered:
        return "unknown", "未检测到注册时间"
    try:
        dt = datetime.fromisoformat(last_registered.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return "unknown", f"注册时间无法解析: {last_registered}"

    age_days = (datetime.now(UTC) - dt).total_seconds() / 86400
    threshold = _FRESHNESS_DAYS.get(data_kind, _DEFAULT_FRESHNESS_DAYS)
    if age_days <= threshold:
        return "healthy", f"数据截至 {dt.strftime('%Y-%m-%d')}"
    return (
        "degraded",
        f"数据截至 {dt.strftime('%Y-%m-%d')}，{int(age_days)} 天未更新（阈值 {threshold} 天）",
    )


def _health_label(status: str) -> str:
    labels = {
        "healthy": "正常 / Healthy",
        "degraded": "降级 / Degraded",
        "unhealthy": "异常 / Unhealthy",
        "unknown": "未知 / Unknown",
    }
    return labels.get(status, status)


def _health_icon(status: str) -> str:
    icons = {
        "healthy": "🟢",
        "degraded": "🟡",
        "unhealthy": "🔴",
        "unknown": "⚪",
    }
    return icons.get(status, "⚪")


def _health_badge(status: str) -> str:
    badges = {
        "healthy": "badge-green",
        "degraded": "badge-yellow",
        "unhealthy": "badge-red",
        "unknown": "badge-gray",
    }
    return badges.get(status, "badge-gray")


def _format_time(iso_str: str) -> str:
    """Format ISO UTC time string to short local-ish display."""
    if not iso_str:
        return ""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%m-%d %H:%M")
    except (ValueError, TypeError):
        return iso_str[:16] if len(iso_str) >= 16 else iso_str
