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
    "Volatility_20D": +0.26,
    "Amplitude_5D": -0.27,
    "Volume_Concentration": -0.24,
    "Momentum_3M": -0.23,
}

# ── 消融实验: 拆因子定位 Q5 塌陷来源 ──

LVR_VOL_ONLY_WEIGHTS: dict[str, float] = {
    "Volatility_20D": +1.00,  # 低波异象
}

LVR_VOL_MOM1M_WEIGHTS: dict[str, float] = {
    "Volatility_20D": +0.50,  # 低波异象
    "Momentum_1M": -0.50,  # 短期反转 (IC=-0.054, 与Vol_20D相关仅+0.078)
}

LVR_VOL_CONC_WEIGHTS: dict[str, float] = {
    "Volatility_20D": +0.50,  # 低波异象
    "Volume_Concentration": -0.50,  # 量集中度 (IC=-0.052, IC_IR=0.67, 极其稳定)
}

LVR_VOL_MOM_WEIGHTS: dict[str, float] = {
    "Volatility_20D": +0.55,
    "Momentum_3M": -0.45,  # 最强反转因子
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
            "bull": 5,
            "sideways_up": 8,
            "neutral": 10,
            "sideways_down": 12,
            "bear": 15,
            "crisis": 20,
        },
        regime_freq={
            "bull": 15,
            "sideways_up": 20,
            "neutral": 20,
            "sideways_down": 30,
            "bear": 40,
            "crisis": 60,
        },
    )


LVR_VOL_ONLY = register_config(
    _make_lvr_config("lvr_vol_only", "低波(仅波动率)", LVR_VOL_ONLY_WEIGHTS)
)
LVR_VOL_STABLE = register_config(
    StrategyConfig(
        name="lvr_vol_stable",
        display_name="低波(稳定版)",
        factors=dict(LVR_VOL_ONLY_WEIGHTS),
        max_positions=10,
        rebalance_freq=40,  # 双月调仓 ↓换手
        sell_buffer_multiplier=4,  # buffer到40名 ↓换手
        score_smooth_days=5,  # 5日得分平滑 ↓换手
        model_mode=False,
        quality_filter=True,
        industry_neutral=True,
        orthogonalize=True,
        anti_chase=True,
        chase_threshold=0.20,
        chase_lookback=5,
        use_market_filter=True,
    )
)
LVR_VOL_MOM1M = register_config(
    _make_lvr_config("lvr_vol_mom1m", "低波+动量1M", LVR_VOL_MOM1M_WEIGHTS)
)
LVR_VOL_CONC = register_config(
    _make_lvr_config("lvr_vol_conc", "低波+量集中度", LVR_VOL_CONC_WEIGHTS)
)
LVR_VOL_MOM = register_config(_make_lvr_config("lvr_vol_mom", "低波+动量", LVR_VOL_MOM_WEIGHTS))
LVR_VOL_ALL_REV = register_config(
    _make_lvr_config("lvr_vol_all_rev", "低波+全部反转", LVR_VOL_ALL_REVERSAL_WEIGHTS)
)

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
            "bull": 5,
            "sideways_up": 8,
            "neutral": 10,
            "sideways_down": 12,
            "bear": 15,
            "crisis": 20,
        },
        regime_freq={
            "bull": 15,
            "sideways_up": 20,
            "neutral": 20,
            "sideways_down": 30,
            "bear": 40,
            "crisis": 60,
        },
    )
)


# ------------------------------------------------------------------
# momentum_vol_full — 原始配置（保留向后兼容）
# ------------------------------------------------------------------

MOMENTUM_VOL_FULL_WEIGHTS: dict[str, float] = {
    # 价量因子 5 个 — 权重方向由全量 IC 归因确定（2026-07-23）
    # IC 方向均为负（A股存在反转效应），幅度 ∝ |IC|
    "Amplitude_5D": -0.25,  # IC=-0.072, IR=0.40
    "Volatility_20D": +0.22,  # IC=+0.063, IR=0.34 (低波异象，唯一正向)
    "Momentum_3M": -0.20,  # IC=-0.057, IR=0.40
    "Volume_Concentration": -0.19,  # IC=-0.055, IR=0.66
    "Volume_Trend_10D": -0.14,  # IC=-0.041, IR=0.46
    # 已移除（|IC|<0.02 或 IC_IR<0.3，噪音源）:
    #   PE_TTM, PB, Price_Volume_Corr, Implied_Net_Flow, Volume_Price_Trend
}

LOW_VOL_REVERSAL_WEIGHTS: dict[str, float] = {
    "Amplitude_5D": -0.25,
    "Volatility_20D": +0.22,
    "Momentum_3M": -0.20,
    "Volume_Concentration": -0.19,
    "Volume_Trend_10D": -0.14,
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
        model_mode=False,  # 回测默认线性加权；管道 .for_live() 开启 LightGBM
        quality_filter=True,
        industry_neutral=True,
        orthogonalize=True,
        anti_chase=True,
        chase_threshold=0.20,
        chase_lookback=5,
        use_market_filter=True,
        regime_positions={
            "bull": 5,
            "sideways_up": 8,
            "neutral": 10,
            "sideways_down": 12,
            "bear": 15,
            "crisis": 20,
        },
        regime_freq={
            "bull": 15,
            "sideways_up": 20,
            "neutral": 20,
            "sideways_down": 30,
            "bear": 40,
            "crisis": 60,
        },
    )
)


# ------------------------------------------------------------------
# 实验配置: Volume_Trend_10D 替换候选 (2026-08-13, 因子失效诊断 #5)
#   Volume_Trend_10D ic_30d=0.000 (最弱因子) → 替换测试
#   候选1: Volume_Expansion_20_120 (+1, 量能扩张=机构关注, volume.py:154)
#   候选2: Amount_Momentum_20_120  (+1, 金额趋势=资金流确认, volume.py:155)
#   权重沿用被替换因子的 -0.14 (方向翻转, 反向语义保留)
# ------------------------------------------------------------------

MVF_V2_EXPANSION_WEIGHTS: dict[str, float] = {
    "Amplitude_5D": -0.25,
    "Volatility_20D": +0.22,
    "Momentum_3M": -0.20,
    "Volume_Concentration": -0.19,
    "Volume_Expansion_20_120": -0.14,  # 替换 Volume_Trend_10D (方向按 -1 反向)
}

MVF_V2_AMOUNT_WEIGHTS: dict[str, float] = {
    "Amplitude_5D": -0.25,
    "Volatility_20D": +0.22,
    "Momentum_3M": -0.20,
    "Volume_Concentration": -0.19,
    "Amount_Momentum_20_120": -0.14,  # 替换 Volume_Trend_10D (方向按 -1 反向)
}


def _make_mvf_v2_config(name: str, display: str, factors: dict) -> StrategyConfig:
    """Factory: momentum_vol_full 克隆 + 因子替换."""
    base = MOMENTUM_VOL_FULL_CONFIG
    import copy

    c = copy.deepcopy(base)
    c.name = name
    c.display_name = display
    c.factors = dict(factors)
    return c


MVF_V2_EXPANSION = register_config(
    _make_mvf_v2_config("mvf_v2_expansion", "mvF v2 (量能扩张替换)", MVF_V2_EXPANSION_WEIGHTS)
)
MVF_V2_AMOUNT = register_config(
    _make_mvf_v2_config("mvf_v2_amount", "mvF v2 (金额动量替换)", MVF_V2_AMOUNT_WEIGHTS)
)


# ------------------------------------------------------------------
# 实验配置: Mom×Vol 交互因子增强 (2026-08-13, R5 → 正式因子)
#   Mom_Vol_Interaction = z(Momentum_3M) × z(Volatility_20D)
#   R5/验证: 增量 IC +0.0301 (2022-2026 +0.0385), Q1→Q5 单调, w=0.05 最优
#   enhanced = composite + 0.05 × interaction → 权重 +0.05
# ------------------------------------------------------------------

MVF_V2_INTERACTION_WEIGHTS: dict[str, float] = {
    "Amplitude_5D": -0.25,
    "Volatility_20D": +0.22,
    "Momentum_3M": -0.20,
    "Volume_Concentration": -0.19,
    "Volume_Trend_10D": -0.14,
    "Mom_Vol_Interaction": +0.05,  # R5 增量因子 (方向 +1, 小权重增强)
}

MVF_V2_INTERACTION = register_config(
    _make_mvf_v2_config(
        "mvf_v2_interaction",
        "mvF v2 (Mom×Vol 交互增强, w=0.05)",
        MVF_V2_INTERACTION_WEIGHTS,
    )
)
# 交互因子与 Mom/Vol 高度共线：VIF 正交化会剥离其信息（实测 IC 0.0708→0.0401，
# turnover 1909%→7072%），必须关闭 orthogonalize（2026-08-13 验证）
MVF_V2_INTERACTION.orthogonalize = False

# 归因对照：5 因子原版 + 关 orthogonalize（区分「正交化开关」vs「交互因子」贡献）
MVF_NOORTH = register_config(
    _make_mvf_v2_config(
        "mvf_noorth",
        "mvF (5因子, 关正交化)",
        dict(MOMENTUM_VOL_FULL_WEIGHTS),
    )
)
MVF_NOORTH.orthogonalize = False


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
                    zip(
                        regime_history["date"].cast(pl.Utf8).to_list(),
                        regime_history["regime"].to_list(),
                        strict=False,
                    )
                )
                logger.info(
                    "📊 市场状态检测: {} 天, 当前={}",
                    len(regime_map),
                    regime_history["regime"].tail(1).item()
                    if not regime_history.is_empty()
                    else "?",
                )
        except Exception as e:
            logger.warning("市场状态检测失败: {}，跳过", e)

    # ── Factor Layer v2: build regime-aware weights ──
    regime_weights: dict[str, dict[str, float]] | None = None
    if getattr(config, "use_regime_ensemble", False) and regime_map:
        try:
            from qp.strategy.factor_layers import FactorEnsemble

            ensemble = FactorEnsemble.from_config(config.factor_layers)
            regime_weights = {}
            seen_regimes = set(regime_map.values())
            for regime in seen_regimes:
                lw = ensemble.get_layer_weights(regime)
                regime_weights[regime] = ensemble.get_active_weights(
                    regime=regime, layer_overrides=lw
                )
            # Log regime distribution
            from collections import Counter

            regime_counts = Counter(regime_map.values())
            total_days = len(regime_map)
            dist_parts = [
                f"{r}:{c}/{total_days}({c / total_days:.0%})"
                for r, c in regime_counts.most_common()
            ]
            logger.info(
                "🎯 因子 Ensemble: {} 个状态 → 动态权重 | 分布: {}",
                len(regime_weights),
                " ".join(dist_parts),
            )
        except Exception as e:
            logger.warning("因子 Ensemble 构建失败: {}，使用固定权重", e)

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
        regime_weights=regime_weights,
        index_df=index_df,
        return_diagnostics=True,
        model_mode=config.model_mode,
        score_percentile_min=score_percentile_min,
        score_percentile_max=score_percentile_max,
        score_smooth_days=getattr(config, "score_smooth_days", 1),
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
