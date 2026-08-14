"""Unit tests for TencentAdapter — raw-price contract (2026-08-14).

Guards the critical fix: the adapter must ONLY use `day` (unadjusted)
from the kline/kline endpoint and must NEVER fall back to qfqday/hfqday
(the fqkline endpoint is BANNED — negative-price corruption bug).
"""
from qp.data.adapter.tencent_adapter import TencentAdapter


class TestExtractKlinesRawOnly:
    def test_prefers_day_and_ignores_qfqday(self) -> None:
        """qfqday must never be used even if day is present alongside it."""
        data = {
            "data": {
                "sh600438": {
                    "day": [["2018-10-08", "6.540", "6.430", "6.550", "6.400", "199288"]],
                    "qfqday": [["2018-10-08", "1.282", "1.172", "1.292", "1.142", "199288"]],
                }
            }
        }
        klines = TencentAdapter._extract_klines(data, "sh600438")
        assert klines is not None
        assert klines[0][2] == "6.430"  # raw close, NOT the qfq 1.172

    def test_returns_none_when_no_day(self) -> None:
        """If only qfqday/hfqday present (banned endpoint shape), return None."""
        data = {
            "data": {
                "sh600438": {
                    "qfqday": [["2018-10-08", "1.282", "1.172", "1.292", "1.142", "199288"]],
                }
            }
        }
        assert TencentAdapter._extract_klines(data, "sh600438") is None

    def test_empty_payload_returns_none(self) -> None:
        assert TencentAdapter._extract_klines({"data": {}}, "sh600438") is None
