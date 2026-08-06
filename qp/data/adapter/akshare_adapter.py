"""AKShare adapter — China A-share market data source (TDR-001).

Implements BaseDataSource to isolate the Data Layer from the specific provider.
Research code must never call akshare directly (ADR-013, ADR-017).
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from qp.shared.protocols.base_data_source import BaseDataSource


class AKShareAdapter(BaseDataSource):
    """AKShare-based A-share daily price data adapter."""

    @property
    def dataset_name(self) -> str:
        return "daily_price"

    def fetch_raw(self, start_date: date, end_date: date, **kwargs) -> pd.DataFrame:
        """Fetch daily price data for all A-share stocks via AkShare.

        Args:
            start_date: Start date (inclusive).
            end_date: End date (inclusive).
            **kwargs: Additional args (unused for this adapter).

        Returns:
            Raw DataFrame with A-share daily OHLCV data.
        """
        import akshare as ak

        frames: list[pd.DataFrame] = []
        symbols = kwargs.get("symbols")

        if symbols is None:
            # Fetch all A-share stock list
            try:
                stock_info = ak.stock_zh_a_spot_em()
                symbols = stock_info["代码"].tolist()[:50]  # Limit for walking skeleton
            except Exception:
                symbols = ["000001", "000002", "600000", "600036", "601318"]

        for symbol in symbols:
            try:
                df = ak.stock_zh_a_hist(
                    symbol=symbol,
                    period="daily",
                    start_date=start_date.strftime("%Y%m%d"),
                    end_date=end_date.strftime("%Y%m%d"),
                    adjust="qfq",  # 前复权
                )
                if not df.empty:
                    df["symbol"] = symbol
                    frames.append(df)
            except Exception:
                continue

        if not frames:
            return pd.DataFrame()

        return pd.concat(frames, ignore_index=True)

    def validate_schema(self, df: pd.DataFrame) -> bool:
        """Check that the DataFrame contains expected columns."""
        required_cols = {"日期", "开盘", "收盘", "最高", "最低", "成交量", "symbol"}
        return required_cols.issubset(set(df.columns))
