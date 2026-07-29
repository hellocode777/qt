"""DataQualityService — read-only access to dataset and data source health.

Bridges the QP Data layer (Layer 2) to the Web layer.
Provides metrics about data freshness, stock counts, row counts,
and data source health.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
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
            try:
                qr = json.loads(report_path.read_text(encoding="utf-8"))
            except Exception:
                pass

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
            "all_checks_pass": all(
                v == "pass" for v in quality_checks.values()
            ) if quality_checks else False,
        }

    # ------------------------------------------------------------------
    # Source Health
    # ------------------------------------------------------------------

    def source_health(self) -> list[dict[str, Any]]:
        """Get health status for all data sources.

        Checks ``data/metadata/sources.json`` first; falls back to health
        inferred from dataset presence (Sina + Tencent).
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
        """Infer source health from dataset files when sources.json is absent."""
        registry = self._read_registry()
        has_data = len(registry) > 0
        return [
            {
                "source_name": "sina",
                "description": "新浪财经 API — 日线行情",
                "data_kind": "daily_ohlcv",
                "health_status": "healthy" if has_data else "unknown",
                "status_label": "正常" if has_data else "未检测",
                "last_success": "",
                "consecutive_failures": 0,
                "fetch_error_count": 0,
                "avg_latency": 0.0,
                "health_notes": "",
                "icon": "🟢" if has_data else "⚪",
                "badge_class": "badge-green" if has_data else "badge-gray",
            },
            {
                "source_name": "tencent",
                "description": "腾讯财经 API — 长周期历史数据",
                "data_kind": "daily_ohlcv",
                "health_status": "healthy" if has_data else "unknown",
                "status_label": "正常" if has_data else "未检测",
                "last_success": "",
                "consecutive_failures": 0,
                "fetch_error_count": 0,
                "avg_latency": 0.0,
                "health_notes": "",
                "icon": "🟢" if has_data else "⚪",
                "badge_class": "badge-green" if has_data else "badge-gray",
            },
        ]

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
