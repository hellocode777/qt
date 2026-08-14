"""Tencent adapter — fetches A-share daily data from Tencent Finance API.

Uses web.ifzq.gtimg.cn as the primary data source (TDR-001).
More stable than AkShare in restricted network environments.
Implements BaseDataSource to isolate the Data Layer from the specific provider.

⚠️ 复权状态约定（2026-08-14, critical）:
  本 adapter 只取 **不复权原始价**（kline/kline 接口的 `day` 字段）。
  复权一律在计算层用 adj_factor 表（akshare qfq-factor）按需调整。

  ⛔ 禁止使用 `fqkline/get` + `qfq` 接口（历史负价格坏数据 bug，
  600438 2018-10 曾返回 -0.068 等负价格，污染 daily_price_latest）。
  该接口在本项目已废弃，见 docs/architecture/data/DP-002-data-layer.md。
"""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta

import pandas as pd
import requests

from qp.data.adapter.code_list import CORE_SYMBOLS
from qp.shared.protocols.base_data_source import BaseDataSource


class TencentAdapter(BaseDataSource):
    """Tencent Finance API-based A-share daily price data adapter.

    API: https://ifzq.gtimg.cn/appstock/app/kline/kline  (raw `day` series)
    Each request returns up to ~730 trading days of daily K-line data.
    Longer periods are automatically split into segments.

    ⛔ Do NOT use fqkline/get + qfq (deprecated — see module docstring).
    """

    DEFAULT_SYMBOLS: list[str] = CORE_SYMBOLS

    @property
    def dataset_name(self) -> str:
        return "daily_price"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch_raw(self, start_date: date, end_date: date, **kwargs) -> pd.DataFrame:
        """Fetch daily price data for a list of A-share stocks via Tencent API.

        Args:
            start_date: Start date (inclusive).
            end_date: End date (inclusive).
            **kwargs:
                symbols: List of 6-digit stock codes. Uses DEFAULT_SYMBOLS if omitted.

        Returns:
            Raw DataFrame with columns matching AkShare format:
            日期, 股票代码, 开盘, 收盘, 最高, 最低, 成交量, symbol
        """
        symbols: list[str] = kwargs.get("symbols") or self.DEFAULT_SYMBOLS

        start_str = start_date.strftime("%Y-%m-%d")
        end_str = end_date.strftime("%Y-%m-%d")

        s_dt = datetime(start_date.year, start_date.month, start_date.day)
        e_dt = datetime(end_date.year, end_date.month, end_date.day)

        n_total = len(symbols)
        all_rows: list[dict] = []
        for i, code in enumerate(symbols):
            if i > 0:
                time.sleep(0.3)  # avoid rate limiting (WAF blocks below ~0.2s)
            try:
                tc = self._code_to_tencent(code)
                rows = self._fetch_one_stock(tc, code, s_dt, e_dt)
                all_rows.extend(rows)
            except Exception:
                pass
            # Progress: print every 50 stocks or at the end
            # 豁免 print() 硬规则：终端进度条（stderr + \r 刷新），logger 无法做覆盖式进度 UI
            if (i + 1) % 50 == 0 or i == n_total - 1:
                pct = (i + 1) / n_total * 100
                n_rows = len(all_rows)
                print(
                    f"\r  [{pct:5.1f}%] {i + 1}/{n_total} stocks  |  {n_rows:,} rows",
                    end="",
                    file=__import__("sys").stderr,
                    flush=True,
                )

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
    def _code_to_tencent(code: str) -> str:
        """Convert 6-digit A-share code to Tencent market-prefixed format.

        Shanghai: 600xxx, 601xxx, 603xxx, 605xxx, 688xxx → shXXXXXX
        Shenzhen: 000xxx, 001xxx, 002xxx, 003xxx, 300xxx → szXXXXXX
        """
        if code.startswith(("600", "601", "603", "605", "688")):
            return f"sh{code}"
        if code.startswith(("000", "001", "002", "003", "300")):
            return f"sz{code}"
        return code

    def _fetch_one_stock(
        self,
        tc: str,
        code: str,
        start_dt: datetime,
        end_dt: datetime,
    ) -> list[dict]:
        """Fetch one stock's full history, handling pagination via date segments.

        The Tencent API returns at most ~730 records per call.  Longer periods
        are split into ~2.5-year segments automatically.
        """
        url = "https://ifzq.gtimg.cn/appstock/app/kline/kline"  # raw (unadjusted) day series
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Referer": "https://finance.qq.com/",
        }

        segments = self._build_segments(start_dt, end_dt)
        all_rows: list[dict] = []

        for i, (seg_start, seg_end) in enumerate(segments):
            if i > 0:
                time.sleep(0.2)  # gap between segments for same stock
            # NO qfq suffix: `kline/kline` without adjustment returns raw `day`
            # prices. fqkline/get+qfq is BANNED (negative-price corruption bug).
            param = f"{tc},day,{seg_start},{seg_end},2000"
            try:
                r = requests.get(url, params={"param": param}, headers=headers, timeout=30)
                if not r.text or not r.text.strip():
                    continue
                data = r.json()
            except requests.RequestException:
                continue
            except ValueError:
                # Non-JSON response
                continue

            klines = self._extract_klines(data, tc)
            if not klines:
                continue

            for row in klines:
                try:
                    all_rows.append(
                        {
                            "日期": str(row[0])[:10],
                            "股票代码": code,
                            "开盘": float(row[1]),
                            "收盘": float(row[2]),
                            "最高": float(row[3]),
                            "最低": float(row[4]),
                            "成交量": float(row[5]),
                            "symbol": code,
                        }
                    )
                except (ValueError, IndexError):
                    continue

        return all_rows

    @staticmethod
    def _extract_klines(data: dict, tc: str) -> list | None:
        """Extract K-line array from the nested Tencent JSON response.

        Response structure (kline/kline, NO adjustment):
          {"data": {"sh600519": {"day": [...]}}}

        Only `day` (raw, unadjusted) is used. `qfqday`/`hfqday` keys belong
        to the fqkline endpoint which is BANNED (negative-price corruption).
        """
        symbol_data = data.get("data", {}).get(tc, {})
        return symbol_data.get("day") or None

    @staticmethod
    def _build_segments(start: datetime, end: datetime) -> list[tuple[str, str]]:
        """Split a date range into ~900-day (natural) segments."""
        segments: list[tuple[str, str]] = []
        cur = start
        while cur < end:
            nxt = cur + timedelta(days=900)
            if nxt >= end:
                segments.append((cur.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")))
            else:
                nxt_end = nxt - timedelta(days=1)
                segments.append((cur.strftime("%Y-%m-%d"), nxt_end.strftime("%Y-%m-%d")))
            cur = nxt
        return segments
