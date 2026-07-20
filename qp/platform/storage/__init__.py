"""Storage Factory — provides storage backends.

Platform provides StorageFactory, not business Repositories (ADR-004).
Repositories belong to their respective business layers.
"""

from qp.platform.storage.factory import StorageFactory

__all__ = ["StorageFactory"]
