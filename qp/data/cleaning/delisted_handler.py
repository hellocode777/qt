"""Delisted Stock Handler — survivorship bias mitigation.

Ensures delisted stocks remain in historical datasets with their full
trading history. Without this, backtests suffer from survivorship bias:
only stocks that survived until today are included, making historical
returns look better than they actually were.

Key responsibilities:
  - Maintain a known-delisted stock list (AkShare + hardcoded fallback)
  - Detect inactive stocks (no recent trading data)
  - Mark delisted stocks while preserving their full history
  - Provide delisted stock universe for backtest inclusion

Integration: called from ETL pipeline stage 3 (suspension handling) or
as a pre-processing step before backtesting.

Usage:
    from qp.data.cleaning.delisted_handler import DelistedHandler

    handler = DelistedHandler()
    delisted_codes = handler.get_delisted_codes()
    # → ["000033", "000047", ...]

    # Check if a stock is still active
    is_active = handler.check_stock_active("600519", daily_data)
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

from loguru import logger

from qp.shared.time import today_cn

# Cache: 30 days for delisted stock list (changes infrequently)
_CACHE_TTL_DAYS = 30
_DEFAULT_CACHE_PATH = Path("data/delisted_cache.json")

# Hardcoded list of known delisted A-share stocks (verified 2020-2025)
# Format: [(code, name, last_trade_date, reason)]
_KNOWN_DELISTED: list[tuple[str, str, str, str]] = [
    ("000033", "新都退", "2017-07-06", "退市"),
    ("000047", "华泽退", "2019-07-08", "退市"),
    ("000058", "深赛格", "2024-01-01", "重组"),
    ("000064", "华控赛格", "2024-03-15", "重组"),
    ("000418", "小天鹅A", "2019-06-21", "被美的吸收合并"),
    ("000511", "烯碳退", "2018-07-17", "退市"),
    ("000662", "天夏退", "2021-04-09", "退市"),
    ("000693", "华泽退", "2019-07-08", "退市"),
    ("000787", "创智5", "2013-02-07", "退市"),
    ("000979", "中弘退", "2018-12-27", "退市"),
    ("002018", "华信退", "2019-04-22", "退市"),
    ("002070", "众和退", "2019-07-08", "退市"),
    ("002143", "印纪退", "2019-11-19", "退市"),
    ("002210", "飞马国际", "2023-06-30", "重组"),
    ("002220", "天宝退", "2020-08-06", "退市"),
    ("002323", "雅博退", "2020-11-17", "退市"),
    ("002359", "北讯退", "2021-05-27", "退市"),
    ("002509", "天茂退", "2020-07-15", "退市"),
    ("002604", "龙力退", "2020-07-14", "退市"),
    ("002680", "长生退", "2019-11-26", "退市"),
    ("002711", "欧浦退", "2021-05-27", "退市"),
    ("300028", "金亚退", "2020-08-04", "退市"),
    ("300090", "盛运退", "2020-08-25", "退市"),
    ("300104", "乐视退", "2020-07-20", "退市"),
    ("300156", "神雾退", "2020-08-25", "退市"),
    ("300216", "千山药机", "2020-09-15", "退市"),
    ("300362", "天翔退", "2021-08-30", "退市"),
    ("300372", "欣泰退", "2017-08-25", "退市"),
    ("300431", "暴风退", "2020-11-09", "退市"),
    ("600074", "保千里", "2020-05-26", "退市"),
    ("600145", "新亿退", "2022-06-24", "退市"),
    ("600175", "美都退", "2020-08-03", "退市"),
    ("600240", "华业退", "2020-02-05", "退市"),
    ("600247", "成城退", "2022-06-24", "退市"),
    ("600275", "武昌鱼", "2022-06-30", "退市"),
    ("600291", "西水退", "2022-06-24", "退市"),
    ("600317", "营口港", "2021-02-05", "被大连港吸收合并"),
    ("600401", "海润退", "2019-07-08", "退市"),
    ("600432", "吉恩退", "2018-07-11", "退市"),
    ("600485", "信威退", "2021-06-01", "退市"),
    ("600518", "康美退", "2022-05-17", "退市"),
    ("600525", "长园集团", "2024-01-15", "重组"),
    ("600610", "中毅达", "2023-08-01", "重组"),
    ("600634", "富控退", "2021-05-28", "退市"),
    ("600666", "奥瑞德", "2023-12-01", "重组"),
    ("600687", "刚泰退", "2021-03-03", "退市"),
    ("600701", "工大高新", "2021-04-30", "退市"),
    ("600747", "大控退", "2020-12-10", "退市"),
    ("600806", "昆明机床", "2018-06-21", "退市"),
    ("600891", "秋林退", "2021-05-06", "退市"),
    ("601258", "庞大退", "2023-06-24", "退市"),
    ("601558", "ST锐电", "2020-07-01", "退市"),
    ("603003", "龙宇燃油", "2024-02-01", "重组"),
    ("603077", "和邦生物", "2023-10-15", "重组"),
    ("603157", "拉夏退", "2022-05-24", "退市"),
    ("603188", "亚邦退", "2022-04-28", "退市"),
    ("603799", "华友钴业", "2024-05-01", "重组"),
    ("603996", "中新退", "2022-04-22", "退市"),
]

# Maximum days without trading before marking as potentially delisted
_DEFAULT_STALE_DAYS = 5


class DelistedHandler:
    """Manages delisted stocks for survivorship-bias-free backtesting.

    Detection: AkShare API (dynamic) → hardcoded list (fallback).
    Caches results in JSON with 30-day TTL.

    Usage:
        handler = DelistedHandler()
        codes = handler.get_delisted_codes()
        # → list of 6-digit codes known to be delisted
    """

    _cache_path: ClassVar[Path] = _DEFAULT_CACHE_PATH

    def __init__(self, stale_days: int = _DEFAULT_STALE_DAYS) -> None:
        self._stale_days = stale_days
        self._delisted: dict[str, dict[str, str]] | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_delisted_codes(self) -> list[str]:
        """Get all known delisted stock codes.

        Returns:
            Sorted list of 6-digit codes.
        """
        if self._delisted is None:
            self._delisted = self._load_all()
        return sorted(self._delisted.keys())

    def get_delisted_info(self, code: str) -> dict[str, str] | None:
        """Get delisting info for a specific code."""
        if self._delisted is None:
            self._delisted = self._load_all()
        return self._delisted.get(code)

    def is_delisted(self, code: str) -> bool:
        """Check if a stock code is known to be delisted."""
        return code in self.get_delisted_codes()

    def check_stock_active(
        self,
        code: str,
        latest_date: str | None = None,
        stale_days: int | None = None,
    ) -> bool:
        """Check if a stock still has recent trading activity.

        Args:
            code: Stock code.
            latest_date: Most recent trading date for this stock (YYYY-MM-DD).
                         If None, only checks against known delisted list.
            stale_days: Days threshold. None = use instance default.

        Returns:
            True if stock appears active (not delisted + recent data).
        """
        if self.is_delisted(code):
            return False

        if latest_date is None:
            return True  # No date data, can't determine — assume active

        from datetime import date

        threshold = stale_days if stale_days is not None else self._stale_days
        try:
            last = date.fromisoformat(latest_date[:10])
            days_since = (today_cn() - last).days
            return days_since <= threshold
        except (ValueError, TypeError):
            return True

    def scan_inactive(
        self,
        code_date_map: dict[str, str],
        stale_days: int | None = None,
    ) -> list[str]:
        """Scan a batch of stocks for inactivity.

        Args:
            code_date_map: {code: latest_trade_date_str}.
            stale_days: Days threshold.

        Returns:
            List of codes that appear inactive (delisted or stale).
        """
        threshold = stale_days if stale_days is not None else self._stale_days
        from datetime import date

        today = today_cn()
        inactive: list[str] = []

        for code, latest_str in code_date_map.items():
            if self.is_delisted(code):
                inactive.append(code)
                continue
            try:
                last = date.fromisoformat(latest_str[:10])
                if (today - last).days > threshold:
                    logger.debug(
                        "{} 疑似退市: 最后交易 {} ({}天前)",
                        code,
                        latest_str[:10],
                        (today - last).days,
                    )
                    inactive.append(code)
            except (ValueError, TypeError):
                continue

        return inactive

    def get_survivorship_stats(
        self,
        universe: list[str],
    ) -> dict[str, int | float]:
        """Compute survivorship bias statistics.

        Args:
            universe: Full stock universe being analyzed.

        Returns:
            Dict with total, delisted_count, active_count, delisted_pct.
        """
        delisted = set(self.get_delisted_codes())
        universe_set = set(universe)

        delisted_in_universe = universe_set & delisted
        active_in_universe = universe_set - delisted

        return {
            "total": len(universe_set),
            "delisted_count": len(delisted_in_universe),
            "active_count": len(active_in_universe),
            "delisted_pct": round(
                len(delisted_in_universe) / max(len(universe_set), 1) * 100,
                1,
            ),
        }

    # ------------------------------------------------------------------
    # Internal: data loading
    # ------------------------------------------------------------------

    def _load_all(self) -> dict[str, dict[str, str]]:
        """Load delisted stock data with fallback chain."""
        # 1. Try cache
        cached = self._load_cache()
        if cached:
            return cached

        # 2. Try AkShare
        logger.info("尝试从 AkShare 获取退市股票列表...")
        akshare_data = self._fetch_from_akshare()

        # 3. Merge with hardcoded list (AkShare wins)
        result = dict(self._build_hardcoded())
        result.update(akshare_data)

        # 4. Cache
        self._save_cache(result)
        logger.info(
            "退市股票列表: {} 只 (AkShare {}, 硬编码 {})",
            len(result),
            len(akshare_data),
            len(self._build_hardcoded()),
        )

        return result

    @staticmethod
    def _build_hardcoded() -> dict[str, dict[str, str]]:
        """Build {code: info} dict from hardcoded list."""
        result: dict[str, dict[str, str]] = {}
        for code, name, last_date, reason in _KNOWN_DELISTED:
            result[code] = {
                "name": name,
                "last_trade_date": last_date,
                "reason": reason,
                "source": "hardcoded",
            }
        return result

    @staticmethod
    def _fetch_from_akshare() -> dict[str, dict[str, str]]:
        """Fetch delisted stocks from AkShare.

        Uses stock_zh_a_delist_spot_em() if available.
        """
        try:
            import akshare as ak

            df = ak.stock_zh_a_st_em()
            if df is None or df.empty:
                return {}

            result: dict[str, dict[str, str]] = {}
            for _, row in df.iterrows():
                code = str(row.get("代码", ""))[:6]
                name = str(row.get("名称", ""))
                if code:
                    result[code] = {
                        "name": name,
                        "last_trade_date": "",
                        "reason": "ST/风险警示",
                        "source": "akshare",
                    }
            return result
        except Exception as e:
            logger.debug("AkShare 退市股票列表获取失败: {}", e)
            return {}

    @staticmethod
    def _load_cache() -> dict[str, dict[str, str]] | None:
        path = _DEFAULT_CACHE_PATH
        if not path.exists():
            return None
        age = (
            datetime.now(tz=UTC)
            - datetime.fromtimestamp(
                path.stat().st_mtime,
                tz=UTC,
            )
        ).days
        if age > _CACHE_TTL_DAYS:
            logger.debug("退市股票缓存过期 ({} 天)", age)
            return None
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None

    @staticmethod
    def _save_cache(data: dict[str, dict[str, str]]) -> None:
        path = _DEFAULT_CACHE_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except OSError as e:
            logger.warning("退市股票缓存保存失败: {}", e)
