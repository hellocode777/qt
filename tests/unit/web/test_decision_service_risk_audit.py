"""Unit tests for Risk Audit WebUI display parsing.

Regression context: the risk audit section showed raw English detail strings
("Position cap: equal weight 20.0% > 8% at 5 positions") with no structured
numbers, so users couldn't tell at a glance how much a limit was breached.
These tests verify the service-layer parsing that feeds the new visual bars.
"""

from __future__ import annotations

from qp.decision.decision_package import RiskAuditEntry
from qp.web.services.decision_service import _parse_risk_entry


def test_parse_sector_cap_detail():
    entry = RiskAuditEntry(
        violation_type="risk_limit",
        detail="Sector cap: Energy at 40.0% > 25%",
        action="warning",
    )
    d = _parse_risk_entry(entry)
    assert d["category"] == "sector_cap"
    assert d["category_label"] == "行业集中"
    assert d["actual_pct"] == 40.0
    assert d["threshold_pct"] == 25.0
    assert d["over_pct"] == 15.0
    assert d["severity"] == "warning"


def test_parse_position_cap_detail():
    entry = RiskAuditEntry(
        violation_type="risk_limit",
        detail="Position cap: equal weight 20.0% > 8% at 5 positions",
        action="warning",
    )
    d = _parse_risk_entry(entry)
    assert d["category"] == "position_cap"
    assert d["category_label"] == "单仓上限"
    assert d["actual_pct"] == 20.0
    assert d["threshold_pct"] == 8.0
    assert d["over_pct"] == 12.0


def test_parse_position_count_detail():
    entry = RiskAuditEntry(
        violation_type="risk_limit",
        detail="Position count: 7 > 5 max — 2 dropped",
        action="dropped",
    )
    d = _parse_risk_entry(entry)
    assert d["category"] == "position_count"
    assert d["category_label"] == "持仓数量"
    # 7 和 5 不是百分比，无法解析 → N/A
    assert d["actual_pct"] is None
    assert d["threshold_pct"] is None
    assert d["severity"] == "danger"


def test_parse_correlation_entry_structured():
    entry = RiskAuditEntry(
        symbol="000591/000531",
        violation_type="correlation",
        detail="High correlation (0.710)",
        threshold="0.70",
        actual="0.710",
        action="warning",
    )
    d = _parse_risk_entry(entry)
    assert d["category"] == "correlation"
    assert d["category_label"] == "相关性"
    # structured actual "0.710" is a ratio → ×100
    assert d["actual_pct"] == 71.0
    assert d["threshold_pct"] == 70.0
    assert d["over_pct"] == 1.0


def test_parse_correlation_detail_text_fallback():
    entry = RiskAuditEntry(
        violation_type="risk_limit",
        detail="Correlation: 2 pair(s) > 70%, 2 symbol(s) dropped",
        action="warning",
    )
    d = _parse_risk_entry(entry)
    assert d["category"] == "correlation"
    assert d["category_label"] == "相关性"
    # The % in "> 70%" is the threshold; the pair count is not a percentage →
    # actual stays N/A (honest), threshold parsed from the text.
    assert d["actual_pct"] is None
    assert d["threshold_pct"] == 70.0


def test_parse_empty_detail_keeps_defaults():
    entry = RiskAuditEntry(violation_type="risk_limit", detail="", action="warning")
    d = _parse_risk_entry(entry)
    assert d["category"] == "risk_limit"
    assert d["category_label"] == "risk_limit"
    assert d["actual_pct"] is None
    assert d["threshold_pct"] is None
    assert d["over_pct"] is None


def test_build_candidate_stocks_with_weights():
    from qp.decision.decision_package import RiskAudit

    ra = RiskAudit(
        candidates_in=2,
        candidates_out=2,
        candidate_weights={"000591": 0.5, "000531": 0.5},
    )
    from qp.web.services.decision_service import _build_candidate_stocks

    rows = _build_candidate_stocks(ra)
    assert len(rows) == 2
    by_sym = {r["symbol"]: r for r in rows}
    assert by_sym["000591"]["weight_pct"] == 50.0
    assert by_sym["000591"]["sector"]  # non-empty industry label
    # sorted by weight desc
    assert rows[0]["weight_pct"] >= rows[1]["weight_pct"]


def test_build_candidate_stocks_empty_legacy():
    from qp.decision.decision_package import RiskAudit
    from qp.web.services.decision_service import _build_candidate_stocks

    # Legacy packages predate candidate_weights → no fabricated rows
    ra = RiskAudit(candidates_in=5, candidates_out=5, candidate_weights={})
    assert _build_candidate_stocks(ra) == []


def test_risk_audit_serialization_roundtrip(tmp_path):
    from qp.decision.decision_package import DecisionPackage, RiskAudit, RiskAuditEntry

    ra = RiskAudit(
        candidates_in=5,
        candidates_out=3,
        entries=[
            RiskAuditEntry(
                symbol="",
                violation_type="risk_limit",
                detail="Sector cap: Energy at 40.0% > 25%",
                action="warning",
            )
        ],
        dropped_symbols=["000999"],
        sector_exposure={"Energy": 0.4},
        passed=False,
        candidate_weights={"000591": 0.25, "000531": 0.25},
    )
    dp = DecisionPackage(package_id="dp-rt-test", date="2026-08-27", risk_audit=ra)
    p = tmp_path / "dp.json"
    dp.to_json(p)

    loaded = DecisionPackage.from_json(p)
    assert loaded.risk_audit.candidate_weights == {"000591": 0.25, "000531": 0.25}
    assert loaded.risk_audit.passed is False
    assert loaded.risk_audit.entries[0].detail == "Sector cap: Energy at 40.0% > 25%"
