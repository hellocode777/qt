"""Industry Classifier — multi-source fallback chain for A-share industry mapping.

Data sources (in priority order):
  1. Local JSON cache (90-day TTL)
  2. Baostock — CSRC (China Securities Regulatory Commission) industry classification
  3. AkShare — East Money (东方财富) industry sector boards
  4. Code prefix fallback — last resort, 30+ categories

All sources are hidden behind ``IndustryClassifier``. Consumers never know
which source provided the data (ADR-013).
"""

from __future__ import annotations

import contextlib
from typing import ClassVar

from loguru import logger

from qp.data.industry.cache import IndustryCache

# ------------------------------------------------------------------
# CSRC major category mapping (一级行业大类, for aggregation)
# ------------------------------------------------------------------

CSRC_CATEGORY_MAP: dict[str, str] = {
    "A": "农林牧渔",
    "B": "采矿业",
    "C": "制造业",
    "D": "电力热力燃气",
    "E": "建筑业",
    "F": "批发零售",
    "G": "交通运输仓储",
    "H": "住宿餐饮",
    "I": "信息技术",
    "J": "金融业",
    "K": "房地产业",
    "L": "租赁商务服务",
    "M": "科研技术服务",
    "N": "水利环境公共设施",
    "O": "居民服务修理",
    "P": "教育",
    "Q": "卫生社会工作",
    "R": "文化体育娱乐",
    "S": "综合",
}

# ------------------------------------------------------------------
# Code prefix → fallback industry (30+ categories)
# ------------------------------------------------------------------

_PREFIX_INDUSTRY: dict[str, str] = {
    # Shanghai main board
    "600": "金融/综合(沪)",
    "601": "金融/基建(沪)",
    "603": "制造/科技(沪)",
    "605": "制造/科技(沪)",
    # STAR market (科创板)
    "688": "科创板",
    "689": "科创板",
    # Shenzhen main board
    "000": "主板(深)",
    "001": "主板(深)",
    # SME board
    "002": "中小板",
    "003": "中小板",
    # ChiNext (创业板)
    "300": "创业板",
    "301": "创业板",
}

# ------------------------------------------------------------------
# AkShare board code → industry name mapping (80+ sectors)
# ------------------------------------------------------------------

_AKSHARE_BOARD_NAMES: dict[str, str] = {
    "BK0477": "白酒",
    "BK0481": "啤酒",
    "BK0478": "食品饮料",
    "BK0468": "医药制造",
    "BK0465": "医疗器械",
    "BK0479": "家电行业",
    "BK0449": "半导体",
    "BK0447": "电子元件",
    "BK0536": "新能源",
    "BK0448": "计算机",
    "BK0459": "通信设备",
    "BK0497": "汽车行业",
    "BK0476": "银行",
    "BK0473": "保险",
    "BK0494": "房地产",
    "BK0485": "航天军工",
    "BK0493": "化工行业",
    "BK0471": "水泥建材",
    "BK0488": "煤炭行业",
    "BK0496": "钢铁行业",
    "BK0487": "有色金属",
    "BK0456": "软件开发",
    "BK0492": "电力行业",
    "BK0495": "环保行业",
    "BK0457": "互联网服务",
    "BK0460": "文化传媒",
    "BK0501": "农牧饲渔",
    "BK0480": "纺织服装",
    "BK0483": "商业百货",
    "BK0484": "旅游酒店",
    "BK0504": "仪器仪表",
    "BK0508": "输配电气",
    "BK0502": "港口水运",
    "BK0472": "民航机场",
    "BK0482": "高速公路",
    "BK0509": "工程建设",
    "BK0490": "石油行业",
    "BK0464": "材料行业",
    "BK0507": "专用设备",
    "BK0498": "文化传媒",
    "BK0537": "新能源车",
    "BK0555": "光伏设备",
    "BK0489": "电子信息",
    "BK0589": "锂电池",
    "BK0573": "储能",
    "BK0491": "机械行业",
    "BK0469": "化纤行业",
    "BK0467": "包装材料",
    "BK0513": "安防设备",
    "BK0510": "船舶制造",
    "BK0450": "通信服务",
    "BK0475": "证券",
    "BK0547": "数字货币",
    "BK0503": "交运设备",
    "BK0576": "CRO",
    "BK0580": "工业母机",
    "BK0593": "数字经济",
    "BK0544": "东数西算",
    "BK0545": "信创",
}

# AkShare board codes to fetch
_AKSHARE_BOARD_CODES: list[str] = list(_AKSHARE_BOARD_NAMES.keys())


class IndustryClassifier:
    """Multi-source industry classification for A-share stocks.

    Fallback chain: local cache → Baostock (CSRC) → AkShare (East Money) → prefix.

    Usage:
        classifier = IndustryClassifier()
        mapping = classifier.get_mapping(["600519", "000858"])
        # → {"600519": "C15酒、饮料和精制茶制造业", "000858": "C15..."}

        # Get major category:
        cat = classifier.get_category("C15酒、饮料和精制茶制造业")
        # → "制造业"
    """

    # Cache instance shared across classifier instances (class-level)
    _cache: ClassVar[IndustryCache] = IndustryCache()

    def __init__(self, force_refresh: bool = False) -> None:
        """Initialize classifier.

        Args:
            force_refresh: If True, skip cache and re-fetch from all sources.
        """
        self._force_refresh = force_refresh
        self._data: dict[str, str] | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_mapping(self, symbols: list[str] | None = None) -> dict[str, str]:
        """Get {symbol: industry_name} for the requested symbols.

        Args:
            symbols: Stock codes to look up. If None, returns all cached symbols.

        Returns:
            {symbol: industry_name} — every requested symbol gets a label
            (via fallback if no source has it).
        """
        all_data = self._load_all()

        if symbols is None:
            return dict(all_data)

        result: dict[str, str] = {}
        for sym in symbols:
            code = str(sym)[:6]
            industry = all_data.get(code, "")
            if industry:
                result[code] = industry
            else:
                result[code] = self._prefix_fallback(code)
        return result

    def get_category(self, industry_name: str) -> str:
        """Extract CSRC major category from a full industry name.

        Args:
            industry_name: e.g. "C15酒、饮料和精制茶制造业"

        Returns:
            Major category name, e.g. "制造业", or "其他" if unrecognized.
        """
        if not industry_name:
            return "其他"
        prefix = industry_name[0].upper()
        return CSRC_CATEGORY_MAP.get(prefix, f"其他({prefix})")

    def get_stocks_in_industry(
        self,
        industry: str,
        symbols: list[str],
    ) -> list[str]:
        """Get all stocks belonging to a given industry.

        Args:
            industry: Industry name to filter by.
            symbols: Universe of stock codes to check.

        Returns:
            List of stock codes in the specified industry.
        """
        mapping = self.get_mapping(symbols)
        return [c for c in symbols if mapping.get(str(c)[:6]) == industry]

    def refresh(self) -> dict[str, str]:
        """Force a full refresh from remote sources, bypassing cache."""
        self._data = None
        self._cache.invalidate()
        return self._load_all()

    # ------------------------------------------------------------------
    # Internal: load pipeline
    # ------------------------------------------------------------------

    def _load_all(self) -> dict[str, str]:
        """Execute the full fallback chain and return the merged result."""
        if self._data is not None:
            return self._data

        # 1. Try cache
        if not self._force_refresh:
            cached = self._cache.load()
            if cached:
                self._data = cached
                return self._data

        # 2. Try Baostock
        logger.info("尝试 Baostock 获取 CSRC 行业分类...")
        baostock_data = self._fetch_from_baostock()

        # 3. Try AkShare supplement
        if len(baostock_data) < 1000:
            logger.info("Baostock 数据不足 ({} 条)，尝试 AkShare 补充...", len(baostock_data))
            akshare_data = self._fetch_from_akshare()
            # Merge: baostock wins, akshare fills gaps
            for code, industry in akshare_data.items():
                if code not in baostock_data or not baostock_data[code]:
                    baostock_data[code] = industry

        # 4. Save to cache
        if baostock_data:
            self._cache.save(baostock_data)
            self._data = baostock_data
            return self._data

        # 5. All remote sources failed — use empty dict, prefix fallback at query time
        logger.warning("所有在线数据源不可用，将使用代码前缀兜底")
        self._data = {}
        return self._data

    # ------------------------------------------------------------------
    # Internal: Baostock source
    # ------------------------------------------------------------------

    @staticmethod
    def _fetch_from_baostock() -> dict[str, str]:
        """Fetch CSRC industry classification from Baostock.

        Returns:
            {code: "C15酒、饮料和精制茶制造业"} mapping.
        """
        try:
            import baostock as bs  # type: ignore[reportMissingImports]
        except ImportError:
            logger.debug("Baostock 未安装，跳过")
            return {}

        try:
            lg = bs.login()
            if lg.error_code != "0":
                logger.warning("Baostock 登录失败: {}", lg.error_msg)
                return {}

            rs = bs.query_stock_industry()
            if rs.error_code != "0":
                logger.warning("Baostock 行业查询失败: {}", rs.error_msg)
                bs.logout()
                return {}

            industry_map: dict[str, str] = {}
            while rs.next():
                row = rs.get_row_data()
                # row: [update_date, code_with_exchange, name, industry, source]
                raw_code = row[1]  # e.g. "sh.600519" or "sz.000858"
                industry = row[3]

                # Extract 6-digit stock code
                code = raw_code.split(".")[1][:6] if "." in raw_code else raw_code[:6]

                if code not in industry_map and industry:
                    industry_map[code] = industry

            bs.logout()

            empty_count = sum(1 for v in industry_map.values() if not v)
            logger.info(
                "Baostock: {} 只股票 ({} 有效, {} 无行业)",
                len(industry_map),
                len(industry_map) - empty_count,
                empty_count,
            )
            return industry_map

        except Exception as e:
            logger.warning("Baostock 获取行业失败: {}", e)
            with contextlib.suppress(Exception):
                bs.logout()
            return {}

    # ------------------------------------------------------------------
    # Internal: AkShare source
    # ------------------------------------------------------------------

    @staticmethod
    def _fetch_from_akshare() -> dict[str, str]:
        """Fetch industry classification from AkShare East Money sector boards.

        Iterates over 60+ industry board codes, fetching constituent stocks.
        Returns {code: board_name} mapping.

        Returns:
            {code: industry_name} mapping from East Money sector data.
        """
        try:
            import akshare as ak
        except ImportError:
            logger.debug("AkShare 未安装，跳过行业板块查询")
            return {}

        import time

        logger.info(
            "尝试 AkShare 东方财富行业板块 API ({} 个板块)...",
            len(_AKSHARE_BOARD_CODES),
        )
        industry_map: dict[str, str] = {}
        success_count = 0

        for i, bcode in enumerate(_AKSHARE_BOARD_CODES):
            try:
                df = ak.stock_board_industry_cons_em(symbol=bcode)
                if df is None or df.empty:
                    continue

                board_name = _AKSHARE_BOARD_NAMES.get(bcode, bcode)
                stock_col = next(
                    (c for c in ["代码", "code"] if c in df.columns),
                    None,
                )
                if not stock_col:
                    continue

                codes = df[stock_col].astype(str).str[:6].tolist()
                for c in codes:
                    if c not in industry_map:
                        industry_map[c] = board_name
                success_count += 1
            except Exception:
                continue

            # Rate limiting
            time.sleep(0.15)

            if (i + 1) % 20 == 0:
                logger.debug("  AkShare 行业板块进度: {}/{}", i + 1, len(_AKSHARE_BOARD_CODES))

        logger.info(
            "AkShare: {}/{} 板块成功, {} 只股票",
            success_count,
            len(_AKSHARE_BOARD_CODES),
            len(industry_map),
        )
        return industry_map

    # ------------------------------------------------------------------
    # Internal: prefix fallback
    # ------------------------------------------------------------------

    @staticmethod
    def _prefix_fallback(code: str) -> str:
        """Last-resort industry assignment based on stock code prefix.

        Args:
            code: 6-digit stock code.

        Returns:
            Industry name string (never empty).
        """
        prefix = code[:3]
        return _PREFIX_INDUSTRY.get(prefix, "其他")


# ------------------------------------------------------------------
# Convenience: one-shot function
# ------------------------------------------------------------------


def get_industry_map(
    symbols: list[str] | None = None,
    force_refresh: bool = False,
) -> dict[str, str]:
    """One-shot: get industry mapping for a list of symbols.

    Args:
        symbols: Stock codes to look up.
        force_refresh: Skip cache, re-fetch from remote sources.

    Returns:
        {symbol: industry_name} mapping.
    """
    classifier = IndustryClassifier(force_refresh=force_refresh)
    return classifier.get_mapping(symbols)
