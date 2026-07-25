"""Alpha Multi-Factor v1.0 — institutional-grade multi-factor alpha strategy.

5-factor-group architecture:
  Value     (25%): Earnings_Yield, PE_TTM, PB — cheap stocks
  Quality   (25%): ROE, Profit_Stability, Cash_Quality — avoid junk
  Momentum  (20%): Momentum_6M, Trend_MA120 — ride trends
  Volume    (15%): Volume_Expansion_20_120, Amount_Momentum_20_120 — money flow
  Low Risk  (15%): Volatility_60D, MaxDD_60D — control downside

Design principles:
  - Industry-neutral per factor (OLS: strip sector + size effects)
  - Z-score then winsorize(3σ)
  - Monthly rebalance, sell buffer (buy Top20, sell below Top40)
  - ML upgrade path: LightGBM LambdaRank via model_mode=True
  - Must pass §10.1 validation gate before entering strategy layer

Usage:
    uv run qp experiment run multifactor --strategy alpha_multi_factor_v1 --start 2024-01-01
"""

from __future__ import annotations

from typing import Any

import polars as pl
from loguru import logger

from qp.research.feature.fundamental import compute_all_fundamental_factors
from qp.strategy.config import (
    StrategyConfig,
    get_strategy_config,
    register_config,
)
from qp.strategy.market_filter import filter_signals
from qp.strategy.market_regime import MarketRegimeDetector
from qp.strategy.multifactor import run_multifactor_strategy

# ======================================================================
# v1 — 原版（已退役，保留对照）
# ======================================================================

# ------------------------------------------------------------------
# v2 Factor Weights — 5 groups, 14 factors
# ------------------------------------------------------------------
# 核心修正（基于 v1 IC 归因数据）:
#   Trend_MA120    IC=-0.067 → 反转: 偏离MA越低越好
#   Momentum_6M    IC=-0.061 → 反转: 保留但降权
#   Amount_Mom     IC=-0.057 → 反转: 缩量更好
#   Volume_Exp     IC=-0.053 → 反转: 缩量更好
#   Volatility_60D IC=+0.050 → 确认低波异象，保留正向
#   MaxDD_60D      IC=-0.027 → 反转: 回撤越大未来收益越高
#   Value/Quality  |IC|<0.02  → 保留但降权，需要更长时间周期验证
# 权重符号说明:
#   + = 因子值越高 → 综合得分越高（买入）
#   - = 因子值越低 → 综合得分越高（买入）
# 注意: 价量因子的 MOMENTUM_DIRECTIONS/VOLUME_DIRECTIONS 已内置方向
#       在 combine_factors 中: norm * direction * weight → 最终贡献
#       所以 reversal 因子用 +weight（direction 已为 -1, +weight 保持反转）

ALPHA_V2_WEIGHTS: dict[str, float] = {
    # ── ① Short-term Reversal (25%) — A股核心Alpha ──
    # 数据支撑: Momentum_6M IC=-0.061, Trend_MA120 IC=-0.067
    "Short_Term_Reversal_5D": +0.10,  # 5日反转 (direction=-1, +weight→反转)
    "Momentum_1M": +0.08,  # 20日反转 (direction=-1, +weight→反转)
    "Momentum_3M": +0.07,  # 60日反转 (direction=-1, +weight→反转)
    # ── ② Value Reversal (25%) — 便宜+修复 ──
    # 数据支撑: 2024-2026 IC弱但有经济逻辑，需要更长周期
    "Earnings_Yield": +0.10,  # EPS/Price, 越高越便宜
    "PB": -0.08,  # 低PB=便宜 (负号: 低PB→高得分)
    "PCF_OCF": +0.07,  # FCF Yield, 越高现金流越好
    # ── ③ Quality (20%) — 降权但保留, 防止价值陷阱 ──
    "ROE": +0.08,
    "Profit_Stability": +0.06,
    "Cash_Quality": +0.06,
    # ── ④ Low Risk (15%) — 低波异象已确认 ──
    "Volatility_60D": +0.10,  # IC=+0.05, 低波异象确认 (direction=+1)
    "MaxDD_60D": -0.05,  # IC=-0.027, 反转: 回撤越大越买 (direction=+1, -weight)
    # ── ⑤ Liquidity / Contrarian Volume (15%) — 缩量反转 ──
    # 数据支撑: Volume_Exp IC=-0.053, Amount_Mom IC=-0.057
    # A股放量=派发, 缩量=蓄力 → 取负
    "Volume_Expansion_20_120": -0.08,  # 缩量更好 (direction=+1, -weight)
    "Amount_Momentum_20_120": -0.07,  # 成交额萎缩更好 (direction=+1, -weight)
}

# ------------------------------------------------------------------
# v2 Strategy Config
# ------------------------------------------------------------------

ALPHA_V2_CONFIG = register_config(
    StrategyConfig(
        name="alpha_multi_factor_v2",
        display_name="Alpha多因子 v2.0 (反转版)",
        factors=dict(ALPHA_V2_WEIGHTS),
        max_positions=20,
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
            "bull": 15,
            "sideways_up": 20,
            "neutral": 20,
            "sideways_down": 25,
            "bear": 30,
            "crisis": 35,
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

# ======================================================================
# v1 — 原版（保留对照）
# ======================================================================

# Category weights:
#   Value=25%  Quality=25%  Momentum=20%  Volume=15%  LowRisk=15%
# Within-category weights are equal (normalized by combine_factors).
# Signs: negative = factor value should be penalized (e.g. high vol → low score)

ALPHA_MULTI_FACTOR_WEIGHTS: dict[str, float] = {
    # ── Value (25%) — higher = cheaper ──
    "Earnings_Yield": +0.10,  # EPS/Price
    "PE_TTM": -0.075,  # Lower P/E = better (negated)
    "PB": -0.075,  # Lower P/B = better (negated)
    # ── Quality (25%) — higher = better business ──
    "ROE": +0.10,  # High ROE = quality
    "Profit_Stability": +0.075,  # -std(ROE), higher = more stable
    "Cash_Quality": +0.075,  # OCF/EPS, higher = real profits
    # ── Momentum (20%) — trend confirmation ──
    "Momentum_6M": -0.10,  # 6M return (A股反转 → negative sign)
    "Trend_MA120": +0.10,  # Price > MA120 = uptrend
    # ── Volume / Money Flow (15%) — institutional interest ──
    "Volume_Expansion_20_120": +0.075,  # Expanding volume = interest
    "Amount_Momentum_20_120": +0.075,  # Expanding amount = money flow
    # ── Low Risk (15%) — volatility penalty ──
    "Volatility_60D": +0.075,  # Low-vol anomaly (factor is negated)
    "MaxDD_60D": +0.075,  # Smaller drawdowns = better (factor is negated)
}

# ------------------------------------------------------------------
# Strategy Config
# ------------------------------------------------------------------

ALPHA_MULTI_FACTOR_CONFIG = register_config(
    StrategyConfig(
        name="alpha_multi_factor_v1",
        display_name="Alpha多因子 v1.0",
        factors=dict(ALPHA_MULTI_FACTOR_WEIGHTS),
        max_positions=20,
        rebalance_freq=20,
        sell_buffer_multiplier=2,  # Buy rank≤20, sell rank>40
        model_mode=False,  # 回测默认线性加权；.for_live() 开启 LightGBM
        quality_filter=True,
        industry_neutral=True,
        orthogonalize=True,
        anti_chase=True,
        chase_threshold=0.20,
        chase_lookback=5,
        use_market_filter=True,
        # Market regime adaptive positions (effective for A-share):
        regime_positions={
            "bull": 15,       # concentrate in strong trends
            "sideways_up": 20,
            "neutral": 20,
            "sideways_down": 25,  # diversify when uncertain
            "bear": 30,
            "crisis": 35,     # maximum diversification
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
# Main run function
# ------------------------------------------------------------------


def run_alpha_multi_factor_v1(
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
    """Run Alpha Multi-Factor strategy v1.0.

    Pipeline:
      1. Quality filter → avoid junk
      2. Fundamental factor computation → EY, stability, cash quality
      3. Price/volume factor computation → momentum, volume, risk
      4. Factor pipeline → winsorize → normalize → neutralize → combine
      5. Anti-chase → skip stocks that ran up too fast
      6. Signal generation → Top-N with sell buffer
      7. Market filter → MA20>MA60 + regime gating
    """
    # 1. Load config
    if config is None:
        config = get_strategy_config("alpha_multi_factor_v1")
    else:
        config = _apply_overrides(config, overrides)

    weights = dict(config.factors)
    top_n = config.max_positions
    rebalance_freq = config.rebalance_freq
    sell_buffer_rank = config.get_sell_buffer_rank()

    logger.info("📋 {}", config.describe().replace("\n", "\n📋 "))

    # 2. Market regime detection
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

    # 3. Compute fundamental-derived factors (PIT-safe, quarterly update)
    logger.info("   📊 计算基本面因子 (EY, Profit Stability, Cash Quality)...")
    try:
        extra_factors = compute_all_fundamental_factors(
            price_data,
            fundamental_data or {},
        )
        n_dates = len(extra_factors)
        n_fund_factors = 3
        logger.info("   ✅ 基本面因子: {} 日 × {} 因子", n_dates, n_fund_factors)
    except Exception as e:
        logger.warning("基本面因子计算失败: {}，跳过", e)
        extra_factors = None

    # 4. Run multi-factor strategy engine
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
        extra_factors=extra_factors,
    )

    diagnostics = None
    if isinstance(mf_result, tuple):
        signals, diagnostics = mf_result
        scores = diagnostics.get("scores") if diagnostics else None
    else:
        signals = mf_result
        scores = None

    # 5. Market filter + regime gating
    if config.use_market_filter and not signals.is_empty() and index_df is not None:
        signals = filter_signals(
            signals,
            index_df,
            ma_period=20,
            confirmation_days=3,
            ma_slow=60,
        )

        if regime_map is not None and not signals.is_empty():
            from qp.strategy.market_filter import apply_regime_gating

            signals = apply_regime_gating(signals, regime_map)

    if return_diagnostics:
        return signals, diagnostics  # type: ignore[return-value]
    return signals, {"scores": scores}


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


# ------------------------------------------------------------------
# v2 runner — thin wrapper, same engine, corrected factor signs
# ------------------------------------------------------------------


def run_alpha_multi_factor_v2(
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
    """Alpha Multi-Factor v2.0 — A股 Quality-Value-Reversal.

    v2 fixes v1's systematic sign errors discovered by IC attribution:
      - Momentum → Reversal (all negative IC)
      - Volume Expansion → Contrarian (negative IC = distribution, not accumulation)
      - Trend_MA120 removed (replaced by short-term reversal factors)
      - MaxDD flipped (drawdown → opportunity, not risk)
      - Value/Quality reduced weight (IC near zero in 2024-2026)
    """
    if config is None:
        config = get_strategy_config("alpha_multi_factor_v2")
    return run_alpha_multi_factor_v1(
        price_data=price_data,
        config=config,
        fundamental_data=fundamental_data,
        valuation_data=valuation_data,
        index_df=index_df,
        force_rebalance_today=force_rebalance_today,
        holdings=holdings,
        return_diagnostics=return_diagnostics,
        **overrides,
    )


def _apply_overrides(config: StrategyConfig, overrides: dict[str, Any]) -> StrategyConfig:
    """Apply **overrides key-value pairs to a copy of config."""
    import copy

    c = copy.deepcopy(config)
    for k, v in overrides.items():
        if hasattr(c, k):
            setattr(c, k, v)
    return c
