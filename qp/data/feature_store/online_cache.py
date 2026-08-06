"""Online Feature Cache — low-latency in-memory feature store.

Implements data_layer.md §1.5:
  "在线特征缓存 (Online Feature Cache):
    - Storage: Redis / Memory
    - Access: Key-Value Lookup
    - Partition: By Symbol

Provides sub-millisecond feature lookups for real-time strategy execution.
For personal systems, uses an in-memory dict by default; Redis is an
optional upgrade path.

Usage::

    from qp.data.feature_store import OnlineCache

    cache = OnlineCache()
    cache.update("600519", {"momentum_20": 0.05, "rsi_14": 62.3})

    # Get latest feature snapshot for a symbol
    snapshot = cache.get("600519")
    # → {"momentum_20": 0.05, "rsi_14": 62.3, "updated_at": datetime(...)}

    # Batch get all symbols
    all_data = cache.get_all()
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from datetime import UTC, datetime
from typing import Any

from loguru import logger


class OnlineCache:
    """Thread-safe in-memory feature cache for real-time trading.

    Stores the latest feature snapshot per symbol. Optimized for:
      - O(1) per-symbol lookups
      - Batch reads for portfolio-wide signal generation
      - Thread safety for concurrent strategy access

    For personal systems, the in-memory dict suffices. For production,
    swap to Redis with the same interface.
    """

    def __init__(
        self, max_symbols: int = 10_000, ttl_seconds: int | None = None
    ) -> None:
        """Initialize the online cache.

        Args:
            max_symbols: Maximum number of symbols to store (LRU eviction).
            ttl_seconds: Optional TTL for cache entries. None = no expiry.
        """
        self._max_symbols = max_symbols
        self._ttl_seconds = ttl_seconds
        self._cache: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._lock = threading.Lock()

    # ── Write ──

    def update(
        self,
        symbol: str,
        features: dict[str, float | None],
        timestamp: datetime | None = None,
    ) -> None:
        """Update a symbol's feature vector.

        Merges with existing data — partial updates are OK (only provided
        keys are overwritten).

        Args:
            symbol: Stock identifier (e.g., '600519').
            features: Dict of {feature_name: value}. None values are skipped.
            timestamp: When the features were computed. Defaults to now(UTC).
        """
        ts = timestamp or datetime.now(tz=UTC)

        with self._lock:
            if symbol not in self._cache:
                self._cache[symbol] = {"updated_at": ts}
                # Evict oldest if at capacity
                if len(self._cache) > self._max_symbols:
                    oldest = next(iter(self._cache))
                    self._cache.pop(oldest, None)
                    logger.debug("OnlineCache: evicted '{}' (LRU)", oldest)
            else:
                # Move to end (most-recently-used)
                self._cache.move_to_end(symbol)

            entry = self._cache[symbol]
            entry["updated_at"] = ts

            for key, value in features.items():
                if value is not None:
                    entry[key] = value

    def update_batch(
        self,
        symbol_features: dict[str, dict[str, float | None]],
        timestamp: datetime | None = None,
    ) -> None:
        """Batch update multiple symbols.

        Args:
            symbol_features: {symbol: {feature_name: value}}.
            timestamp: When features were computed.
        """
        ts = timestamp or datetime.now(tz=UTC)
        for symbol, features in symbol_features.items():
            self.update(symbol, features, timestamp=ts)

        logger.debug("OnlineCache: batch updated {} symbols", len(symbol_features))

    # ── Read ──

    def get(
        self, symbol: str, feature_names: list[str] | None = None
    ) -> dict[str, Any] | None:
        """Get the latest feature snapshot for a symbol.

        Args:
            symbol: Stock identifier.
            feature_names: Optional subset of features to return.
                          None = all features.

        Returns:
            Dict of {feature_name: value, 'updated_at': datetime}, or None
            if the symbol is not cached (or TTL expired).
        """
        with self._lock:
            if symbol not in self._cache:
                return None

            entry = self._cache[symbol]

            # TTL check
            if self._ttl_seconds is not None and "updated_at" in entry:
                age = (datetime.now(tz=UTC) - entry["updated_at"]).total_seconds()
                if age > self._ttl_seconds:
                    self._cache.pop(symbol, None)
                    return None

            # Move to MRU
            self._cache.move_to_end(symbol)

            if feature_names is not None:
                result = {"updated_at": entry.get("updated_at")}
                for name in feature_names:
                    if name in entry:
                        result[name] = entry[name]
                return result

            return dict(entry)

    def get_feature_value(self, symbol: str, feature_name: str) -> float | None:
        """Get a single feature value for a symbol.

        Args:
            symbol: Stock identifier.
            feature_name: Feature name.

        Returns:
            Feature value or None.
        """
        entry = self.get(symbol, feature_names=[feature_name])
        if entry is None:
            return None
        return entry.get(feature_name)

    def get_all(
        self,
        feature_names: list[str] | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Get feature snapshots for all cached symbols.

        Args:
            feature_names: Optional feature subset.

        Returns:
            {symbol: {feature_name: value, 'updated_at': datetime}}.
        """
        with self._lock:
            result: dict[str, dict[str, Any]] = {}
            expired: list[str] = []

            now = datetime.now(tz=UTC)
            for symbol in list(self._cache.keys()):
                entry = self._cache[symbol]

                # TTL check
                if self._ttl_seconds is not None and "updated_at" in entry:
                    age = (now - entry["updated_at"]).total_seconds()
                    if age > self._ttl_seconds:
                        expired.append(symbol)
                        continue

                if feature_names is not None:
                    filtered = {"updated_at": entry.get("updated_at")}
                    for name in feature_names:
                        if name in entry:
                            filtered[name] = entry[name]
                    result[symbol] = filtered
                else:
                    result[symbol] = dict(entry)

            # Clean expired
            for sym in expired:
                self._cache.pop(sym, None)

            return result

    def get_vector(
        self,
        symbol: str,
        feature_names: list[str],
        default: float = 0.0,
    ) -> list[float]:
        """Get a feature vector as a list of floats (for model input).

        Args:
            symbol: Stock identifier.
            feature_names: Ordered list of feature names.
            default: Default value for missing features.

        Returns:
            List of feature values in the same order as feature_names.
        """
        entry = self.get(symbol, feature_names=feature_names)
        if entry is None:
            return [default] * len(feature_names)

        return [entry.get(name, default) for name in feature_names]

    # ── Management ──

    def remove(self, symbol: str) -> bool:
        """Remove a symbol from the cache.

        Returns:
            True if the symbol was present and removed.
        """
        with self._lock:
            if symbol in self._cache:
                self._cache.pop(symbol, None)
                return True
            return False

    def clear(self) -> None:
        """Clear all cached data."""
        with self._lock:
            self._cache.clear()
            logger.info("OnlineCache: cleared all entries")

    def refresh_from_offline(
        self,
        offline_store,
        as_of_date: str,
        symbols: list[str] | None = None,
        factor_groups: list[str] | None = None,
    ) -> int:
        """Refresh the online cache from the offline store.

        Loads the latest feature snapshot from the OfflineStore and
        populates the online cache. This is the bridge between batch
        computation and real-time serving.

        Args:
            offline_store: OfflineStore instance.
            as_of_date: Reference date for snapshot.
            symbols: Optional symbol filter.
            factor_groups: Optional factor group filter.

        Returns:
            Number of symbols loaded into cache.
        """
        df = offline_store.load_snapshot(
            as_of_date=as_of_date,
            symbols=symbols,
            factor_groups=factor_groups,
        )

        if df.is_empty():
            logger.debug("OnlineCache: no data to refresh from offline store")
            return 0

        # Convert DataFrame rows to per-symbol dicts
        count = 0
        if "symbol" in df.columns:
            for row in df.iter_rows(named=True):
                symbol = str(row.pop("symbol"))
                # Drop metadata columns
                row.pop("trade_date", None)
                row.pop("year", None)
                features = {k: v for k, v in row.items() if v is not None}
                if features:
                    self.update(symbol, features)
                    count += 1

        logger.info(
            "OnlineCache: refreshed {} symbols from offline store (as_of={})",
            count,
            as_of_date,
        )
        return count

    # ── Properties ──

    @property
    def symbol_count(self) -> int:
        """Number of symbols currently cached."""
        with self._lock:
            return len(self._cache)

    @property
    def feature_names(self) -> set[str]:
        """Set of all feature names across all cached symbols."""
        names: set[str] = set()
        with self._lock:
            for entry in self._cache.values():
                names.update(k for k in entry if k != "updated_at")
        return names

    def is_cached(self, symbol: str) -> bool:
        """Check if a symbol has cached data."""
        return self.get(symbol) is not None

    def age_seconds(self, symbol: str) -> float | None:
        """Get the age of a symbol's cached data in seconds."""
        entry = self.get(symbol)
        if entry is None or "updated_at" not in entry:
            return None
        return (datetime.now(tz=UTC) - entry["updated_at"]).total_seconds()

    def __contains__(self, symbol: str) -> bool:
        return self.is_cached(symbol)

    def __len__(self) -> int:
        return self.symbol_count

    def __repr__(self) -> str:
        return (
            f"OnlineCache(symbols={self.symbol_count}, "
            f"features={sorted(self.feature_names)}, "
            f"max={self._max_symbols})"
        )
