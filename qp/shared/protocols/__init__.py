"""Abstract interfaces (Protocols / ABCs) for all core domain objects.

These interfaces define the contract between layers.
Every concrete implementation in a layer must implement one of these base classes.

See rule.md §7 for the complete specification of each interface.
"""

from .base_broker import BaseBroker
from .base_capital_allocator import BaseCapitalAllocator
from .base_corporate_action import CorporateActionEngine
from .base_data_source import BaseDataSource
from .base_experiment_tracker import BaseExperimentTracker
from .base_feature import BaseFeature
from .base_model import BaseModel
from .base_pipeline import BasePipeline
from .base_portfolio_risk import BasePortfolioRiskManager
from .base_risk_model import BaseRiskModel
from .base_strategy import BaseStrategy

__all__ = [
    "BaseBroker",
    "BaseCapitalAllocator",
    "BaseDataSource",
    "BaseExperimentTracker",
    "BaseFeature",
    "BaseModel",
    "BasePipeline",
    "BasePortfolioRiskManager",
    "BaseRiskModel",
    "BaseStrategy",
    "CorporateActionEngine",
]
