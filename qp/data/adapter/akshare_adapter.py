"""AKShare adapter — China A-share market data source (TDR-001).

Implements BaseDataSource to isolate the Data Layer from the specific provider.
Research code must never call akshare directly (ADR-013, ADR-017).

⚠️ 复权状态约定（2026-08-14, critical）:
  1. fetch_raw() 只返回 **不复权原始价**（adjust=""）。
  2. 复权因子通过 get_adjust_factor() 单独获取（adjust="qfq-factor"），
     得到「除权日 → 累积前复权倍数」表。
  3. 复权价换算公式（已实测验证 600438 2018-05~10）:
        close_qfq = close_raw / qfq_factor(该日适用的最近除权日因子)
     akshare 返回的 qfq_factor 越大表示除权次数/幅度越多（历史价被
     摊薄得越厉害），最新除权日 factor=1.0（原始价=前复权价）。
  4. 生产价格表只存原始价，复权一律在计算层用因子表按需调整。

  ⛔ 禁止在 fetch_raw 中使用 adjust="qfq"/"hfq"（会把复权价混入原始价
  表，导致 daily_price_latest 复权状态不一致 — 2026-08-14 事故根因）。
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from qp.shared.protocols.base_data_source import BaseDataSource
from qp.shared.time import today_cn


class AKShareAdapter(BaseDataSource):
    """AKShare-based A-share daily price data adapter."""

    @property
    def dataset_name(self) -> str:
        return "daily_price"

    def fetch_raw(self, start_date: date, end_date: date, **kwargs) -> pd.DataFrame:
        """Fetch RAW (unadjusted) daily price data via AkShare.

        Args:
            start_date: Start date (inclusive).
            end_date: End date (inclusive).
            **kwargs:
                symbols: List of 6-digit stock codes.

        Returns:
            Raw DataFrame with A-share daily OHLCV data (unadjusted).
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
                    adjust="",  # 不复权原始价 (CRITICAL — do not change to qfq/hfq)
                )
                if not df.empty:
                    df["symbol"] = symbol
                    frames.append(df)
            except Exception:
                continue

        if not frames:
            return pd.DataFrame()

        return pd.concat(frames, ignore_index=True)

    def get_adjust_factor(
        self,
        symbols: list[str],
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> pd.DataFrame:
        """Fetch forward-adjustment factors (qfq-factor) for the given symbols.

        Each row is an ex-date with the cumulative qfq factor valid from that
        date onward (latest ex-date has factor = 1.0).

        Returns:
            DataFrame with columns [symbol, ex_date, qfq_factor].
            To get the qfq price on date D:
                factor = qfq_factor[ex_date = max(ex_date <= D)]
                close_qfq = close_raw / factor
        """
        import akshare as ak

        rows: list[dict] = []
        for symbol in symbols:
            market = "sh" if symbol.startswith(("6", "9")) else "sz"
            sym_key = f"{market}{symbol}"
            try:
                df = ak.stock_zh_a_daily(
                    symbol=sym_key,
                    start_date=(start_date or date(1990, 1, 1)).strftime("%Y%m%d"),
                    end_date=(end_date or today_cn()).strftime("%Y%m%d"),
                    adjust="qfq-factor",
                )
                if df is None or df.empty:
                    continue
                # Vectorized (avoid per-row .iterrows() for pyright + speed)
                dates = df["date"].astype(str).str[:10].tolist()
                factors = [float(v) for v in df["qfq_factor"].tolist()]
                for i in range(len(dates)):
                    rows.append(
                        {
                            "symbol": symbol,
                            "ex_date": dates[i],
                            "qfq_factor": factors[i],
                        }
                    )
            except Exception:
                continue

        return pd.DataFrame(rows, columns=["symbol", "ex_date", "qfq_factor"])

    def validate_schema(self, df: pd.DataFrame) -> bool:
        """Check that the DataFrame contains expected columns."""
        required_cols = {"日期", "开盘", "收盘", "最高", "最低", "成交量", "symbol"}
        return required_cols.issubset(set(df.columns))
