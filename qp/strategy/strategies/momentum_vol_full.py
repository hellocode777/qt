"""momentum_vol_full — 动量+成交量 完整版策略.

从 QuantTrading 迁移，基于全量 IC 归因精简为 5 因子：
  5 因子线性加权 → MAD 去极值 → 排名标准化 →
  行业中性化 → 因子正交化 → 质量过滤 → 防追高 →
  卖出缓冲 → 大盘双均线过滤 → 市场状态自适应仓位

因子权重（由全量 3039 只 IC 归因确定，2026-07-23）:
  Amplitude_5D        -0.25  5日振幅（反转效应，高振幅→低得分）
  Volatility_20D      +0.22  低波异象（唯一正向因子）
  Momentum_3M         -0.20  60日动量（A股反转，高动量→低得分）
  Volume_Concentration -0.19  成交量集中度
  Volume_Trend_10D    -0.14  成交量趋势

已移除的弱因子（|IC|<0.02 或 IC_IR<0.3）:
  PE_TTM, PB, Price_Volume_Corr, Implied_Net_Flow, Volume_Price_Trend
"""

from __future__ import annotations

from typing import Any

import polars as pl
from loguru import logger

from qp.strategy.config import (
    StrategyConfig,
    get_strategy_config,
    register_config,
)
from qp.strategy.market_filter import filter_signals
from qp.strategy.market_regime import MarketRegimeDetector
from qp.strategy.multifactor import run_multifactor_strategy

# ------------------------------------------------------------------
# low_vol_reversal — 低波+反转（从 momentum_vol_full IC 归因演化）
# ------------------------------------------------------------------

LOW_VOL_REVERSAL_WEIGHTS: dict[str, float] = {
    "Amplitude_5D": -0.25,
    "Volatility_20D": +0.22,
    "Momentum_3M": -0.20,
    "Volume_Concentration": -0.19,
    "Volume_Trend_10D": -0.14,
}

# ── 消融实验: 拆因子定位 Q5 塌陷来源 ──

LVR_VOL_ONLY_WEIGHTS: dict[str, float] = {
    "Volatility_20D": +1.00,  # 低波异象
}

LVR_VOL_MOM_WEIGHTS: dict[str, float] = {
    "Volatility_20D": +0.55,
    "Momentum_3M": -0.45,     # 最强反转因子
}

LVR_VOL_ALL_REVERSAL_WEIGHTS: dict[str, float] = {
    "Volatility_20D": +0.35,
    "Momentum_3M": -0.25,
    "Amplitude_5D": -0.15,
    "Volume_Trend_10D": -0.15,
    "Volume_Concentration": -0.10,
}


def _make_lvr_config(name: str, display: str, factors: dict) -> StrategyConfig:
    """Factory for low_vol_reversal ablation configs."""
    return StrategyConfig(
        name=name,
        display_name=display,
        factors=dict(factors),
        max_positions=10, rebalance_freq=20, sell_buffer_multiplier=2,
        model_mode=False, quality_filter=True, industry_neutral=True,
        orthogonalize=True, anti_chase=True, chase_threshold=0.20,
        chase_lookback=5, use_market_filter=True,
        regime_positions={
            "bull": 5, "sideways_up": 8, "neutral": 10,
            "sideways_down": 12, "bear": 15, "crisis": 20,
        },
        regime_freq={
            "bull": 15, "sideways_up": 20, "neutral": 20,
            "sideways_down": 30, "bear": 40, "crisis": 60,
        },
    )


LVR_VOL_ONLY = register_config(_make_lvr_config(
    "lvr_vol_only", "低波(仅波动率)", LVR_VOL_ONLY_WEIGHTS))
LVR_VOL_MOM = register_config(_make_lvr_config(
    "lvr_vol_mom", "低波+动量", LVR_VOL_MOM_WEIGHTS))
LVR_VOL_ALL_REV = register_config(_make_lvr_config(
    "lvr_vol_all_rev", "低波+全部反转", LVR_VOL_ALL_REVERSAL_WEIGHTS))

LOW_VOL_REVERSAL_CONFIG = register_config(
    StrategyConfig(
        name="low_vol_reversal",
        display_name="低波+反转",
        factors=dict(LOW_VOL_REVERSAL_WEIGHTS),
        max_positions=10,
        rebalance_freq=20,
        sell_buffer_multiplier=2,
        model_mode=False,
        quality_filter=True,
        industry_neutral=True,
        orthogonalize=True,
        anti_chase=True,
        chase_threshold=0.20,
        chase_lookback=5,
        use_market_filter=True,
        regime_positions={
            "bull": 5, "sideways_up": 8, "neutral": 10,
            "sideways_down": 12, "bear": 15, "crisis": 20,
        },
        regime_freq={
            "bull": 15, "sideways_up": 20, "neutral": 20,
            "sideways_down": 30, "bear": 40, "crisis": 60,
        },
    )
)


# ------------------------------------------------------------------
# momentum_vol_full — 原始配置（保留向后兼容）
# ------------------------------------------------------------------

MOMENTUM_VOL_FULL_WEIGHTS: dict[str, float] = {
    # 价量因子 5 个 — 权重方向由全量 IC 归因确定（2026-07-23）
    # IC 方向均为负（A股存在反转效应），幅度 ∝ |IC|
    "Amplitude_5D": -0.25,           # IC=-0.072, IR=0.40
    "Volatility_20D": +0.22,         # IC=+0.063, IR=0.34 (低波异象，唯一正向)
    "Momentum_3M": -0.20,            # IC=-0.057, IR=0.40
    "Volume_Concentration": -0.19,   # IC=-0.055, IR=0.66
    "Volume_Trend_10D": -0.14,       # IC=-0.041, IR=0.46
    # 已移除（|IC|<0.02 或 IC_IR<0.3，噪音源）:
    #   PE_TTM, PB, Price_Volume_Corr, Implied_Net_Flow, Volume_Price_Trend
}

# ------------------------------------------------------------------
# 策略配置（回测和管道共用）
# ------------------------------------------------------------------

MOMENTUM_VOL_FULL_CONFIG = register_config(
    StrategyConfig(
        name="momentum_vol_full",
        display_name="动量+成交量(完整版)",
        factors=dict(MOMENTUM_VOL_FULL_WEIGHTS),
        max_positions=10,
        rebalance_freq=20,
        sell_buffer_multiplier=2,
        model_mode=False,          # 回测默认线性加权；管道 .for_live() 开启 LightGBM
        quality_filter=True,
        industry_neutral=True,
        orthogonalize=True,
        anti_chase=True,
        chase_threshold=0.20,
        chase_lookback=5,
        use_market_filter=True,
        regime_positions={
            "bull": 5, "sideways_up": 8, "neutral": 10,
            "sideways_down": 12, "bear": 15, "crisis": 20,
        },
        regime_freq={
            "bull": 15, "sideways_up": 20, "neutral": 20,
            "sideways_down": 30, "bear": 40, "crisis": 60,
        },
    )
)


# ------------------------------------------------------------------
# 主运行函数
# ------------------------------------------------------------------


def run_momentum_vol_full(
    price_data: dict[str, pl.DataFrame],
    config: StrategyConfig | None = None,
    fundamental_data: dict[str, pl.DataFrame] | None = None,
    valuation_data: dict[str, pl.DataFrame] | None = None,
    index_df: pl.DataFrame | None = None,
    force_rebalance_today: bool = False,
    holdings: set[str] | None = None,
    return_diagnostics: bool = False,
    **overrides: Any,
) -> pl.DataFrame | tuple[pl.DataFrame, dict[str, Any]]:
    """运行 动量+成交量 完整版多因子策略.

    完整流程:
      1. 质量过滤 — 剔除 ROE≤0 / 毛利率<10% / 营收下滑 / 净利率<0
      2. 因子计算 — 10 因子截面打分
      3. 因子管线 — MAD去极值 → 排名标准化 → 行业中性 → 正交化 → 加权合成
      4. 防追高 — 近5日涨超20%跳过买入
      5. 信号生成 — Top-N买入，卖出缓冲区
      6. 大盘过滤 — MA20>MA60 双确认
      7. 市场状态 — 熊市/危机禁止开仓，自适应持仓数

    Args:
        price_data: {code: DataFrame(trade_date, open, high, low, close, volume)}.
        config: StrategyConfig 对象。None 则使用 MOMENTUM_VOL_FULL_CONFIG.
        fundamental_data: {code: DataFrame(report_date, ROE, gross_margin, ...)}.
        valuation_data: {code: DataFrame(date, PE_TTM, PB, ...)}.
        index_df: 沪深300 日线 [date, close] 用于大盘过滤和市场状态检测.
        force_rebalance_today: 强制最后一天为调仓日（管道模式）.
        holdings: 当前持仓（管道模式）.
        return_diagnostics: 返回诊断信息.
        **overrides: 可覆盖 StrategyConfig 的任意字段.

    Returns:
        Polars DataFrame [date, symbol, signal, score, reason, name],
        或 (DataFrame, diagnostics) when return_diagnostics=True.
    """
    # 1. 加载配置
    if config is None:
        config = get_strategy_config("momentum_vol_full")
    else:
        # 允许 params 覆盖 config 字段
        config = _apply_overrides(config, overrides)

    weights = dict(config.factors)
    top_n = config.max_positions
    rebalance_freq = config.rebalance_freq
    sell_buffer_rank = config.get_sell_buffer_rank()

    logger.info("📋 {}", config.describe().replace("\n", "\n📋 "))

    # 2. 市场状态检测（用于自适应仓位 + 大盘过滤）
    regime_map: dict[str, str] | None = None
    if config.use_market_filter and index_df is not None:
        try:
            detector = MarketRegimeDetector()
            regime_history = detector.detect_history(index_df)
            if not regime_history.is_empty():
                regime_map = dict(
                    zip(regime_history["date"].cast(pl.Utf8).to_list(),
                        regime_history["regime"].to_list(), strict=False)
                )
                logger.info(
                    "📊 市场状态检测: {} 天, 当前={}",
                    len(regime_map),
                    regime_history["regime"].tail(1).item() if not regime_history.is_empty() else "?",
                )
        except Exception as e:
            logger.warning("市场状态检测失败: {}，跳过", e)

    # 3. 运行多因子策略（核心引擎）
    # Always request scores for IC analysis, even if diagnostics not needed
    # Extract score band overrides for inverted-U selection
    score_percentile_min = overrides.pop("score_percentile_min", None)
    score_percentile_max = overrides.pop("score_percentile_max", None)

    mf_result = run_multifactor_strategy(
        price_data,
        weights=weights,
        top_n=top_n,
        rebalance_freq=rebalance_freq,
        fundamental_data=fundamental_data or {},
        valuation_data=valuation_data or {},
        industry_neutral=config.industry_neutral,
        orthogonalize=config.orthogonalize,
        quality_filter=config.quality_filter,
        anti_chase=config.anti_chase,
        chase_threshold=config.chase_threshold,
        chase_lookback=config.chase_lookback,
        sell_buffer_rank=sell_buffer_rank,
        force_rebalance_today=force_rebalance_today,
        holdings=holdings,
        regime_map=regime_map,
        regime_positions=config.regime_positions if regime_map else None,
        return_diagnostics=True,
        model_mode=config.model_mode,
        score_percentile_min=score_percentile_min,
        score_percentile_max=score_percentile_max,
    )

    diagnostics = None
    if isinstance(mf_result, tuple):
        signals, diagnostics = mf_result
        scores = diagnostics.get("scores") if diagnostics else None
    else:
        signals = mf_result
        scores = None

    # 4. 大盘过滤 + 市场状态门控
    if config.use_market_filter and not signals.is_empty() and index_df is not None:
        # 4a. 双均线确认过滤
        signals = filter_signals(
            signals,
            index_df,
            ma_period=20,
            confirmation_days=3,
            ma_slow=60,
        )

        # 4b. 熊市/危机禁止开新仓
        if regime_map is not None and not signals.is_empty():
            from qp.strategy.market_filter import apply_regime_gating

            signals = apply_regime_gating(signals, regime_map)

    if return_diagnostics:
        return signals, diagnostics  # type: ignore[return-value]
    # When not returning full diagnostics, still return scores for IC analysis
    return signals, {"scores": scores}


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _apply_overrides(config: StrategyConfig, overrides: dict[str, Any]) -> StrategyConfig:
    """将 **overrides 中的键值覆盖到 config 上."""
    import copy

    c = copy.deepcopy(config)
    for k, v in overrides.items():
        if hasattr(c, k):
            setattr(c, k, v)
    return c
