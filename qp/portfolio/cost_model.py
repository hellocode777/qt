"""Transaction Cost Model — A-share realistic trading costs.

Models the four components of trading costs in China A-share market:
  1. Stamp tax (印花税): 0.05%, sell only
  2. Commission (佣金): 0.025%, buy + sell
  3. Slippage (滑点): base 0.1%, adjusted for volatility
  4. Market impact (冲击成本): sqrt model from Almgren-Chriss

Costs are subtracted from expected returns to produce net returns.
"""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl

# A-share standard rates (2024)
STAMP_TAX_RATE = 0.0005  # 0.05%, sell side only
COMMISSION_RATE = 0.00025  # 0.025%, both sides
DEFAULT_SLIPPAGE_BPS = 10.0  # 10 bps = 0.1%
DEFAULT_IMPACT_BASE_BPS = 5.0  # 5 bps base for sqrt model


@dataclass
class CostBreakdown:
    """Per-trade cost breakdown."""

    symbol: str
    trade_value: float
    side: str  # BUY / SELL
    stamp_tax: float = 0.0
    commission: float = 0.0
    slippage: float = 0.0
    market_impact: float = 0.0

    @property
    def total_cost(self) -> float:
        return self.stamp_tax + self.commission + self.slippage + self.market_impact

    @property
    def total_cost_pct(self) -> float:
        return self.total_cost / self.trade_value if self.trade_value > 0 else 0.0


class CostModel:
    """Estimates per-trade and portfolio-level transaction costs.

    Usage:
        model = CostModel()
        cost = model.estimate_trade(symbol="600519", trade_value=100000, side="BUY")
        print(f"Cost: {cost.total_cost_pct:.4%}")
    """

    def __init__(
        self,
        stamp_tax_rate: float = STAMP_TAX_RATE,
        commission_rate: float = COMMISSION_RATE,
        slippage_bps: float = DEFAULT_SLIPPAGE_BPS,
    ) -> None:
        self._stamp_tax_rate = stamp_tax_rate
        self._commission_rate = commission_rate
        self._slippage_rate = slippage_bps / 10000.0  # bps → decimal

    # ------------------------------------------------------------------
    # Single trade estimation
    # ------------------------------------------------------------------

    def estimate_trade(
        self,
        symbol: str,
        trade_value: float,
        side: str,
        daily_volume: float | None = None,
        volatility: float | None = None,
    ) -> CostBreakdown:
        """Estimate total cost for a single trade.

        Args:
            symbol: Stock symbol.
            trade_value: Total trade amount in CNY.
            side: "BUY" or "SELL".
            daily_volume: Average daily volume in CNY (for impact model).
            volatility: Annualized volatility (for slippage adjustment).

        Returns:
            CostBreakdown with per-component costs.
        """
        cost = CostBreakdown(symbol=symbol, trade_value=trade_value, side=side)

        # Commission: both sides
        cost.commission = trade_value * self._commission_rate

        # Stamp tax: sell only
        if side.upper() == "SELL":
            cost.stamp_tax = trade_value * self._stamp_tax_rate

        # Slippage: base, adjusted for volatility
        vol_multiplier = (volatility or 0.30) / 0.30  # Normalized to 30% vol
        cost.slippage = trade_value * self._slippage_rate * vol_multiplier

        # Market impact
        if daily_volume is not None and daily_volume > 0:
            cost.market_impact = MarketImpactModel.sqrt_impact(
                trade_value=trade_value,
                daily_volume=daily_volume,
            )

        return cost

    # ------------------------------------------------------------------
    # Portfolio-level estimation
    # ------------------------------------------------------------------

    def estimate_portfolio(
        self,
        orders: list[CostBreakdown],
    ) -> dict:
        """Aggregate costs across all orders.

        Args:
            orders: List of per-trade CostBreakdown objects.

        Returns:
            Dict with total costs and statistics.
        """
        total_value = sum(o.trade_value for o in orders)
        total_cost = sum(o.total_cost for o in orders)

        return {
            "total_trade_value": round(total_value, 2),
            "total_cost": round(total_cost, 2),
            "total_cost_pct": round(total_cost / total_value * 100, 4) if total_value > 0 else 0.0,
            "stamp_tax": round(sum(o.stamp_tax for o in orders), 2),
            "commission": round(sum(o.commission for o in orders), 2),
            "slippage": round(sum(o.slippage for o in orders), 2),
            "market_impact": round(sum(o.market_impact for o in orders), 2),
            "n_trades": len(orders),
        }

    def estimate_turnover_cost(
        self,
        total_capital: float,
        turnover_pct: float,
        n_stocks: int = 10,
    ) -> float:
        """Estimate cost for a given turnover level.

        Args:
            total_capital: Total portfolio capital.
            turnover_pct: Turnover fraction (0.0–1.0).
            n_stocks: Number of stocks traded.

        Returns:
            Estimated total cost in CNY.
        """
        traded_value = total_capital * turnover_pct
        per_stock = traded_value / max(n_stocks, 1)

        buy_cost = per_stock * self._commission_rate + per_stock * self._slippage_rate
        sell_cost = (
            per_stock * self._commission_rate
            + per_stock * self._stamp_tax_rate
            + per_stock * self._slippage_rate
        )

        # Assume half buys, half sells
        n_buys = n_stocks // 2
        n_sells = n_stocks - n_buys
        return n_buys * buy_cost + n_sells * sell_cost

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def stamp_tax_rate(self) -> float:
        return self._stamp_tax_rate

    @property
    def commission_rate(self) -> float:
        return self._commission_rate

    @property
    def slippage_rate(self) -> float:
        return self._slippage_rate


class MarketImpactModel:
    """Models price impact of trades using sqrt formula.

    Based on Almgren-Chriss framework: impact scales with sqrt of
    trade size relative to daily volume.

    I = σ * sqrt(Q / ADV)  where:
      σ = daily volatility
      Q = trade quantity
      ADV = average daily volume
    """

    @staticmethod
    def sqrt_impact(
        trade_value: float,
        daily_volume: float,
        participation_rate: float | None = None,
        base_bps: float = DEFAULT_IMPACT_BASE_BPS,
    ) -> float:
        """Compute sqrt market impact in CNY.

        Args:
            trade_value: Trade amount in CNY.
            daily_volume: Average daily volume in CNY.
            participation_rate: Max fraction of daily volume (default: 0.10 = 10%).
            base_bps: Base impact in basis points at 1% participation.

        Returns:
            Estimated market impact cost in CNY.
        """
        if daily_volume <= 0 or trade_value <= 0:
            return 0.0

        participation = trade_value / daily_volume
        max_p = participation_rate or 0.10

        if participation > max_p:
            return trade_value * 0.01  # 1% penalty for exceeding liquidity limit

        # Impact = base_bps * sqrt(participation / 1%)
        impact_pct = (base_bps / 10000.0) * (participation / 0.01) ** 0.5
        return trade_value * impact_pct

    @staticmethod
    def compute_adv(prices: pl.DataFrame, lookback: int = 20) -> dict[str, float]:
        """Compute average daily volume (in CNY) for each symbol.

        Args:
            prices: DataFrame with [trade_date, symbol, close, volume].
            lookback: Number of days for average.

        Returns:
            symbol → ADV in CNY mapping.
        """
        if prices.is_empty():
            return {}

        df = prices.sort(["symbol", "trade_date"])

        # Estimate daily volume in CNY (close * volume)
        if "volume" in df.columns:
            df = df.with_columns(
                (pl.col("close") * pl.col("volume")).alias("daily_value")
            )
        else:
            return {}

        # Last N days average
        df = df.group_by("symbol").tail(lookback)
        adv = df.group_by("symbol").agg(
            pl.col("daily_value").mean().alias("adv")
        )

        return dict(zip(adv["symbol"].to_list(), adv["adv"].to_list(), strict=True))
