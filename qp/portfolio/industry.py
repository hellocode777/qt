"""IndustryMapper — maps stock symbols to industry sectors.

Hardcoded sector classification for A-share stocks currently
in the default symbol set.  Extended symbols fall through to "Other".

In Phase 4 this will be replaced by a formal sector classification
loaded from the Data Layer (e.g. Shenwan industry codes).
"""

from __future__ import annotations

# Sector mapping for the 18 default stocks
# Sourced from public Shenwan industry classification (2024 edition)
_SECTOR_MAP: dict[str, tuple[str, str]] = {
    # Banking (申万银行)
    "000001": ("Financials", "Banking"),
    "600000": ("Financials", "Banking"),
    "600036": ("Financials", "Banking"),
    "601166": ("Financials", "Banking"),
    # Consumer / Food & Beverage / Home Appliances (申万食品饮料/家用电器)
    "000333": ("Consumer", "HomeAppliances"),
    "000651": ("Consumer", "HomeAppliances"),
    "000858": ("Consumer", "FoodBeverage"),
    "600519": ("Consumer", "FoodBeverage"),
    "601888": ("Consumer", "Retail"),
    # Technology / Electronics (申万电子)
    "002415": ("Technology", "Electronics"),
    "002475": ("Technology", "Electronics"),
    "300750": ("Technology", "NewEnergy"),
    # Real Estate (申万房地产)
    "000002": ("RealEstate", "RealEstate"),
    # Healthcare / Pharmaceuticals (申万医药生物)
    "600276": ("Healthcare", "Pharma"),
    # Materials / Building Materials (申万建筑材料)
    "600585": ("Materials", "BuildingMaterials"),
    # Energy / Power Equipment (申万电力设备)
    "601012": ("Energy", "SolarPower"),
    # Insurance (申万非银金融)
    "601318": ("Financials", "Insurance"),
}


class IndustryMapper:
    """Maps stock symbols to industry sector and sub-sector.

    Usage:
        mapper = IndustryMapper()
        sector = mapper.get_sector("600519")   # "Consumer"
        group = mapper.get_sector_group("600519")  # "FoodBeverage"

        # Get all symbols in a sector
        banks = mapper.get_symbols_in_sector("Financials")  # ["000001", ...]
    """

    def __init__(self) -> None:
        pass

    def get_sector(self, symbol: str) -> str:
        """Get the top-level sector for a symbol.

        Returns "Other" for unknown symbols.
        """
        mapping = _SECTOR_MAP.get(symbol)
        return mapping[0] if mapping else "Other"

    def get_sector_group(self, symbol: str) -> str:
        """Get the sub-sector group for a symbol.

        Returns "Other" for unknown symbols.
        """
        mapping = _SECTOR_MAP.get(symbol)
        return mapping[1] if mapping else "Other"

    def get_symbols_in_sector(self, sector: str) -> list[str]:
        """Get all known symbols belonging to a sector."""
        return [sym for sym, (s, _) in _SECTOR_MAP.items() if s == sector]

    def get_sector_weights(
        self,
        holdings: dict[str, float],
    ) -> dict[str, float]:
        """Compute sector exposure weights from a holdings dict.

        Args:
            holdings: symbol → weight mapping (e.g. {"600519": 0.08, ...})

        Returns:
            sector → total_weight mapping.
        """
        sector_weights: dict[str, float] = {}
        for sym, w in holdings.items():
            sector = self.get_sector(sym)
            sector_weights[sector] = sector_weights.get(sector, 0.0) + w
        return sector_weights
