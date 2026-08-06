"""AkShare Fundamental Data Adapter — fetches financial statement data.

Implements BaseDataSource to isolate the Data Layer from AkShare.
Research code must never call akshare directly (ADR-013).
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from loguru import logger

from qp.shared.protocols.base_data_source import BaseDataSource

# ------------------------------------------------------------------
# Column mapping: AkShare THS Chinese → unified English factor names
# ------------------------------------------------------------------

_COLUMN_MAP: dict[str, str] = {
    "净资产收益率": "ROE",
    "净资产收益率-摊薄": "ROE_diluted",
    "营业总收入": "revenue",
    "营业总收入同比增长率": "revenue_growth",
    "净利润": "net_profit",
    "净利润同比增长率": "net_profit_growth",
    "销售毛利率": "gross_margin",
    "销售净利率": "net_margin",
    "基本每股收益": "EPS",
    "每股净资产": "NAV",
    "资产负债率": "debt_ratio",
    "每股经营现金流": "cashflow_per_share",
    "扣非净利润": "deducted_profit",
    "扣非净利润同比增长率": "deducted_profit_growth",
}

# AkShare columns that may contain the actual publish date
_PUBLISH_DATE_COLS = ["notice_date", "发布日期", "公告日期"]

# Cache TTL (7 days for financial data)
_CACHE_TTL_DAYS = 7
_DEFAULT_CACHE_DIR = Path("data/fundamental_cache")

# Estimate disclosure deadlines by report month
# A-share rules:
#   Annual (12-31) → by April 30 next year
#   Q1 (03-31)     → by April 30 same year
#   Semi-annual (06-30) → by Aug 31
#   Q3 (09-30)     → by Oct 31
# Conservative: use 5 days before deadline


def _estimate_publish_date(report_date: pd.Timestamp) -> pd.Timestamp:
    """Estimate financial report publish date when actual date is unavailable."""
    y, m = report_date.year, report_date.month
    if m == 12:
        return pd.Timestamp(f"{y + 1}-04-25")  # type: ignore[reportReturnType]
    if m == 3:
        return pd.Timestamp(f"{y}-04-25")  # type: ignore[reportReturnType]
    if m == 6:
        return pd.Timestamp(f"{y}-08-26")  # type: ignore[reportReturnType]
    if m == 9:
        return pd.Timestamp(f"{y}-10-26")  # type: ignore[reportReturnType]
    return report_date


class FundamentalAdapter(BaseDataSource):
    """AkShare-based fundamental (financial statement) data adapter.

    Fetches historical financial indicators for A-share stocks via
    AkShare's THS (同花顺) financial abstract API.

    Usage:
        adapter = FundamentalAdapter()
        raw = adapter.fetch_raw(date(2024, 1, 1), date(2026, 7, 20), symbols=["600519"])
        # → pd.DataFrame with publish_date column for PIT filtering
    """

    def __init__(self, cache_dir: str | Path = _DEFAULT_CACHE_DIR) -> None:
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    @property
    def dataset_name(self) -> str:
        return "fundamental_raw"

    def fetch_raw(
        self,
        start_date: date,
        end_date: date,
        **kwargs: Any,
    ) -> pd.DataFrame:
        """Fetch fundamental data for given symbols.

        Args:
            start_date: Not used for fundamental (report-date based).
            end_date: Not used for fundamental.
            **kwargs: Must include 'symbols' (list of 6-digit codes).

        Returns:
            DataFrame with columns: symbol, report_date, publish_date,
            ROE, revenue_growth, gross_margin, net_margin, net_profit_growth,
            debt_ratio, EPS, NAV, cashflow_per_share.
        """
        symbols: list[str] = kwargs.get("symbols", [])
        if not symbols:
            logger.warning("FundamentalAdapter.fetch_raw: 未提供 symbols")
            return pd.DataFrame()

        all_frames: list[pd.DataFrame] = []
        for symbol in symbols:
            df = self._fetch_single(symbol)
            if df is not None and not df.empty:
                all_frames.append(df)

        if not all_frames:
            return pd.DataFrame()

        result = pd.concat(all_frames, ignore_index=True)
        logger.info(
            "FundamentalAdapter: {} 只股票, {} 条记录",
            len(symbols),
            len(result),
        )
        return result

    def validate_schema(self, df: pd.DataFrame) -> bool:
        """Check that the DataFrame contains expected fundamental columns."""
        if df.empty:
            return True
        required = {"symbol", "report_date", "publish_date"}
        return required.issubset(set(df.columns))

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _fetch_single(self, symbol: str) -> pd.DataFrame | None:
        """Fetch fundamental data for one stock, with JSON cache."""
        # Try cache
        cached = self._load_cache(symbol)
        if cached is not None:
            return cached

        # Fetch from AkShare
        try:
            import akshare as ak

            df = ak.stock_financial_abstract_ths(symbol=symbol)
        except Exception as e:
            logger.debug("{} 基本面获取失败: {}", symbol, e)
            return None

        if df is None or df.empty:
            logger.debug("{} 基本面数据为空", symbol)
            return None

        # Extract publish date
        publish_dates: pd.Series | None = None
        for col in _PUBLISH_DATE_COLS:
            if col in df.columns:
                publish_dates = pd.to_datetime(df[col], errors="coerce")
                logger.debug("  {} 使用实际发布日期列: {}", symbol, col)
                break

        # Rename columns
        df = df.rename(columns={k: v for k, v in _COLUMN_MAP.items() if k in df.columns})

        # Keep only report date + mapped columns
        keep_cols = ["报告期"] + [v for v in _COLUMN_MAP.values() if v in df.columns]
        df = df[[c for c in keep_cols if c in df.columns]]

        # Set report_date index
        df["报告期"] = pd.to_datetime(df["报告期"])
        report_dates = df["报告期"].copy()
        df = df.set_index("报告期").sort_index()

        # Convert numeric columns (strip %, 亿, 万)
        for col in df.columns:
            if col == "报告期":
                continue
            try:
                df[col] = df[col].apply(
                    lambda x: (
                        float(
                            str(x).replace("%", "").replace("亿", "").replace("万", "").strip(),
                        )
                        if x is not None and x is not False and str(x).strip()
                        else np.nan
                    ),
                )
            except Exception:
                continue

        # Attach publish_date
        if publish_dates is not None:
            df["publish_date"] = publish_dates.values
        else:
            # Estimate from report_date
            df["publish_date"] = df.index.map(_estimate_publish_date)  # type: ignore[arg-type]

        # Reset index to make report_date a column
        df = df.reset_index().rename(columns={"报告期": "report_date", "index": "report_date"})
        if "report_date" not in df.columns:
            df["report_date"] = report_dates.values  # type: ignore[reportAttributeAccessIssue]

        df["symbol"] = symbol

        # Cache
        self._save_cache(symbol, df)

        logger.info(
            "{} 基本面: {} 期 [{}-{}]",
            symbol,
            len(df),
            str(df["report_date"].min())[:10],
            str(df["report_date"].max())[:10],
        )
        return df

    def _cache_path(self, symbol: str) -> Path:
        return self._cache_dir / f"{symbol}.json"

    def _load_cache(self, symbol: str) -> pd.DataFrame | None:
        """Load from JSON cache (7-day TTL)."""
        path = self._cache_path(symbol)
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
            return None

        try:
            with open(path, encoding="utf-8") as f:
                data: list[dict[str, Any]] = json.load(f)
            if not data:
                return None
            df = pd.DataFrame(data)
            if "report_date" in df.columns:
                df["report_date"] = pd.to_datetime(df["report_date"])
            if "publish_date" in df.columns:
                df["publish_date"] = pd.to_datetime(df["publish_date"], errors="coerce")
            logger.debug("{} 基本面(缓存): {} 期", symbol, len(df))
            return df
        except (json.JSONDecodeError, OSError, ValueError) as e:
            logger.debug("{} 基本面缓存加载失败: {}", symbol, e)
            return None

    def _save_cache(self, symbol: str, df: pd.DataFrame) -> None:
        """Save to JSON cache."""
        path = self._cache_path(symbol)
        try:
            records = df.copy()
            # Convert timestamps to strings for JSON
            for col in records.columns:
                if pd.api.types.is_datetime64_any_dtype(records[col]):
                    records[col] = records[col].dt.strftime("%Y-%m-%d")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(records.to_dict("records"), f, ensure_ascii=False, default=str)
        except OSError as e:
            logger.debug("{} 基本面缓存保存失败: {}", symbol, e)
