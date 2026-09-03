# pyright: reportOperatorIssue=false, reportAttributeAccessIssue=false, reportOptionalSubscript=false, reportOptionalOperand=false, reportArgumentType=false, reportReturnType=false, reportIncompatibleMethodOverride=false
"""Tests for qp.data.calendar + qp.data.industry (previously 0% coverage)."""

from __future__ import annotations

import json
import tempfile
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from qp.data.calendar.calendar import TradingCalendar
from qp.data.industry.cache import IndustryCache
from qp.data.industry.classifier import (
    _PREFIX_INDUSTRY,
    CSRC_CATEGORY_MAP,
    IndustryClassifier,
    get_industry_map,
)


class TestTradingCalendar:
    def test_get_trading_days_weekend_filter(self) -> None:
        """Fallback path (no akshare): Mon-Fri only."""
        cal = TradingCalendar()
        start, end = date(2026, 7, 13), date(2026, 7, 19)  # Mon → Sun
        with patch("akshare.tool_trade_date_hist_sina", side_effect=Exception("no net")):
            days = cal.get_trading_days(start, end)
        assert days == [
            date(2026, 7, 13),
            date(2026, 7, 14),
            date(2026, 7, 15),
            date(2026, 7, 16),
            date(2026, 7, 17),
        ]

    def test_get_trading_days_single_day_weekend(self) -> None:
        cal = TradingCalendar()
        with patch("akshare.tool_trade_date_hist_sina", side_effect=Exception("no net")):
            days = cal.get_trading_days(date(2026, 7, 18), date(2026, 7, 18))  # Saturday
        assert days == []

    def test_is_trading_day(self) -> None:
        cal = TradingCalendar()
        with patch("akshare.tool_trade_date_hist_sina", side_effect=Exception("no net")):
            assert cal.is_trading_day(date(2026, 7, 13)) is True  # Mon
            assert cal.is_trading_day(date(2026, 7, 18)) is False  # Sat

    def test_next_trading_day_skips_weekend(self) -> None:
        cal = TradingCalendar()
        with patch("akshare.tool_trade_date_hist_sina", side_effect=Exception("no net")):
            assert cal.next_trading_day(date(2026, 7, 17)) == date(2026, 7, 17)  # Fri → same
            assert cal.next_trading_day(date(2026, 7, 18)) == date(2026, 7, 20)  # Sat → Mon

    def test_akshare_source_used_when_available(self) -> None:
        """When akshare works, its trade dates win."""
        import pandas as pd

        cal = TradingCalendar()
        hist = pd.DataFrame({"trade_date": pd.to_datetime(["2026-07-14", "2026-07-15"])})
        with patch("akshare.tool_trade_date_hist_sina", return_value=hist):
            days = cal.get_trading_days(date(2026, 7, 13), date(2026, 7, 16))
        assert days == [date(2026, 7, 14), date(2026, 7, 15)]

    def test_first_trading_day_of_month_with_real_calendar(self) -> None:
        """2026-09-01 is a Tuesday trading day → first trading day is 9/1.
        Rebalance day must be exactly that date; 9/2 must NOT rebalance."""
        import pandas as pd

        # Sept 2026: 9/1 Tue .. 9/4 Fri (no CN holiday that week)
        hist = pd.DataFrame(
            {"trade_date": pd.to_datetime(["2026-09-01", "2026-09-02", "2026-09-03"])}
        )
        cal = TradingCalendar()
        with patch("akshare.tool_trade_date_hist_sina", return_value=hist):
            assert cal.is_first_trading_day_of_month(date(2026, 9, 1)) is True
            assert cal.is_first_trading_day_of_month(date(2026, 9, 2)) is False

    def test_first_trading_day_when_first_is_weekend(self) -> None:
        """2026-11-01 is a Sunday → first trading day is Mon 11/2."""
        import pandas as pd

        hist = pd.DataFrame({"trade_date": pd.to_datetime(["2026-11-02", "2026-11-03"])})
        cal = TradingCalendar()
        with patch("akshare.tool_trade_date_hist_sina", return_value=hist):
            assert cal.first_trading_day_of_month(2026, 11) == date(2026, 11, 2)
            assert cal.is_first_trading_day_of_month(date(2026, 11, 2)) is True
            assert cal.is_first_trading_day_of_month(date(2026, 11, 3)) is False

    def test_first_trading_day_after_long_holiday(self) -> None:
        """2026-10-01 National Day week (10/1-10/7 off) → first trading day 10/8."""
        import pandas as pd

        # akshare real calendar: 2026-10 holiday + trading resume 10/8
        hist = pd.DataFrame({"trade_date": pd.to_datetime(["2026-10-08", "2026-10-09"])})
        cal = TradingCalendar()
        with patch("akshare.tool_trade_date_hist_sina", return_value=hist):
            assert cal.first_trading_day_of_month(2026, 10) == date(2026, 10, 8)
            assert cal.is_first_trading_day_of_month(date(2026, 10, 1)) is False
            assert cal.is_first_trading_day_of_month(date(2026, 10, 8)) is True

    def test_has_real_calendar_flag(self) -> None:
        """Flag must be True after a successful akshare load, False on failure."""
        import pandas as pd

        cal_ok = TradingCalendar()
        hist = pd.DataFrame({"trade_date": pd.to_datetime(["2026-09-01"])})
        with patch("akshare.tool_trade_date_hist_sina", return_value=hist):
            cal_ok.get_trading_days(date(2026, 9, 1), date(2026, 9, 1))
        assert cal_ok.has_real_calendar is True

        cal_fail = TradingCalendar()
        with patch("akshare.tool_trade_date_hist_sina", side_effect=Exception("no net")):
            cal_fail.get_trading_days(date(2026, 9, 1), date(2026, 9, 1))
        assert cal_fail.has_real_calendar is False


class TestIndustryCache:
    def test_load_missing_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = IndustryCache(Path(tmp) / "cache.json")
            assert cache.load() is None

    def test_save_then_load_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cache.json"
            cache = IndustryCache(path)
            data = {f"{i:06d}": "制造业" for i in range(60)}  # >50 required by load()
            cache.save(data)
            assert cache.load() == data

    def test_too_few_entries_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cache.json"
            path.write_text(json.dumps({"600519": "白酒"}), encoding="utf-8")
            cache = IndustryCache(path)
            assert cache.load() is None  # < 50 entries → invalid

    def test_expired_cache_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cache.json"
            data = {f"{i:06d}": "制造业" for i in range(100)}
            path.write_text(json.dumps(data), encoding="utf-8")
            # Fake old mtime (200 days ago)
            old = date.today() - timedelta(days=200)
            ts = __import__("datetime").datetime(old.year, old.month, old.day).timestamp()
            import os

            os.utime(path, (ts, ts))
            cache = IndustryCache(path, ttl_days=90)
            assert cache.load() is None

    def test_corrupt_json_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cache.json"
            path.write_text("{not json", encoding="utf-8")
            cache = IndustryCache(path)
            assert cache.load() is None

    def test_invalidate_deletes_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cache.json"
            cache = IndustryCache(path)
            cache.save({"600519": "白酒"})
            assert path.exists()
            cache.invalidate()
            assert not path.exists()


class TestIndustryClassifier:
    def test_get_category_known_prefix(self) -> None:
        c = IndustryClassifier()
        assert c.get_category("C15酒、饮料和精制茶制造业") == "制造业"
        assert c.get_category("J金融业") == "金融业"

    def test_get_category_empty_and_unknown(self) -> None:
        c = IndustryClassifier()
        assert c.get_category("") == "其他"
        assert c.get_category("X未知分类") == "其他(X)"

    def test_category_map_covers_all_csrc_sections(self) -> None:
        # A-S sections A-S should all be mapped
        assert set("ABCDEFGHIJKLMNOPQRS") <= set(CSRC_CATEGORY_MAP.keys())

    def test_prefix_fallback_known_and_unknown(self) -> None:
        assert IndustryClassifier._prefix_fallback("600519") == "金融/综合(沪)"
        assert IndustryClassifier._prefix_fallback("300750") == "创业板"
        assert IndustryClassifier._prefix_fallback("688981") == "科创板"
        assert IndustryClassifier._prefix_fallback("999999") == "其他"

    def test_get_mapping_uses_prefix_when_no_data(self) -> None:
        c = IndustryClassifier()
        # Empty data → every symbol falls back to prefix
        with patch.object(IndustryClassifier, "_load_all", return_value={}):
            mapping = c.get_mapping(["600519", "000001"])
        assert mapping["600519"] == _PREFIX_INDUSTRY["600"]
        assert mapping["000001"] == _PREFIX_INDUSTRY["000"]

    def test_get_mapping_uses_cached_data(self) -> None:
        c = IndustryClassifier()
        with patch.object(IndustryClassifier, "_load_all", return_value={"600519": "白酒"}):
            mapping = c.get_mapping(["600519", "000858"])
        assert mapping["600519"] == "白酒"
        assert mapping["000858"] == _PREFIX_INDUSTRY["000"]

    def test_get_stocks_in_industry(self) -> None:
        c = IndustryClassifier()
        with patch.object(IndustryClassifier, "_load_all", return_value={"600519": "白酒"}):
            found = c.get_stocks_in_industry("白酒", ["600519", "000858"])
        assert found == ["600519"]

    def test_refresh_invalidates_cache(self) -> None:
        c = IndustryClassifier()
        with (
            patch.object(IndustryCache, "invalidate") as mock_inv,
            patch.object(IndustryClassifier, "_load_all", return_value={}),
        ):
            result = c.refresh()
        mock_inv.assert_called_once()
        assert result == {}

    def test_get_industry_map_one_shot(self) -> None:
        with patch.object(IndustryClassifier, "_load_all", return_value={"600519": "白酒"}):
            mapping = get_industry_map(["600519"])
        assert mapping["600519"] == "白酒"
