"""SourceMetadata & SourceMetadataStore — data source health tracking.

Tracks origin, access patterns, freshness, and reliability per adapter.
Answers: "How trustworthy is this data source and when was it last healthy?"

Implements dp.md §7.8: metadata/ as a dedicated directory in storage hierarchy.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loguru import logger


@dataclass
class SourceMetadata:
    """Metadata about a single data source adapter.

    Attributes:
        source_name: Adapter name (e.g. 'akshare', 'tencent', 'demo').
        description: Human-readable description.
        data_kind: What kind of data ('daily_ohlcv', 'financials', 'capital_flow').
        last_fetch_attempt: When the last fetch was attempted (ISO UTC).
        last_fetch_success: When the last successful fetch occurred (ISO UTC).
        fetch_error_count: Cumulative fetch error count.
        consecutive_failures: Consecutive failures since last success.
        avg_latency_seconds: Average fetch latency in seconds.
        health_status: 'healthy', 'degraded', or 'unhealthy'.
        health_notes: Explanatory notes about current health.
        supports_symbol_filter: Whether fetch_raw accepts symbols=.
        max_symbols: Maximum symbols supported per request (None = unlimited).
        rate_limit_rps: Rate limit in requests per second.
    """

    source_name: str
    description: str = ""
    data_kind: str = ""
    last_fetch_attempt: str = ""
    last_fetch_success: str = ""
    fetch_error_count: int = 0
    consecutive_failures: int = 0
    avg_latency_seconds: float = 0.0
    health_status: str = "healthy"
    health_notes: str = ""
    supports_symbol_filter: bool = True
    max_symbols: int | None = None
    rate_limit_rps: float = 1.0

    # ── Health state transitions ──

    def record_fetch_success(self, latency_seconds: float = 0.0) -> None:
        """Update state after a successful fetch."""
        now = datetime.now(UTC).isoformat()
        self.last_fetch_attempt = now
        self.last_fetch_success = now
        self.consecutive_failures = 0
        if self.avg_latency_seconds == 0.0:
            self.avg_latency_seconds = latency_seconds
        else:
            # Exponential moving average
            self.avg_latency_seconds = 0.8 * self.avg_latency_seconds + 0.2 * latency_seconds
        self._recompute_health()

    def record_fetch_failure(self, error_message: str = "") -> None:
        """Update state after a failed fetch."""
        now = datetime.now(UTC).isoformat()
        self.last_fetch_attempt = now
        self.fetch_error_count += 1
        self.consecutive_failures += 1
        if error_message:
            self.health_notes = error_message
        self._recompute_health()

    def _recompute_health(self) -> None:
        """Derive health_status from consecutive_failures."""
        if self.consecutive_failures == 0:
            self.health_status = "healthy"
        elif self.consecutive_failures < 3:
            self.health_status = "degraded"
        else:
            self.health_status = "unhealthy"

    def is_healthy(self) -> bool:
        """Return True if this source is not in 'unhealthy' state."""
        return self.health_status != "unhealthy"

    # ── Serialization ──

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_name": self.source_name,
            "description": self.description,
            "data_kind": self.data_kind,
            "last_fetch_attempt": self.last_fetch_attempt,
            "last_fetch_success": self.last_fetch_success,
            "fetch_error_count": self.fetch_error_count,
            "consecutive_failures": self.consecutive_failures,
            "avg_latency_seconds": self.avg_latency_seconds,
            "health_status": self.health_status,
            "health_notes": self.health_notes,
            "supports_symbol_filter": self.supports_symbol_filter,
            "max_symbols": self.max_symbols,
            "rate_limit_rps": self.rate_limit_rps,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SourceMetadata:
        valid_keys = {f.name for f in __import__("dataclasses").fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in valid_keys})


class SourceMetadataStore:
    """Registry for source adapter metadata with JSON file persistence.

    Behaves like a health dashboard for all data source adapters.
    Uses JSON file cache with lazy loading.

    Usage::

        store = SourceMetadataStore()
        store.register(SourceMetadata(source_name="akshare", data_kind="daily_ohlcv"))
        store.record_success("akshare", latency_seconds=2.3)
        print(store.get("akshare").health_status)  # 'healthy'
    """

    def __init__(self, store_path: str | Path = "data/metadata/sources.json") -> None:
        self._store_path = Path(store_path)
        self._entries: dict[str, SourceMetadata] = {}
        self._load_from_disk()

    # ── CRUD ──

    def register(self, meta: SourceMetadata) -> None:
        """Register a source metadata entry.

        Raises:
            ValueError: If a source with the same name already exists.
        """
        if meta.source_name in self._entries:
            raise ValueError(f"数据源 '{meta.source_name}' 已存在。使用 update 或先获取现有条目。")
        self._entries[meta.source_name] = meta
        self._save_to_disk()
        logger.debug("数据源已注册: {}", meta.source_name)

    def get(self, source_name: str) -> SourceMetadata | None:
        """Get a source metadata entry by name."""
        return self._entries.get(source_name)

    def list_sources(self) -> list[str]:
        """Return sorted list of all registered source names."""
        return sorted(self._entries.keys())

    def list_healthy(self) -> list[str]:
        """Return source names whose health_status is not 'unhealthy'."""
        return [n for n, m in self._entries.items() if m.is_healthy()]

    def health_summary(self) -> dict[str, str]:
        """Return {source_name: health_status} for all registered sources."""
        return {n: m.health_status for n, m in self._entries.items()}

    # ── Event recording ──

    def record_success(self, source_name: str, latency_seconds: float = 0.0) -> None:
        """Record a successful fetch for a source. Auto-creates entry if missing."""
        if source_name not in self._entries:
            self._entries[source_name] = SourceMetadata(source_name=source_name)
        self._entries[source_name].record_fetch_success(latency_seconds)
        self._save_to_disk()
        logger.debug("{} 抓取成功 (延迟 {:.1f}s)", source_name, latency_seconds)

    def record_failure(self, source_name: str, error_message: str = "") -> None:
        """Record a failed fetch for a source. Auto-creates entry if missing."""
        if source_name not in self._entries:
            self._entries[source_name] = SourceMetadata(source_name=source_name)
        self._entries[source_name].record_fetch_failure(error_message)
        self._save_to_disk()
        logger.debug("{} 抓取失败: {}", source_name, error_message or "(无详情)")

    # ── Persistence ──

    def _save_to_disk(self) -> None:
        """Persist all entries to JSON file."""
        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "updated_at": datetime.now(UTC).isoformat(),
            "sources": [m.to_dict() for m in self._entries.values()],
        }
        self._store_path.write_text(
            json.dumps(data, indent=2, default=str, ensure_ascii=False),
            encoding="utf-8",
        )

    def _load_from_disk(self) -> None:
        """Load entries from JSON file if it exists."""
        if not self._store_path.exists():
            return
        try:
            data = json.loads(self._store_path.read_text(encoding="utf-8"))
            for raw in data.get("sources", []):
                meta = SourceMetadata.from_dict(raw)
                self._entries[meta.source_name] = meta
            logger.debug("已从磁盘加载 {} 个数据源条目", len(self._entries))
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning("数据源元数据加载失败 ({}), 使用空注册表", e)

    # ── Dunder ──

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, source_name: str) -> bool:
        return source_name in self._entries
