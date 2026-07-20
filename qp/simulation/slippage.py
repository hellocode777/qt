"""Slippage models — simulate price impact of trades.

Configurable slippage models for realistic backtesting:
  - FixedSlippage: constant bps
  - VolatilitySlippage: scales with volatility
  - SqrtImpactModel: Almgren-Chriss sqrt formula
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np


class BaseSlippageModel(ABC):
    """Abstract slippage model."""

    @abstractmethod
    def compute(
        self,
        price: float,
        volume: int,
        side: str,
        daily_volume: float | None = None,
        volatility: float | None = None,
    ) -> float:
        """Compute slippage per share.

        Args:
            price: Current stock price.
            volume: Trade quantity (shares).
            side: "BUY" or "SELL".
            daily_volume: Average daily volume in shares (for impact models).
            volatility: Annualized volatility (for vol-scaled models).

        Returns:
            Slippage per share in price units.
        """
        ...


class FixedSlippage(BaseSlippageModel):
    """Constant basis point slippage."""

    def __init__(self, bps: float = 10.0) -> None:
        """Args:
            bps: Slippage in basis points (1 bp = 0.01%). Default 10 bps = 0.1%.
        """
        self._rate = bps / 10000.0

    def compute(
        self,
        price: float,
        volume: int,
        side: str,
        daily_volume: float | None = None,
        volatility: float | None = None,
    ) -> float:
        return price * self._rate

    @property
    def rate(self) -> float:
        return self._rate


class VolatilitySlippage(BaseSlippageModel):
    """Volatility-scaled slippage: base_bps * (realized_vol / reference_vol)."""

    def __init__(
        self,
        base_bps: float = 10.0,
        reference_vol: float = 0.30,
    ) -> None:
        """Args:
            base_bps: Base slippage in bps.
            reference_vol: Reference annual vol (default 30%) for normalization.
        """
        self._base_rate = base_bps / 10000.0
        self._reference_vol = reference_vol

    def compute(
        self,
        price: float,
        volume: int,
        side: str,
        daily_volume: float | None = None,
        volatility: float | None = None,
    ) -> float:
        vol = volatility or self._reference_vol
        multiplier = vol / self._reference_vol
        return price * self._base_rate * multiplier


class SqrtImpactModel(BaseSlippageModel):
    """Almgren-Chriss sqrt market impact model.

    impact = base_bps * sqrt(participation_rate / 1%)
    """

    def __init__(self, base_bps: float = 5.0, max_participation: float = 0.10) -> None:
        """Args:
            base_bps: Impact at 1% participation rate in bps.
            max_participation: Maximum participation rate (default 10%).
        """
        self._base_rate = base_bps / 10000.0
        self._max_participation = max_participation

    def compute(
        self,
        price: float,
        volume: int,
        side: str,
        daily_volume: float | None = None,
        volatility: float | None = None,
    ) -> float:
        if daily_volume is None or daily_volume <= 0:
            return 0.0

        trade_value = price * volume
        participation = trade_value / daily_volume

        if participation > self._max_participation:
            return price * 0.01  # Penalty

        impact_pct = self._base_rate * np.sqrt(participation / 0.01)
        return price * impact_pct


# ------------------------------------------------------------------
# Factory
# ------------------------------------------------------------------

def create_slippage_model(model_type: str = "fixed", **kwargs) -> BaseSlippageModel:
    """Create a slippage model by name.

    Args:
        model_type: "fixed" | "volatility" | "sqrt"
        **kwargs: Passed to the model constructor.

    Returns:
        BaseSlippageModel instance.
    """
    models: dict[str, type[BaseSlippageModel]] = {
        "fixed": FixedSlippage,
        "volatility": VolatilitySlippage,
        "sqrt": SqrtImpactModel,
    }
    if model_type not in models:
        raise ValueError(f"Unknown slippage model '{model_type}'. Choose from: {list(models)}")
    return models[model_type](**kwargs)
