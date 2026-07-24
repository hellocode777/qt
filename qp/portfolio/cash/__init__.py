"""Cash Management — dynamic cash reserve with defense triggers.

Per docs/8_Capital_Allocation_Layer.md §第四部分:
  "现金不仅是剩余资金的归宿，更是平台风险态度的缓冲垫。"
"""

from qp.portfolio.cash.cash_manager import CashDecision, CashManager
from qp.portfolio.cash.reserve_policy import ReservePolicy

__all__ = ["CashDecision", "CashManager", "ReservePolicy"]
