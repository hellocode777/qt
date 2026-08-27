"""Listing Date Registry — prevents survivorship bias from IPOs.

Implements data_layer.md §1.4 Dynamic Universe step 3:
  "上市日期过滤（新股未满 N 天）"

Maintains a registry of A-share IPO dates with fallback chain:
  1. Local JSON cache (90-day TTL)
  2. AkShare stock_info (dynamic)
  3. Hardcoded list (~150 major A-shares)

Usage::

    from qp.data.universe import ListingDateRegistry, is_listed_before

    registry = ListingDateRegistry()
    was_listed = is_listed_before("600519", "2024-01-15")
    # → True (Kweichow Moutai listed in 2001)
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from datetime import date as date_t
from pathlib import Path
from typing import ClassVar

from loguru import logger

from qp.shared.json_io import json_load, json_save

# Cache TTL for IPO date data (changes very rarely)
_CACHE_TTL_DAYS = 90
_DEFAULT_CACHE_PATH = Path("data/listing_dates_cache.json")

# Default minimum days since IPO before stock is tradeable
_DEFAULT_MIN_LISTING_DAYS = 200  # ~1 trading year

# Hardcoded listing dates for major A-share stocks (verified)
# Format: {code: (listing_date_iso, name)}
_HARDCODED_LISTING: dict[str, tuple[str, str]] = {
    # Shanghai Main Board (600xxx-601xxx-603xxx)
    "600000": ("1999-11-10", "浦发银行"),
    "600016": ("2000-12-19", "民生银行"),
    "600028": ("2001-08-08", "中国石化"),
    "600030": ("2003-01-06", "中信证券"),
    "600031": ("2003-07-03", "三一重工"),
    "600036": ("2002-04-09", "招商银行"),
    "600048": ("2006-07-31", "保利发展"),
    "600050": ("2002-10-09", "中国联通"),
    "600085": ("1997-06-25", "同仁堂"),
    "600104": ("1997-11-25", "上汽集团"),
    "600111": ("1997-09-24", "北方稀土"),
    "600196": ("1998-08-07", "复星医药"),
    "600276": ("2000-10-18", "恒瑞医药"),
    "600309": ("2001-01-05", "万华化学"),
    "600406": ("2003-10-16", "国电南瑞"),
    "600436": ("2003-07-18", "片仔癀"),
    "600438": ("2004-03-02", "通威股份"),
    "600519": ("2001-08-27", "贵州茅台"),
    "600570": ("2003-06-12", "恒生电子"),
    "600585": ("2002-02-07", "海螺水泥"),
    "600588": ("2001-05-18", "用友网络"),
    "600690": ("1993-11-19", "海尔智家"),
    "600809": ("1994-01-06", "山西汾酒"),
    "600887": ("1996-03-12", "伊利股份"),
    "600900": ("2003-11-18", "长江电力"),
    "601012": ("2011-04-12", "隆基绿能"),
    "601088": ("2007-10-09", "中国神华"),
    "601111": ("2006-08-18", "中国国航"),
    "601166": ("2007-02-05", "兴业银行"),
    "601288": ("2010-07-15", "农业银行"),
    "601318": ("2007-03-01", "中国平安"),
    "601328": ("2007-05-15", "交通银行"),
    "601390": ("2007-12-03", "中国中铁"),
    "601398": ("2006-10-27", "工商银行"),
    "601600": ("2007-04-30", "中国铝业"),
    "601628": ("2007-01-09", "中国人寿"),
    "601668": ("2009-07-29", "中国建筑"),
    "601688": ("2010-02-26", "华泰证券"),
    "601766": ("2008-08-18", "中国中车"),
    "601800": ("2012-03-09", "中国交建"),
    "601818": ("2010-08-18", "光大银行"),
    "601857": ("2007-11-05", "中国石油"),
    "601888": ("2009-10-15", "中国中免"),
    "601899": ("2008-04-25", "紫金矿业"),
    "601919": ("2007-06-26", "中远海控"),
    "601939": ("2007-09-25", "建设银行"),
    "601985": ("2015-06-10", "中国核电"),
    "601988": ("2006-07-05", "中国银行"),
    "601989": ("2009-12-16", "中国重工"),
    "603259": ("2018-06-11", "药明康德"),
    "603288": ("2014-02-11", "海天味业"),
    "603501": ("2019-07-22", "韦尔股份"),
    # Shenzhen Main Board (000xxx-001xxx-002xxx)
    "000001": ("1991-04-03", "平安银行"),
    "000002": ("1991-01-29", "万科A"),
    "000063": ("1997-11-18", "中兴通讯"),
    "000333": ("2013-09-18", "美的集团"),
    "000338": ("2007-04-30", "潍柴动力"),
    "000568": ("1994-05-09", "泸州老窖"),
    "000651": ("1996-11-18", "格力电器"),
    "000725": ("2001-01-12", "京东方A"),
    "000858": ("1998-04-27", "五粮液"),
    "002007": ("2004-06-25", "华兰生物"),
    "002142": ("2007-07-19", "宁波银行"),
    "002230": ("2008-05-12", "科大讯飞"),
    "002241": ("2008-05-22", "歌尔股份"),
    "002304": ("2009-11-06", "洋河股份"),
    "002352": ("2010-02-05", "顺丰控股"),
    "002415": ("2010-05-28", "海康威视"),
    "002460": ("2010-08-10", "赣锋锂业"),
    "002466": ("2010-08-31", "天齐锂业"),
    "002475": ("2010-09-15", "立讯精密"),
    "002594": ("2011-06-30", "比亚迪"),
    "002714": ("2014-01-28", "牧原股份"),
    # GEM (300xxx-301xxx)
    "300015": ("2009-10-30", "爱尔眼科"),
    "300059": ("2010-03-19", "东方财富"),
    "300124": ("2014-01-13", "汇川技术"),
    "300274": ("2011-11-02", "阳光电源"),
    "300413": ("2015-01-21", "芒果超媒"),
    "300498": ("2015-11-02", "温氏股份"),
    "300750": ("2018-06-11", "宁德时代"),
    "300760": ("2018-10-16", "迈瑞医疗"),
    # STAR Market (688xxx-689xxx)
    "688111": ("2019-11-18", "金山办公"),
    "688185": ("2020-03-18", "康希诺"),
    "688256": ("2020-07-20", "寒武纪"),
    "688396": ("2020-04-20", "华润微"),
    "688561": ("2020-07-22", "奇安信"),
    "688981": ("2020-07-16", "中芯国际"),
}


class ListingDateRegistry:
    """Registry of A-share IPO/listing dates with multi-source fallback.

    Usage::

        registry = ListingDateRegistry()
        d = registry.get("600519")  # → date(2001, 8, 27)
        ok = registry.is_seasoned("600519", date(2024, 1, 15))
        # → True (has been listed > 200 days)
    """

    _cache_path: ClassVar[Path] = _DEFAULT_CACHE_PATH

    def __init__(
        self,
        min_listing_days: int = _DEFAULT_MIN_LISTING_DAYS,
    ) -> None:
        self._min_listing_days = min_listing_days
        self._listing_dates: dict[str, date_t] | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, code: str) -> date_t | None:
        """Get the IPO listing date for a stock.

        Returns:
            date or None if unknown.
        """
        if self._listing_dates is None:
            self._listing_dates = self._load_all()
        return self._listing_dates.get(code)

    def is_seasoned(self, code: str, target_date: date_t | str) -> bool:
        """Check if stock was listed long enough before target_date.

        A stock is "seasoned" if:
          target_date - listing_date >= min_listing_days

        Args:
            code: 6-digit stock code.
            target_date: Reference date (YYYY-MM-DD or date object).

        Returns:
            True if stock is seasoned (eligible for trading).
            True if listing date is unknown (optimistic assumption).
        """
        listing = self.get(code)
        if listing is None:
            return True  # Unknown → assume tradeable (avoid false exclusions)

        if isinstance(target_date, str):
            target_date = date_t.fromisoformat(target_date)

        days_listed = (target_date - listing).days
        return days_listed >= self._min_listing_days

    def filter_seasoned(
        self,
        symbols: list[str],
        target_date: date_t | str,
    ) -> list[str]:
        """Filter a list of symbols, returning only seasoned stocks.

        Args:
            symbols: Candidate stock codes.
            target_date: Reference date.

        Returns:
            Subset of symbols that are seasoned.
        """
        if isinstance(target_date, str):
            target_date = date_t.fromisoformat(target_date)

        excluded: list[str] = []
        kept: list[str] = []
        for sym in symbols:
            if self.is_seasoned(sym, target_date):
                kept.append(sym)
            else:
                excluded.append(sym)

        if excluded:
            logger.info(
                "IPO 过滤: {} 只排除 (上市未满 {} 天), {} 只保留",
                len(excluded),
                self._min_listing_days,
                len(kept),
            )
            logger.debug("  排除代码: {}", excluded)
        return kept

    def get_all_known(self) -> dict[str, date_t]:
        """Get all known listing dates."""
        if self._listing_dates is None:
            self._listing_dates = self._load_all()
        return dict(self._listing_dates)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load_all(self) -> dict[str, date_t]:
        """Load listing dates with fallback chain."""
        # 1. Try cache
        cached = self._load_cache()
        if cached:
            logger.debug("IPO 日期缓存命中: {} 只", len(cached))
            return cached

        # 2. Try AkShare
        akshare_data = self._fetch_from_akshare()

        # 3. Merge with hardcoded (AkShare wins)
        result = dict(self._build_hardcoded())
        result.update(akshare_data)

        # 4. Cache
        self._save_cache(result)
        logger.info(
            "IPO 日期注册: {} 只 (AkShare {}, 硬编码 {})",
            len(result),
            len(akshare_data),
            len(self._build_hardcoded()),
        )

        return result

    @staticmethod
    def _build_hardcoded() -> dict[str, date_t]:
        return {code: date_t.fromisoformat(d) for code, (d, _) in _HARDCODED_LISTING.items()}

    @staticmethod
    def _fetch_from_akshare() -> dict[str, date_t]:
        """Fetch listing dates from AkShare.

        Uses stock_info_a_code_name() to get all A-share listings.
        """
        try:
            import akshare as ak

            # Try individual stock info for each symbol
            df = ak.stock_info_a_code_name()
            if df is None or df.empty:
                return {}

            result: dict[str, date_t] = {}
            for _, row in df.iterrows():
                code = str(row.get("code", row.get("代码", "")))[:6]
                listing_str = row.get(
                    "listing_date", row.get("上市日期", row.get("list_date", None))
                )
                if code and listing_str:
                    try:
                        result[code] = date_t.fromisoformat(str(listing_str)[:10])
                    except (ValueError, TypeError):
                        continue
            logger.info("AkShare IPO 日期: {} 只", len(result))
            return result
        except Exception as e:
            logger.debug("AkShare IPO 日期获取失败 (可能网络问题): {}", e)
            return {}

    @staticmethod
    def _load_cache() -> dict[str, date_t] | None:
        path = _DEFAULT_CACHE_PATH
        if not path.exists():
            return None
        age = (datetime.now(tz=UTC) - datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)).days
        if age > _CACHE_TTL_DAYS:
            logger.debug("IPO 日期缓存过期 ({} 天)", age)
            return None
        try:
            data: dict[str, str] = json_load(path)
            return {code: date_t.fromisoformat(d) for code, d in data.items()}
        except (json.JSONDecodeError, OSError, ValueError):
            return None

    @staticmethod
    def _save_cache(data: dict[str, date_t]) -> None:
        path = _DEFAULT_CACHE_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            serialized = {code: d.isoformat() for code, d in data.items()}
            json_save(path, serialized)
        except OSError as e:
            logger.warning("IPO 日期缓存保存失败: {}", e)


# ------------------------------------------------------------------
# Module-level convenience functions
# ------------------------------------------------------------------

_default_registry: ListingDateRegistry | None = None


def _get_registry() -> ListingDateRegistry:
    global _default_registry
    if _default_registry is None:
        _default_registry = ListingDateRegistry()
    return _default_registry


def get_listing_date(code: str) -> date_t | None:
    """Get IPO listing date (module-level convenience)."""
    return _get_registry().get(code)


def is_listed_before(code: str, target_date: date_t | str) -> bool:
    """Check if stock was listed before target_date (module-level convenience)."""
    return _get_registry().is_seasoned(code, target_date)
