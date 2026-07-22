"""StrategyLoader — hot-plug strategy discovery via importlib.

Per docs/6_Strategy_Engine.md 补充 §2:
  "Runner 只需要扫描 Registry，通过类名或动态 import（importlib）
   实例化策略，策略本身与 Runner 的调度完全解耦。"

Usage:
    loader = StrategyLoader()
    strategies = loader.discover("qp.strategy.strategies")
    # → {"MomentumStrategy": <class>, "ValueStrategy": <class>}

    registry = StrategyRegistry()
    loader.register_all(registry, configs={"momentum_v1": {...}})
    # → Strategies instantiated and registered with config
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from dataclasses import dataclass
from typing import Any

from qp.shared.protocols.base_strategy import BaseStrategy


@dataclass
class StrategyLoader:
    """Discover and auto-register BaseStrategy implementations.

    Scans a Python package for BaseStrategy subclasses and optionally
    instantiates and registers them into a StrategyRegistry.

    Usage:
        loader = StrategyLoader()

        # Discover only (no instantiation)
        classes = loader.discover("qp.strategy.strategies")
        for name, cls in classes.items():
            print(f"Found: {name}")

        # Auto-register into registry
        registry = StrategyRegistry()
        loader.register_all(
            registry,
            configs={
                "momentum_v1": {"lookback": 60, "variant": "residual"},
            },
        )
    """

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def discover(
        self,
        package: str = "qp.strategy.strategies",
    ) -> dict[str, type]:
        """Find all BaseStrategy subclasses in a package.

        Args:
            package: Fully qualified Python package name to scan.

        Returns:
            {class_name: class} mapping for all BaseStrategy subclasses.
        """
        try:
            pkg = importlib.import_module(package)
        except ImportError:
            return {}

        # Ensure the package has a path
        if not hasattr(pkg, "__path__"):
            return {}

        classes: dict[str, type] = {}

        for _, module_name, _ in pkgutil.iter_modules(pkg.__path__, pkg.__name__ + "."):
            try:
                mod = importlib.import_module(module_name)
                for name, obj in inspect.getmembers(mod, inspect.isclass):
                    if (
                        issubclass(obj, BaseStrategy)
                        and obj is not BaseStrategy
                        and not inspect.isabstract(obj)
                    ):
                        classes[name] = obj
            except ImportError:
                continue

        return classes

    # ------------------------------------------------------------------
    # Auto-registration
    # ------------------------------------------------------------------

    def register_all(
        self,
        registry: Any,
        package: str = "qp.strategy.strategies",
        configs: dict[str, dict[str, Any]] | None = None,
        lifecycle=None,
    ) -> list[str]:
        """Discover and register all strategies into a StrategyRegistry.

        Args:
            registry: StrategyRegistry instance.
            package: Package to scan for BaseStrategy subclasses.
            configs: {strategy_id: config_dict} for instantiation.
                     Strategies without config use default constructor.
            lifecycle: Default lifecycle for registered strategies.

        Returns:
            List of registered strategy IDs.
        """
        from qp.shared.types import StrategyLifecycle

        if lifecycle is None:
            lifecycle = StrategyLifecycle.RESEARCH
        if configs is None:
            configs = {}

        classes = self.discover(package)
        registered: list[str] = []

        for cls_name, cls in sorted(classes.items()):
            strategy_id = self._default_id(cls_name)

            # Build config
            # Try match by strategy_id first, then class name
            cfg = configs.get(strategy_id, configs.get(cls_name, {}))

            try:
                if cfg:
                    instance = cls(config=cfg)
                else:
                    # Try no-arg constructor
                    instance = cls()

                registry.register(instance, lifecycle=lifecycle)
                registered.append(instance.strategy_id)
            except Exception:
                # Skip strategies that fail to instantiate
                continue

        return registered

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _default_id(cls_name: str) -> str:
        """Generate a default strategy_id from class name."""
        import re

        # PascalCase → snake_case
        name = re.sub(r"(?<!^)(?=[A-Z])", "_", cls_name).lower()
        # Strip trailing "strategy"
        if name.endswith("_strategy"):
            name = name[: -len("_strategy")]
        return f"{name}_v1.0"
