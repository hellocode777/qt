"""Fundamental adapter — fetches financial indicators via AkShare.

Provides quarterly financial data (ROE, margins, growth rates, EPS, NAV)
for A-share stocks.  Implements BaseDataSource to isolate the Data Layer.
"""

from __future__ import annotations

import time
from datetime import date

import pandas as pd

from qp.shared.protocols.base_data_source import BaseDataSource

# AkShare column name → internal field name mapping
_COLUMN_MAP: dict[str, str] = {
    "日期": "report_date",
    "净资产收益率(%)": "ROE",
    "销售毛利率(%)": "gross_margin",
    "主营业务收入增长率(%)": "revenue_growth",
    "销售净利率(%)": "net_margin",
    "资产负债率(%)": "debt_ratio",
    "净利润增长率(%)": "net_profit_growth",
    "摊薄每股收益(元)": "EPS",
    "每股净资产_调整前(元)": "NAV",
}

# Columns to keep after renaming
_OUTPUT_COLS = [
    "report_date",
    "symbol",
    "ROE",
    "gross_margin",
    "revenue_growth",
    "net_margin",
    "debt_ratio",
    "net_profit_growth",
    "EPS",
    "NAV",
]


class FundamentalAdapter(BaseDataSource):
    """AkShare-based financial indicator adapter.

    API: akshare.stock_financial_analysis_indicator(symbol, start_year)
    Returns quarterly financial statements going back to ``start_year``.
    """

    @property
    def dataset_name(self) -> str:
        return "fundamentals"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch_raw(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        **kwargs,
    ) -> pd.DataFrame:
        """Fetch financial indicators for a list of A-share stocks.

        Args:
            start_date: Ignored (filtered by start_year internally).
            end_date: Ignored.
            **kwargs:
                symbols: List of 6-digit stock codes. Required.
                start_year: First year of data (default 2020).

        Returns:
            DataFrame with columns:
            report_date, symbol, ROE, gross_margin, revenue_growth,
            net_margin, debt_ratio, net_profit_growth, EPS, NAV
        """
        symbols: list[str] = kwargs.get("symbols") or []
        start_year: str = str(kwargs.get("start_year", 2015))

        all_rows: list[dict] = []
        total = len(symbols)
        for i, code in enumerate(symbols):
            if i > 0:
                time.sleep(0.3)  # avoid rate limiting
            try:
                rows = self._fetch_one_stock(code, start_year)
                all_rows.extend(rows)
            except Exception:
                continue

            if total > 20 and (i + 1) % 50 == 0:
                from loguru import logger

                logger.info("   Fundamental: {}/{} stocks", i + 1, total)

        if not all_rows:
            return pd.DataFrame(columns=_OUTPUT_COLS)

        df = pd.DataFrame(all_rows)
        # Fill NaN with None for nullable fields
        for col in _OUTPUT_COLS:
            if col in df.columns and col not in ("report_date", "symbol"):
                df[col] = pd.to_numeric(df[col], errors="coerce")
        return df

    def validate_schema(self, df: pd.DataFrame) -> bool:
        """Check that the DataFrame contains expected columns."""
        required_cols = {"report_date", "symbol", "ROE", "EPS", "NAV"}
        return required_cols.issubset(set(df.columns))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _fetch_one_stock(code: str, start_year: str) -> list[dict]:
        """Fetch financial indicators for a single stock."""
        import akshare as ak

        raw = ak.stock_financial_analysis_indicator(symbol=code, start_year=start_year)
        if raw is None or raw.empty:
            return []

        rows: list[dict] = []
        for _, row in raw.iterrows():
            item: dict = {"symbol": code}
            for cn_name, en_name in _COLUMN_MAP.items():
                if cn_name in raw.columns:
                    val = row[cn_name]
                    item[en_name] = None if (val is None or (isinstance(val, float) and val != val)) else val
            rows.append(item)

        return rows
