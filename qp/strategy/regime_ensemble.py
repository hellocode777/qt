"""Regime → Factor Ensemble mapping.

Defines how the 4-layer factor ensemble adjusts per market regime.

Principle:
  - Bull/trending: tilt toward price_alpha + growth (momentum works with trend)
  - Sideways/ranging: balanced allocation across all layers
  - Bear/crisis: tilt toward value + quality (defensive), drop price_alpha
    (reversal strategies fail in panic)
"""

from __future__ import annotations

# ------------------------------------------------------------------
# Regime → Layer Weight mapping
# ------------------------------------------------------------------
# Each regime has a {layer_name: weight} dict.
# Weights are relative — they get normalized to sum to 1.0.
# A weight of 0.0 means the layer is disabled in that regime.

REGIME_LAYER_WEIGHTS: dict[str, dict[str, float]] = {
    "bull": {
        "price_alpha": 0.35,
        "value": 0.15,
        "quality": 0.20,
        "growth": 0.30,
    },
    "sideways_up": {
        "price_alpha": 0.30,
        "value": 0.20,
        "quality": 0.30,
        "growth": 0.20,
    },
    "neutral": {
        "price_alpha": 0.25,
        "value": 0.25,
        "quality": 0.25,
        "growth": 0.25,
    },
    "sideways_down": {
        "price_alpha": 0.15,
        "value": 0.35,
        "quality": 0.30,
        "growth": 0.20,
    },
    "bear": {
        "price_alpha": 0.05,
        "value": 0.40,
        "quality": 0.35,
        "growth": 0.20,
    },
    "crisis": {
        "price_alpha": 0.00,
        "value": 0.50,
        "quality": 0.50,
        "growth": 0.00,
    },
}

# Human-readable explanations for each regime's allocation
REGIME_ALLOCATION_RATIONALE: dict[str, str] = {
    "bull": (
        "趋势向上：重 Price Alpha(35%) + Growth(30%)。"
        "反转因子在牛市中表现为'回调买入'而非纯反转，趋势确认有效。"
        "Value 权重最低(15%)——牛市不看估值。"
    ),
    "sideways_up": (
        "震荡偏多：均衡偏 Price(30%) + Quality(30%)。"
        "方向不明确时质量因子提供防御，反转因子在震荡中有交易机会。"
    ),
    "neutral": (
        "中性：四层均等(25%)。信号不明确时不做风格倾斜，靠多来源分散获取 alpha。"
    ),
    "sideways_down": (
        "震荡偏空：重 Value(35%) + Quality(30%)。"
        "价格下行时便宜货 + 优质股提供安全边际。"
        "Price Alpha 降至 15%——弱市中反转信号可靠性下降。"
    ),
    "bear": (
        "熊市：重 Value(40%) + Quality(35%)，Price Alpha 降至 5%。"
        "反转策略在恐慌中完全失效（接飞刀）。"
        "估值锚 + 盈利质量是最可靠的安全垫。"
    ),
    "crisis": (
        "危机：只保留 Value(50%) + Quality(50%)。"
        "Price Alpha 和 Growth 完全关闭。"
        "流动性危机中唯一有效的因子是'便宜+能活下来'。"
    ),
}


def get_regime_layer_weights(regime: str) -> dict[str, float]:
    """Get normalized layer weights for a given market regime.

    Args:
        regime: Market regime label ("bull", "bear", "crisis", etc.)

    Returns:
        {layer_name: weight} dict normalized to sum to 1.0.
        If regime is unknown, returns equal weights.
    """
    raw = REGIME_LAYER_WEIGHTS.get(regime)
    if raw is None:
        # Unknown regime: equal weight all layers
        return {
            "price_alpha": 0.25,
            "value": 0.25,
            "quality": 0.25,
            "growth": 0.25,
        }

    total = sum(raw.values())
    if total <= 0:
        return dict.fromkeys(raw, 0.0)

    return {k: v / total for k, v in raw.items()}


def get_regime_rationale(regime: str) -> str:
    """Get the rationale for a regime's layer allocation."""
    return REGIME_ALLOCATION_RATIONALE.get(
        regime, f"未知市场状态 '{regime}'：使用默认均衡配置。"
    )


def get_disabled_layers(regime: str) -> list[str]:
    """Get layers disabled in the given regime (weight = 0)."""
    weights = get_regime_layer_weights(regime)
    return [name for name, w in weights.items() if w <= 0]


def regime_ensemble_summary() -> str:
    """Build a human-readable summary of all regime allocations.

    Returns:
        Multi-line string suitable for logging.
    """
    lines = ["Regime → Factor Ensemble 映射:", "-" * 60]
    for regime in ["bull", "sideways_up", "neutral", "sideways_down", "bear", "crisis"]:
        weights = get_regime_layer_weights(regime)
        parts = [f"{k}:{v:.0%}" for k, v in weights.items()]
        disabled = get_disabled_layers(regime)
        note = f"  [关闭: {', '.join(disabled)}]" if disabled else ""
        lines.append(f"  {regime:15s} → {' | '.join(parts)}{note}")
    return "\n".join(lines)
