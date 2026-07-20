"""JSON cache for industry classification mappings.

Cache TTL is 90 days — CSRC industry classifications change very slowly
(mainly during IPO or major restructurings).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loguru import logger

DEFAULT_CACHE_TTL_DAYS = 90
DEFAULT_CACHE_PATH = Path("data/industry_cache.json")


class IndustryCache:
    """Persistent JSON cache for industry classification mappings.

    Usage:
        cache = IndustryCache()
        data = cache.load()           # returns dict or None if expired/missing
        cache.save({"600519": "白酒"})  # persists to disk
    """

    def __init__(
        self,
        cache_path: str | Path = DEFAULT_CACHE_PATH,
        ttl_days: int = DEFAULT_CACHE_TTL_DAYS,
    ) -> None:
        self._path = Path(cache_path)
        self._ttl_days = ttl_days

    def load(self) -> dict[str, str] | None:
        """Load industry mapping from cache.

        Returns:
            {symbol: industry_name} dict if cache is valid, None otherwise.
        """
        if not self._path.exists():
            logger.debug("行业缓存文件不存在: {}", self._path)
            return None

        age_days = self._age_days()
        if age_days > self._ttl_days:
            logger.info("行业缓存已过期 ({} 天 > {} 天)，将重新获取", age_days, self._ttl_days)
            return None

        try:
            with open(self._path, encoding="utf-8") as f:
                data: Any = json.load(f)
            if isinstance(data, dict) and len(data) > 50:
                logger.info("加载行业缓存: {} 只股票 ({} 天前)", len(data), age_days)
                return data
            logger.warning(
                "行业缓存数据不足 ({} 条)，视为无效", len(data) if isinstance(data, dict) else 0
            )
            return None
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("行业缓存加载失败: {}", e)
            return None

    def save(self, industry_map: dict[str, str]) -> None:
        """Save industry mapping to cache file.

        Args:
            industry_map: {symbol: industry_name} mapping.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(industry_map, f, ensure_ascii=False, indent=2)
        logger.info("行业映射已缓存: {} 只股票 → {}", len(industry_map), self._path)

    def invalidate(self) -> None:
        """Delete the cache file, forcing a fresh fetch on next load."""
        if self._path.exists():
            self._path.unlink()
            logger.info("行业缓存已清除: {}", self._path)

    @property
    def path(self) -> Path:
        return self._path

    def _age_days(self) -> int:
        """Return cache file age in days."""
        mtime = datetime.fromtimestamp(self._path.stat().st_mtime, tz=UTC)
        age = datetime.now(tz=UTC) - mtime
        return age.days
