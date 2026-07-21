"""Tests for qp.data.cleaning.delisted_handler — DelistedHandler."""

from __future__ import annotations

from qp.data.cleaning.delisted_handler import DelistedHandler


class TestDelistedHandler:
    def test_hardcoded_list_not_empty(self):
        handler = DelistedHandler()
        codes = handler.get_delisted_codes()
        assert len(codes) >= 50  # 57 hardcoded stocks

    def test_known_delisted_stock(self):
        handler = DelistedHandler()
        # Several known delisted stocks in the hardcoded list
        codes = handler.get_delisted_codes()
        assert len(codes) > 0
        # Verify all returned codes are strings
        for code in codes:
            assert isinstance(code, str)

    def test_active_stock_not_delisted(self):
        handler = DelistedHandler()
        assert handler.is_delisted("600519") is False

    def test_check_stock_active(self):
        handler = DelistedHandler()
        # A currently active A-share stock
        assert handler.check_stock_active("600519") is True

    def test_delisted_stock_not_active(self):
        handler = DelistedHandler()
        codes = handler.get_delisted_codes()
        if codes:
            assert handler.check_stock_active(codes[0]) is False

    def test_scan_inactive_with_dict(self):
        """scan_inactive requires a {code: date_str} dict with recent dates."""
        handler = DelistedHandler()
        from datetime import date
        today = date.today().isoformat()
        code_date_map = {
            "600519": today,
            "600036": today,
        }
        inactive = handler.scan_inactive(code_date_map)
        # Active stocks with recent trade dates should not appear
        assert "600519" not in inactive
        assert "600036" not in inactive

    def test_scan_inactive_with_delisted(self):
        handler = DelistedHandler()
        codes = handler.get_delisted_codes()
        if codes:
            test_code = codes[0]
            code_date_map = {test_code: "2020-01-15"}
            inactive = handler.scan_inactive(code_date_map)
            assert test_code in inactive

    def test_get_survivorship_stats(self):
        handler = DelistedHandler()
        universe = ["600519", "600036", "000858"]
        stats = handler.get_survivorship_stats(universe)
        assert "total" in stats
        assert stats["total"] == 3
        assert "delisted_count" in stats
        assert "active_count" in stats
        assert "delisted_pct" in stats
        assert stats["active_count"] == 3  # all active stocks
