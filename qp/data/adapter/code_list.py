"""Shared stock code list for data adapters.

Provides the canonical list of A-share main-board codes so that every
adapter (Sina, Tencent, etc.) works from the same universe.
"""

from __future__ import annotations

import json

from qp.shared.paths import MAIN_BOARD_CODES

# Default set of liquid large-cap stocks — used for quick test / demo runs.
# The full main-board list (~3000 stocks) is loaded from data/main_board_codes.json.
CORE_SYMBOLS: list[str] = [
    "000001",  # 平安银行
    "000002",  # 万科A
    "000333",  # 美的集团
    "000651",  # 格力电器
    "000858",  # 五粮液
    "002415",  # 海康威视
    "002475",  # 立讯精密
    "300750",  # 宁德时代
    "600000",  # 浦发银行
    "600036",  # 招商银行
    "600276",  # 恒瑞医药
    "600519",  # 贵州茅台
    "600585",  # 海螺水泥
    "600887",  # 伊利股份
    "601012",  # 隆基绿能
    "601166",  # 兴业银行
    "601318",  # 中国平安
    "601888",  # 中国中免
]

_MAIN_BOARD_CACHE: list[str] | None = None


def get_main_board_codes() -> list[str]:
    """Return the full main-board stock code list (~3000 stocks).

    Loaded once from ``data/main_board_codes.json`` and cached.
    Falls back to ``CORE_SYMBOLS`` if the file is missing.
    """
    global _MAIN_BOARD_CACHE
    if _MAIN_BOARD_CACHE is not None:
        return _MAIN_BOARD_CACHE

    path = MAIN_BOARD_CODES
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list) and len(data) > 0:
                _MAIN_BOARD_CACHE = [str(c) for c in data]
                return _MAIN_BOARD_CACHE
        except (json.JSONDecodeError, OSError):
            pass

    _MAIN_BOARD_CACHE = list(CORE_SYMBOLS)
    return _MAIN_BOARD_CACHE
