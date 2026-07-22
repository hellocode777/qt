"""Portfolio Optimization constraints — translate Layer 7 bounds into optimizer inputs.

Per docs/8_Capital_Allocation_Layer.md §第三部分:
  MVP 阶段不做复杂优化，但约束结构需提前定义，
  将 Layer 7 输出的 risk bounds 转换为优化器的硬约束。
"""

from qp.portfolio.optimization.constraints import ConstraintSet, OptimizationConstraintsBuilder

__all__ = ["ConstraintSet", "OptimizationConstraintsBuilder"]
