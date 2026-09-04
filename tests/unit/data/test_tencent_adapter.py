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


class TestFetchHangProtection:
    """2026-09-04 incident regression: half-open network must not hang
    the whole batch (78 min / 0 stocks). Guards: batch watchdog + session
    with explicit connect/read timeouts."""

    def test_batch_watchdog_aborts_hang(self) -> None:
        """fetch_raw must raise once the batch exceeds its time budget,
        even when every request hangs (timeout never fires)."""
        from datetime import date
        from unittest.mock import patch

        adapter = TencentAdapter()
        adapter._BATCH_WATCHDOG_SECONDS = 0.0  # force immediate watchdog fire
        with patch.object(
            adapter,
            "_fetch_one_stock",
            return_value=[],
        ):
            try:
                adapter.fetch_raw(date(2026, 9, 1), date(2026, 9, 4), symbols=["600519"])
            except RuntimeError as e:
                assert "watchdog" in str(e)
                return
        raise AssertionError("expected RuntimeError from watchdog")

    def test_session_reuse_default_pool(self) -> None:
        """Adapter builds a reusable Session (not per-request connections)."""
        from qp.data.adapter.tencent_adapter import TencentAdapter as TA

        adapter = TA()
        assert adapter._session is not None
        # requests.Session mounts a custom HTTPAdapter for https
        https_adapter = adapter._session.get_adapter("https://ifzq.gtimg.cn/")
        assert type(https_adapter).__name__ == "HTTPAdapter"

    def test_connect_read_timeout_tuple_used(self) -> None:
        """_fetch_one_stock must send timeout=(connect, read) so half-open
        connections cannot stall forever."""
        from datetime import datetime
        from unittest.mock import patch

        adapter = TencentAdapter()
        with (
            patch.object(adapter._session, "get") as mock_get,
            patch.object(
                adapter,
                "_build_segments",
                return_value=[("2026-09-01", "2026-09-04")],
            ),
            patch.object(adapter, "_extract_klines", return_value=[]),
        ):
            adapter._fetch_one_stock(
                "sh600519",
                "600519",
                datetime(2026, 9, 1),
                datetime(2026, 9, 4),
            )
        _, kwargs = mock_get.call_args
        assert kwargs["timeout"] == (5.0, 15.0)
