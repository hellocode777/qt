"""IndustryHeatService 单元测试(不碰网络/生产数据)."""

from pathlib import Path

import polars as pl
import pytest

from qp.research.industry_heat import IndustryHeatService


class _FakeMapper:
    """假行业映射: 6 开头 → Tech, 其余 → Fin."""

    def get_sector(self, symbol: str) -> str:
        return "TechSector" if symbol.startswith("6") else "FinSector"

    def get_sector_group(self, symbol: str) -> str:
        return "TechGroup" if symbol.startswith("6") else "FinGroup"


def _write_parquet(dir_: Path) -> None:
    df = pl.DataFrame(
        {
            "date": ["2026-09-09", "2026-09-09", "2026-09-10", "2026-09-10", "2026-09-10"],
            "symbol": ["600519", "000001", "600519", "000001", "600036"],
            "close": [100.0, 20.0, 101.0, 19.8, 50.0],
            "change_pct": [0.01, -0.02, 0.02, -0.01, 0.005],
            "main_net_flow": [1e8, -5e7, 2e8, -1e7, 3e7],
            "main_net_flow_pct": [0.01, -0.02, 0.02, -0.01, 0.005],
            "super_large_net": [1e8, 0.0, 0.0, 0.0, 0.0],
            "large_net": [0.0, 0.0, 0.0, 0.0, 0.0],
            "turnover": ["1.0"] * 5,  # 语义未核实 — 不应参与聚合并会破坏测试(若误用)
        }
    )
    df.write_parquet(str(dir_ / "capital_flow_latest.parquet"))


@pytest.fixture()
def svc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> IndustryHeatService:
    _write_parquet(tmp_path)
    monkeypatch.setattr("qp.research.industry_heat.DATASET_DIR", tmp_path)
    return IndustryHeatService(granularity="subsector", mapper=_FakeMapper())  # type: ignore[arg-type]


def test_compute_uses_latest_date_by_default(svc: IndustryHeatService) -> None:
    """不给 as_of 时使用数据最新日，并如实写进结果。"""
    res = svc.compute()
    assert res.as_of == "2026-09-10"
    assert res.data_date_max == "2026-09-10"
    assert res.granularity == "subsector"


def test_compute_aggregates_by_industry(svc: IndustryHeatService) -> None:
    """按行业聚合主力净流入(亿元)，排序为降序。"""
    res = svc.compute(min_members=1)
    by_name = {r.industry: r for r in res.industries}
    # 9/10: 600519=2e8, 600036=3e7 → TechGroup 合计 2.3e8 = 2.3 亿
    assert by_name["TechGroup"].members == 2
    assert by_name["TechGroup"].main_net_flow_yi == pytest.approx(2.3)
    # 9/10: 000001=-1e7 → FinGroup = -0.1 亿
    assert by_name["FinGroup"].main_net_flow_yi == pytest.approx(-0.1)
    # 降序: Tech 在前
    assert res.industries[0].industry == "TechGroup"


def test_compute_window_accumulates(svc: IndustryHeatService) -> None:
    """window=2 时累计两个交易日。"""
    res = svc.compute(window=2, min_members=1)
    by_name = {r.industry: r for r in res.industries}
    # 600519: 1e8+2e8=3e8; 600036: 3e7 → 3.3 亿
    assert by_name["TechGroup"].main_net_flow_yi == pytest.approx(3.3)


def test_compute_explicit_as_of_before_latest(svc: IndustryHeatService) -> None:
    """指定较早日期时按该日切窗口。"""
    from datetime import date

    res = svc.compute(as_of=date(2026, 9, 9), min_members=1)
    assert res.as_of == "2026-09-09"
    by_name = {r.industry: r for r in res.industries}
    assert by_name["TechGroup"].main_net_flow_yi == pytest.approx(1.0)  # 仅 600519


def test_unknown_granularity_raises() -> None:
    with pytest.raises(ValueError, match="granularity"):
        IndustryHeatService(granularity="bogus")
