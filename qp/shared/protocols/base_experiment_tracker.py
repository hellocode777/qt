"""BaseExperimentTracker — experiment tracking and lineage recording.

See rule.md §7.6 for the complete specification.
"""

from abc import ABC, abstractmethod
from typing import Any


class BaseExperimentTracker(ABC):
    """Abstract base for experiment tracking and full data lineage recording.

    Records the complete dependency chain:
    Dataset → Feature → Label → Model → Strategy → Metrics.
    """

    @abstractmethod
    def log_experiment(
        self,
        experiment_id: str,
        config: dict[str, Any],
        metrics: dict[str, float],
        lineage_graph: dict[str, str],
    ) -> None:
        """Record a complete experiment with configuration, metrics, and lineage.

        Args:
            experiment_id: Unique experiment identifier.
            config: Full experiment configuration (parameters, versions, dates).
            metrics: Evaluation metrics (IC, Sharpe, etc.).
            lineage_graph: Version-bindings for all upstream assets.
        """
        ...
