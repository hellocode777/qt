# pyright: reportAttributeAccessIssue=false, reportOptionalMemberAccess=false
"""Tests for StrategyConfig.with_overrides — CLI override isolation."""

from qp.strategy.config import StrategyConfig, get_strategy_config
from qp.strategy.strategies.momentum_vol_full import MOMENTUM_VOL_FULL_CONFIG


def _cfg() -> StrategyConfig:
    return MOMENTUM_VOL_FULL_CONFIG


# ----------------------------------------------------------------------
# with_overrides
# ----------------------------------------------------------------------


def test_with_overrides_returns_new_object() -> None:
    cfg = _cfg()
    out = cfg.with_overrides(orthogonalize=True)
    assert out is not cfg
    assert out.orthogonalize is True
    # 原对象未被修改
    assert cfg.orthogonalize is False


def test_with_overrides_multiple_fields() -> None:
    cfg = _cfg()
    out = cfg.with_overrides(
        orthogonalize=True,
        quality_filter=False,
        industry_neutral=False,
        anti_chase=False,
    )
    assert out.orthogonalize is True
    assert out.quality_filter is False
    assert out.industry_neutral is False
    assert out.anti_chase is False
    # 未覆盖字段保留
    assert out.max_positions == cfg.max_positions


def test_with_overrides_unknown_keys_ignored() -> None:
    cfg = _cfg()
    out = cfg.with_overrides(not_a_field=123, also_missing="x")
    assert out.not_a_field if hasattr(out, "not_a_field") else True  # type: ignore[attr-defined]
    # 等价于无覆盖
    assert out.to_dict() == cfg.to_dict()


def test_with_overrides_no_args_is_safe_copy() -> None:
    cfg = _cfg()
    out = cfg.with_overrides()
    assert out is not cfg
    assert out.to_dict() == cfg.to_dict()


def test_global_config_not_mutated_by_experiment_style_override() -> None:
    """get_strategy_config 返回共享对象；覆盖必须走副本，不能污染全局。"""
    before = get_strategy_config("momentum_vol_full").to_dict()
    _ = get_strategy_config("momentum_vol_full").with_overrides(
        orthogonalize=True,
        max_positions=99,
    )
    after = get_strategy_config("momentum_vol_full").to_dict()
    assert after == before
    assert get_strategy_config("momentum_vol_full").orthogonalize is False
    assert get_strategy_config("momentum_vol_full").max_positions == 10


# ----------------------------------------------------------------------
# 与注册配置的契约
# ----------------------------------------------------------------------


def test_momentum_vol_full_registered_orthogonalize_false() -> None:
    """当前生产配置：正交化关（2026-08-13 决策）。"""
    cfg = get_strategy_config("momentum_vol_full")
    assert cfg.orthogonalize is False
    assert cfg.quality_filter is True


def test_registered_config_fields_match() -> None:
    cfg = get_strategy_config("momentum_vol_full")
    assert cfg.name == "momentum_vol_full"
    assert set(cfg.factors.keys()) == {
        "Amplitude_5D",
        "Volatility_20D",
        "Momentum_3M",
        "Volume_Concentration",
        "Volume_Trend_10D",
    }
