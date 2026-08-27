"""Sina adapter — fetches A-share daily data from Sina Finance API.

Uses quotes.sina.cn as the data source.  Provides an alternative to the
Tencent adapter when Tencent data is delayed or unavailable.

Implements BaseDataSource to isolate the Data Layer from the specific provider.
"""

from __future__ import annotations

import time
from datetime import date

import pandas as pd
import requests

from qp.data.adapter.code_list import CORE_SYMBOLS
from qp.shared.protocols.base_data_source import BaseDataSource
from qp.shared.time import fmt_date

try:
    from loguru import logger
except ImportError:
    import logging

    logger = logging.getLogger(__name__)


class SinaAdapter(BaseDataSource):
    """Sina Finance API-based A-share daily price data adapter.

    API: https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData
    Returns up to ~1500 trading days of daily K-line data per request.
    """

    DEFAULT_SYMBOLS: list[str] = CORE_SYMBOLS

    # Sina API returns at most ~1500 records per call.
    _MAX_DATALEN = 1500

    @property
    def dataset_name(self) -> str:
        return "daily_price"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch_raw(self, start_date: date, end_date: date, **kwargs) -> pd.DataFrame:
        """Fetch daily price data for a list of A-share stocks via Sina API.

        Args:
            start_date: Start date (inclusive).
            end_date: End date (inclusive).
            **kwargs:
                symbols: List of 6-digit stock codes. Uses DEFAULT_SYMBOLS if omitted.

        Returns:
            Raw DataFrame with columns:
            日期, 股票代码, 开盘, 收盘, 最高, 最低, 成交量, symbol
        """
        symbols: list[str] = kwargs.get("symbols") or self.DEFAULT_SYMBOLS  # type: ignore[assignment]

        start_str = fmt_date(start_date)
        end_str = fmt_date(end_date)

        all_rows: list[dict] = []
        total = len(symbols)
        for i, code in enumerate(symbols):
            if i > 0:
                time.sleep(0.05)  # avoid rate limiting (0.05s = 20 req/s)
            try:
                sc = self._code_to_sina(code)
                rows = self._fetch_one_stock(sc, code)
                all_rows.extend(rows)
            except Exception:
                continue
            # Progress logging for large symbol lists
            if total > 50 and (i + 1) % 100 == 0:
                logger.info("   Sina: {}/{} stocks fetched", i + 1, total)

        if not all_rows:
            return pd.DataFrame()

        df = pd.DataFrame(all_rows)
        # Filter to exact date range
        mask = (df["日期"] >= start_str) & (df["日期"] <= end_str)
        return df.loc[mask].reset_index(drop=True)  # type: ignore[return-value]

    def validate_schema(self, df: pd.DataFrame) -> bool:
        """Check that the DataFrame contains expected columns."""
        required_cols = {"日期", "开盘", "收盘", "最高", "最低", "成交量", "symbol"}
        return required_cols.issubset(set(df.columns))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _code_to_sina(code: str) -> str:
        """Convert 6-digit A-share code to Sina market-prefixed format.

        Shanghai: 600xxx, 601xxx, 603xxx, 605xxx, 688xxx → shXXXXXX
        Shenzhen: 000xxx, 001xxx, 002xxx, 003xxx, 300xxx → szXXXXXX
        """
        if code.startswith(("600", "601", "603", "605", "688")):
            return f"sh{code}"
        if code.startswith(("000", "001", "002", "003", "300")):
            return f"sz{code}"
        return code

    def _fetch_one_stock(self, sc: str, code: str) -> list[dict]:
        """Fetch one stock's full history from Sina API.

        The Sina API returns the most recent N records.  We request
        ``_MAX_DATALEN`` records and rely on the caller's date filter.
        """
        url = "https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Referer": "https://finance.sina.com.cn/",
        }
        params = {
            "symbol": sc,
            "scale": "240",  # daily K-line
            "ma": "no",
            "datalen": str(self._MAX_DATALEN),
        }

        try:
            r = requests.get(url, params=params, headers=headers, timeout=30)
            if not r.text or not r.text.strip():
                return []
            data = r.json()
        except requests.RequestException:
            return []
        except ValueError:
            return []

        if not data or not isinstance(data, list):
            return []

        rows: list[dict] = []
        for item in data:
            try:
                rows.append(
                    {
                        "日期": str(item["day"])[:10],
                        "股票代码": code,
                        "开盘": float(item["open"]),
                        "收盘": float(item["close"]),
                        "最高": float(item["high"]),
                        "最低": float(item["low"]),
                        "成交量": float(item["volume"]),
                        "symbol": code,
                    }
                )
            except (ValueError, KeyError, TypeError):
                continue

        return rows
