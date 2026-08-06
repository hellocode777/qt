"""Metadata module — version, runtime, and environment information."""

from qp.platform.metadata.environment import EnvironmentMeta
from qp.platform.metadata.runtime import RuntimeMeta
from qp.platform.metadata.version import __version__

__all__ = [
    "EnvironmentMeta",
    "RuntimeMeta",
    "__version__",
]
