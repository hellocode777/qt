"""Demo adapter — generates synthetic market data for testing.

Used when live data sources are unavailable (e.g. network restrictions).
Returns Polars DataFrames for native integration with the cleaning pipeline.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import polars as pl

from qp.shared.protocols.base_data_source import BaseDataSource


class DemoAdapter(BaseDataSource):
    """Synthetic data generator for Walking Skeleton testing."""

    # Realistic A-share stock pool
    DEFAULT_SYMBOLS = [
        "000001",  # 平安银行
        "000002",  # 万科A
        "000858",  # 五粮液
        "002415",  # 海康威视
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

    @property
    def dataset_name(self) -> str:
        return "daily_price"

    def fetch_raw(self, start_date: date, end_date: date, **kwargs) -> pl.DataFrame:
        """Generate synthetic OHLCV data for testing.

        Uses geometric Brownian motion with stock-specific drift and volatility.
        Returns a Polars DataFrame for native pipeline integration.

        Args:
            start_date: Start date (inclusive).
            end_date: End date (inclusive).
            **kwargs:
                symbols: List of 6-digit stock codes. Uses DEFAULT_SYMBOLS if omitted.

        Returns:
            Polars DataFrame with columns matching the AkShare format:
            日期, 股票代码, 开盘, 收盘, 最高, 最低, 成交量, symbol
        """
        symbols = kwargs.get("symbols") or self.DEFAULT_SYMBOLS
        np.random.seed(42)  # Deterministic output

        # Generate date range (weekdays only)
        dates: list[date] = []
        current = start_date
        while current <= end_date:
            if current.weekday() < 5:  # Mon-Fri
                dates.append(current)
            current += timedelta(days=1)

        rows: list[dict] = []
        for symbol in symbols:
            # Stock-specific parameters (makes results interesting)
            symbol_seed = hash(symbol) % 10000
            rng = np.random.default_rng(symbol_seed)
            drift = rng.uniform(-0.0003, 0.0008)  # daily drift
            vol = rng.uniform(0.01, 0.03)  # daily volatility
            base_price = rng.uniform(5, 200)

            price = base_price
            for d in dates:
                daily_ret = drift + vol * rng.normal()
                price = price * (1 + daily_ret)
                if price < 1:
                    price = 1

                open_price = price * (1 + rng.uniform(-0.01, 0.01))
                high = max(open_price, price) * (1 + abs(rng.normal(0, 0.005)))
                low = min(open_price, price) * (1 - abs(rng.normal(0, 0.005)))
                volume = int(rng.integers(100_000, 50_000_000))

                rows.append(
                    {
                        "日期": d.strftime("%Y-%m-%d"),
                        "股票代码": symbol,
                        "开盘": round(open_price, 2),
                        "收盘": round(price, 2),
                        "最高": round(high, 2),
                        "最低": round(low, 2),
                        "成交量": float(volume),
                        "symbol": symbol,
                    }
                )

        return pl.DataFrame(rows)

    def validate_schema(self, df: pd.DataFrame | pl.DataFrame) -> bool:
        """Check that the DataFrame contains expected columns."""
        required_cols = {"日期", "开盘", "收盘", "最高", "最低", "成交量", "symbol"}
        return required_cols.issubset(set(df.columns))
