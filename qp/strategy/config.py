"""策略配置数据类 — 回测和管道的唯一配置源.

设计原则（从 QuantTrading 迁移）：
  - "配置即策略，执行器只负责干活"
  - 回测和管道从同一个 StrategyConfig 对象读取所有参数
  - 修改因子权重/过滤器/调仓周期等，只需改一处

Usage:
    from qp.strategy.config import StrategyConfig, get_strategy_config

    # 回测模式
    config = get_strategy_config("momentum_vol_full")

    # 管道模式（实盘）
    config = get_strategy_config("momentum_vol_full").for_live()
"""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class StrategyConfig:
    """策略完整配置 — 收纳全部可调参数.

    回测和管道都从这里读取，消除"两张皮"问题。
    """

    # ── 标识 ──
    name: str = ""
    display_name: str = ""

    # ── 因子权重 {因子名: 带符号权重} ──
    factors: dict[str, float] = field(default_factory=dict)

    # ── 选股参数 ──
    max_positions: int = 10
    rebalance_freq: int = 20  # 基础调仓周期（交易日）
    sell_buffer_multiplier: int = 2  # 卖出缓冲区 = max_positions * multiplier

    # ── 过滤器开关 ──
    model_mode: bool = False  # True=LightGBM, False=线性加权（回测默认关）
    quality_filter: bool = True  # 质量预筛选（ROE>0, 毛利率>10%等）
    industry_neutral: bool = True  # 行业中性化
    orthogonalize: bool = True  # 因子正交化（Gram-Schmidt / VIF）
    anti_chase: bool = True  # 防追高
    chase_threshold: float = 0.20  # 防追高阈值（近N日涨幅超过此值跳过）
    chase_lookback: int = 5  # 防追高回溯天数
    use_market_filter: bool = True  # 大盘双均线过滤（MA20>MA60 + 连续3日站稳）

    # ── Score Band 选股（Inverted-U Alpha 最优区域选择） ──
    score_percentile_min: float | None = None  # 选股百分位下限 (None=Top-N 默认)
    score_percentile_max: float | None = None  # 选股百分位上限 (None=Top-N 默认)

    # ── 市场过滤器强度（按市场状态分级） ──
    regime_filter_strictness: dict[str, dict[str, int]] = field(
        default_factory=lambda: {
            "bull": {"confirmation_days": 2, "ma_slow": 60},
            "sideways_up": {"confirmation_days": 2, "ma_slow": 60},
            "sideways_down": {"confirmation_days": 1, "ma_slow": 0},
            "bear": {"confirmation_days": 1, "ma_slow": 0},
            "crisis": {"confirmation_days": 3, "ma_slow": 60},
        }
    )

    # ── 市场状态自适应持仓 ──
    regime_positions: dict[str, int] = field(
        default_factory=lambda: {
            "bull": 5,
            "sideways_up": 8,
            "neutral": 10,
            "sideways_down": 12,
            "bear": 15,
            "crisis": 20,
        }
    )
    regime_freq: dict[str, int] = field(
        default_factory=lambda: {
            "bull": 15,
            "sideways_up": 20,
            "neutral": 20,
            "sideways_down": 30,
            "bear": 40,
            "crisis": 60,
        }
    )

    # ── 行业中性化强度 ──
    industry_neutral_strength: float = 1.0

    # ── 最低历史数据要求 ──
    min_history: int = 60

    # ── 方法 ──

    def for_live(self) -> StrategyConfig:
        """返回管道模式副本（开启 model_mode）。"""
        c = copy.deepcopy(self)
        c.model_mode = True
        return c

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典，用于保存回测快照。"""
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> StrategyConfig:
        """从字典恢复配置。"""
        valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in d.items() if k in valid_keys}
        return cls(**filtered)

    def get_sell_buffer_rank(self) -> int:
        """计算卖出缓冲区排名阈值。"""
        return self.max_positions * self.sell_buffer_multiplier

    def get_regime_position(self, regime: str) -> int:
        """获取指定市场状态的持仓数。"""
        return self.regime_positions.get(regime, self.max_positions)

    def get_regime_freq(self, regime: str) -> int:
        """获取指定市场状态的调仓周期。"""
        return self.regime_freq.get(regime, self.rebalance_freq)

    def describe(self) -> str:
        """生成配置摘要。"""
        lines = [
            f"策略: {self.display_name} ({self.name})",
            f"因子数: {len(self.factors)} | 持仓: {self.max_positions}只 | 调仓: {self.rebalance_freq}天",
            f"模型: {'LightGBM' if self.model_mode else '线性加权'} | "
            f"质量过滤: {'开' if self.quality_filter else '关'} | "
            f"行业中性: {'开' if self.industry_neutral else '关'} | "
            f"正交化: {'开' if self.orthogonalize else '关'}",
            f"防追高: {'开' if self.anti_chase else '关'} "
            f"(阈值{self.chase_threshold * 100:.0f}%, 回溯{self.chase_lookback}天)",
            f"大盘过滤: {'开' if self.use_market_filter else '关'} | "
            f"卖出缓冲: {self.get_sell_buffer_rank()}",
        ]
        return "\n".join(lines)


# ── 策略配置注册中心 ─────────────────────────────────


STRATEGY_CONFIGS: dict[str, StrategyConfig] = {}


def register_config(config: StrategyConfig) -> StrategyConfig:
    """注册策略配置到统一中心。"""
    STRATEGY_CONFIGS[config.name] = config
    return config


def get_strategy_config(name: str) -> StrategyConfig:
    """获取策略配置的唯一入口。

    回测和管道都调用此函数获取策略参数，确保配置一致。

    Raises:
        KeyError: 策略名不存在
    """
    if name not in STRATEGY_CONFIGS:
        raise KeyError(f"未知策略: {name}，可用: {list(STRATEGY_CONFIGS)}")
    return STRATEGY_CONFIGS[name]


def list_strategy_configs() -> list[str]:
    """列出所有已注册的策略配置。"""
    return sorted(STRATEGY_CONFIGS.keys())
