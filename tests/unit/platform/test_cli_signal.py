"""``qp signal`` 的行为测试 —— 只读预览，不许产生任何副作用。

锁住三件事：
1. 正常路径按冻结权重打印排名；
2. 请求日期不在本地因子库 → 明确失败（exit 1），不偷偷换日期；
3. 全程不写决策包 / 不动目录（只读契约）。
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import polars as pl
import pytest

from qp.platform.cli.commands import signal as signal_mod
from qp.strategy import multifactor


@pytest.fixture()
def factor_parquet(tmp_path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "factor_values_daily.parquet"
    pl.DataFrame(
        {
            "trade_date": ["2026-11-02", "2026-11-02", "2026-11-02"],
            "symbol": ["603167", "600054", "600168"],
            "Volatility_20D": [-0.10, -0.11, -0.13],
        }
    ).write_parquet(path)
    monkeypatch.setattr(multifactor, "FACTOR_VALUES_DAILY", path)
    return path


@pytest.fixture()
def approved(monkeypatch: pytest.MonkeyPatch):
    snap = SimpleNamespace(
        strategy_id="lvr_vol_only",
        version="v20261029a",
        weights={"Volatility_20D": 1.0},
        parameters={"top_n": 10},
        approved_at=datetime(2026, 10, 29),
    )
    from qp.strategy.registry import StrategyRegistry

    monkeypatch.setattr(StrategyRegistry, "load_active", lambda self: [snap])
    return snap


def test_prints_ranked_top(factor_parquet, approved, capsys) -> None:
    rc = signal_mod.cmd_signal()
    out = capsys.readouterr().out
    assert rc == 0
    assert "lvr_vol_only" in out and "v20261029a" in out
    assert "Volatility_20D=1.0" in out
    assert "603167" in out
    # 分数越负排名越前（Volatility_20D 权重 +1，低波动优先）
    assert out.index("603167") < out.index("600168")


def test_top_limits_rows(factor_parquet, approved, capsys) -> None:
    rc = signal_mod.cmd_signal(top=2)
    out = capsys.readouterr().out
    assert rc == 0
    assert "Top 2" in out
    assert "600168" not in out


def test_unknown_date_fails_without_substituting(factor_parquet, approved, capsys) -> None:
    rc = signal_mod.cmd_signal(as_of="2026-10-31")
    out = capsys.readouterr().out
    assert rc == 1
    assert "2026-10-31" in out
    assert "2026-11-02" in out  # 提示最近可用日期


def test_no_approved_strategy_fails(
    factor_parquet, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    from qp.strategy.registry import StrategyRegistry

    monkeypatch.setattr(StrategyRegistry, "load_active", lambda self: [])
    rc = signal_mod.cmd_signal()
    assert rc == 1
    assert "APPROVED" in capsys.readouterr().out


def test_no_write_side_effects(factor_parquet, approved, tmp_path, monkeypatch) -> None:
    """只读契约：跑完前后，临时目录里不该多出任何文件。"""
    before = sorted(p.name for p in tmp_path.iterdir())
    assert signal_mod.cmd_signal() == 0
    after = sorted(p.name for p in tmp_path.iterdir())
    assert before == after
