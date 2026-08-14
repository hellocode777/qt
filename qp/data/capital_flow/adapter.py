"""Capital Flow Data Adapters — AkShare-based money flow data fetching.

Implements BaseDataSource for:
  - Individual stock capital flow (主力净流入, 超大单/大单/中单/小单)
  - Northbound flow (沪深股通持股)
"""

from __future__ import annotations

import json
import os
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from loguru import logger

from qp.shared.protocols.base_data_source import BaseDataSource

_DEFAULT_CACHE_DIR = Path("data/capital_flow_cache")
_CACHE_TTL_DAYS = 3  # Capital flow data changes daily, shorter TTL

# Column renaming map (Chinese → English)
_CAPITAL_FLOW_COLUMNS = {
    "日期": "date",
    "收盘价": "close",
    "涨跌幅": "change_pct",
    "主力净流入-净额": "main_net_flow",
    "主力净流入-净占比": "main_net_flow_pct",
    "超大单净流入-净额": "super_large_net",
    "超大单净流入-净占比": "super_large_net_pct",
    "大单净流入-净额": "large_net",
    "大单净流入-净占比": "large_net_pct",
    "中单净流入-净额": "medium_net",
    "中单净流入-净占比": "medium_net_pct",
    "小单净流入-净额": "small_net",
    "小单净流入-净占比": "small_net_pct",
}

_NORTHBOUND_COLUMNS = {
    "日期": "date",
    "持股数量": "hold_shares",
    "持股市值": "hold_value",
    "持股比例": "hold_pct",
    "当日买入": "daily_buy",
    "当日卖出": "daily_sell",
    "当日成交净买入": "daily_net",
    "收盘价": "close",
}


def _market_tag(code: str) -> str:
    """Determine exchange: 'sh' for Shanghai, 'sz' for Shenzhen."""
    if code.startswith(("6", "9")):
        return "sh"
    return "sz"


class CapitalFlowAdapter(BaseDataSource):
    """Adapter for individual stock capital flow data.

    Fetches main force net inflow + order-size breakdown per stock.

    Sources:
        - ``sina`` (default): Sina MoneyFlow API (vip.stock.finance.sina.com.cn).
          Works behind GFW where eastmoney is blocked. Returns ~4000 daily rows
          per stock (main_net_flow / super_large / large / medium / small nets).
        - ``eastmoney``: AkShare eastmoney interface (main force + pct breakdown).
          May be unreachable in some networks; only use if sina is undesirable.

    Usage:
        adapter = CapitalFlowAdapter()
        raw = adapter.fetch_raw(date(2025, 1, 1), date(2025, 6, 30),
                                symbols=["600519"])
    """

    def __init__(
        self,
        cache_dir: str | Path = _DEFAULT_CACHE_DIR,
        source: str = "sina",
    ) -> None:
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        if source not in ("sina", "eastmoney"):
            raise ValueError(f"Unknown capital flow source: {source!r}")
        self._source = source

    @property
    def dataset_name(self) -> str:
        return "capital_flow"

    def fetch_raw(
        self,
        start_date: date,
        end_date: date,
        **kwargs: Any,
    ) -> pd.DataFrame:
        """Fetch capital flow data for given symbols.

        Args:
            start_date: Start date (used for filtering cached results).
            end_date: End date.
            **kwargs: Must include 'symbols' (list of 6-digit codes).

        Returns:
            DataFrame with columns: symbol, date, close, change_pct,
            main_net_flow, main_net_flow_pct, super_large_net, large_net,
            medium_net, small_net.
        """
        symbols: list[str] = kwargs.get("symbols", [])
        if not symbols:
            return pd.DataFrame()

        all_frames: list[pd.DataFrame] = []
        for symbol in symbols:
            df = self._fetch_single(symbol)
            if df is not None and not df.empty:
                all_frames.append(df)

        if not all_frames:
            return pd.DataFrame()

        result = pd.concat(all_frames, ignore_index=True)
        logger.info("CapitalFlowAdapter: {} 只股票, {} 条", len(symbols), len(result))
        return result

    def validate_schema(self, df: pd.DataFrame) -> bool:
        if df.empty:
            return True
        return "symbol" in df.columns and "main_net_flow" in df.columns

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _fetch_single(self, symbol: str) -> pd.DataFrame | None:
        """Fetch capital flow for one stock, with JSON cache.

        Uses the configured source directly (default ``sina``) — no
        eastmoney-first probing (it times out behind GFW on every stock).
        """
        # Try cache
        cached = self._load_cache(symbol)
        if cached is not None:
            return cached

        if self._source == "eastmoney":
            df = self._fetch_eastmoney(symbol)
            if df is None or df.empty:
                return None
            df = self._normalize_eastmoney_df(df, symbol)
        else:
            df = self._fetch_sina(symbol)

        if df is None or df.empty:
            return None

        # Cache
        self._save_cache(symbol, df)
        logger.debug("{} 资金流: {} 条", symbol, len(df))
        return df

    def _fetch_eastmoney(self, symbol: str) -> pd.DataFrame | None:
        """Fetch via AkShare eastmoney interface; None on failure."""
        try:
            import akshare as ak

            market = _market_tag(symbol)
            # Remove proxy env vars (AkShare uses direct eastmoney access)
            saved = {}
            for key in [
                "http_proxy",
                "https_proxy",
                "HTTP_PROXY",
                "HTTPS_PROXY",
                "all_proxy",
                "ALL_PROXY",
            ]:
                saved[key] = os.environ.pop(key, None)

            try:
                df = ak.stock_individual_fund_flow(stock=symbol, market=market)
            except TypeError:
                df = ak.stock_individual_fund_flow(stock=symbol)
            finally:
                # Restore proxy env
                for key, val in saved.items():
                    if val is not None:
                        os.environ[key] = val
        except Exception as e:
            logger.debug("{} 东财资金流获取失败: {}", symbol, e)
            return None

        if df is None or df.empty:
            return None
        return df

    @staticmethod
    def _normalize_eastmoney_df(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """Rename eastmoney Chinese columns + coerce numerics."""
        df = df.rename(columns=_CAPITAL_FLOW_COLUMNS)
        df["symbol"] = symbol
        numeric_cols = [
            "close",
            "change_pct",
            "main_net_flow",
            "main_net_flow_pct",
            "super_large_net",
            "super_large_net_pct",
            "large_net",
            "large_net_pct",
            "medium_net",
            "medium_net_pct",
            "small_net",
            "small_net_pct",
        ]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        return df

    def _fetch_sina(self, symbol: str) -> pd.DataFrame | None:
        """Fetch capital flow from Sina MoneyFlow API (GFW fallback).

        API: MoneyFlow.ssl_qsfx_lscjfb
        Fields: opendate, trade, changeratio, netamount, ratioamount,
        r0_net (超大单), r1_net (大单), r2_net (中单), r3_net (小单).

        Paged (num=100) to cover the full requested history.
        """
        import json

        market = _market_tag(symbol)
        prefix = f"{market}{symbol}"
        base_url = (
            "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
            "MoneyFlow.ssl_qsfx_lscjfb"
        )

        rows: list[dict[str, Any]] = []
        try:
            page = 1
            while page <= 100:  # safety cap
                resp = requests.get(
                    base_url,
                    params={
                        "page": page,
                        "num": 100,
                        "sort": "opendate",
                        "asc": 0,
                        "daima": prefix,
                    },
                    timeout=15,
                )
                resp.raise_for_status()
                batch = json.loads(resp.text)
                if not batch:
                    break
                rows.extend(batch)
                if len(batch) < 100:
                    break
                page += 1
        except Exception as e:
            logger.debug("{} 新浪资金流获取失败: {}", symbol, e)
            return None

        if not rows:
            return None

        df = pd.DataFrame(rows)
        df = df.rename(
            columns={
                "opendate": "date",
                "trade": "close",
                "changeratio": "change_pct",
                "netamount": "main_net_flow",
                "ratioamount": "main_net_flow_pct",
                "r0_net": "super_large_net",
                "r1_net": "large_net",
                "r2_net": "medium_net",
                "r3_net": "small_net",
            }
        )
        df["symbol"] = symbol
        for col in [
            "close",
            "change_pct",
            "main_net_flow",
            "main_net_flow_pct",
            "super_large_net",
            "large_net",
            "medium_net",
            "small_net",
        ]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        return df

    def _cache_path(self, symbol: str) -> Path:
        return self._cache_dir / f"{symbol}.json"

    def _load_cache(self, symbol: str) -> pd.DataFrame | None:
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
                data = json.load(f)
            if not data:
                return None
            return pd.DataFrame(data)
        except (json.JSONDecodeError, OSError):
            return None

    def _save_cache(self, symbol: str, df: pd.DataFrame) -> None:
        path = self._cache_path(symbol)
        try:
            raw_json: str = df.to_json(orient="records", force_ascii=False)  # type: ignore[assignment]
            records = json.loads(raw_json)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(records, f, ensure_ascii=False, default=str)
        except OSError as e:
            logger.debug("{} 资金流缓存保存失败: {}", symbol, e)


class NorthboundAdapter(BaseDataSource):
    """AkShare adapter for northbound (沪深股通) holding data.

    Fetches HK-to-mainland capital holdings per stock.

    Usage:
        adapter = NorthboundAdapter()
        raw = adapter.fetch_raw(date(2025, 1, 1), date(2025, 6, 30),
                                symbols=["600519"])
    """

    def __init__(self, cache_dir: str | Path = _DEFAULT_CACHE_DIR) -> None:
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    @property
    def dataset_name(self) -> str:
        return "northbound"

    def fetch_raw(
        self,
        start_date: date,
        end_date: date,
        **kwargs: Any,
    ) -> pd.DataFrame:
        symbols: list[str] = kwargs.get("symbols", [])
        if not symbols:
            return pd.DataFrame()

        all_frames: list[pd.DataFrame] = []
        for symbol in symbols:
            df = self._fetch_single(symbol)
            if df is not None and not df.empty:
                all_frames.append(df)

        if not all_frames:
            return pd.DataFrame()

        return pd.concat(all_frames, ignore_index=True)

    def validate_schema(self, df: pd.DataFrame) -> bool:
        if df.empty:
            return True
        return "symbol" in df.columns and "hold_pct" in df.columns

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _fetch_single(self, symbol: str) -> pd.DataFrame | None:
        cached = self._load_cache(symbol)
        if cached is not None:
            return cached

        try:
            import akshare as ak

            df = ak.stock_hsgt_individual_em(symbol=symbol)
        except Exception as e:
            logger.debug("{} 北向资金获取失败: {}", symbol, e)
            return None

        if df is None or df.empty:
            return None

        df = df.rename(columns=_NORTHBOUND_COLUMNS)
        df["symbol"] = symbol

        for col in ["hold_pct", "daily_net", "hold_value", "close"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        self._save_cache(symbol, df)
        logger.debug("{} 北向资金: {} 条", symbol, len(df))
        return df

    def _cache_path(self, symbol: str) -> Path:
        return self._cache_dir / f"northbound_{symbol}.json"

    def _load_cache(self, symbol: str) -> pd.DataFrame | None:
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
                data = json.load(f)
            if not data:
                return None
            return pd.DataFrame(data)
        except (json.JSONDecodeError, OSError):
            return None

    def _save_cache(self, symbol: str, df: pd.DataFrame) -> None:
        path = self._cache_path(symbol)
        try:
            raw_json: str = df.to_json(orient="records", force_ascii=False)  # type: ignore[assignment]
            records = json.loads(raw_json)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(records, f, ensure_ascii=False, default=str)
        except OSError as e:
            logger.debug("{} 北向缓存保存失败: {}", symbol, e)
