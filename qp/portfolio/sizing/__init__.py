"""Position Sizing — compute target weights from allocation policy + candidates.

Per docs/8_Capital_Allocation_Layer.md §第二部分:
  "Position Sizing 就是计算每个 Position 的目标权重。"
"""

from qp.portfolio.sizing.position_sizer import PositionSizer
from qp.portfolio.sizing.weight_normalizer import NormalizationResult, WeightNormalizer

__all__ = ["NormalizationResult", "PositionSizer", "WeightNormalizer"]
