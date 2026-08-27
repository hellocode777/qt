"""IndustryMapper — maps stock symbols to industry sectors.

Loads industry classification from ``data/stock_industry.json`` (generated
by the stock-name keyword classifier).  Falls back to a hardcoded map for
the original 18 default stocks, then to "Other".
"""

from __future__ import annotations

import json as _json
from pathlib import Path as _Path

from qp.shared.paths import STOCK_INDUSTRY

# Hardcoded fallback for the 18 original default stocks
# Sourced from public Shenwan industry classification (2024 edition)
_FALLBACK_MAP: dict[str, tuple[str, str]] = {
    # Banking (申万银行)
    "000001": ("Financials", "Banking"),
    "600000": ("Financials", "Banking"),
    "600036": ("Financials", "Banking"),
    "601166": ("Financials", "Banking"),
    # Consumer / Food & Beverage / Home Appliances
    "000333": ("Consumer", "HomeAppliances"),
    "000651": ("Consumer", "HomeAppliances"),
    "000858": ("Consumer", "FoodBeverage"),
    "600519": ("Consumer", "FoodBeverage"),
    "601888": ("Consumer", "Retail"),
    # Technology / Electronics
    "002415": ("Technology", "Electronics"),
    "002475": ("Technology", "Electronics"),
    "300750": ("Technology", "NewEnergy"),
    # Real Estate
    "000002": ("RealEstate", "RealEstate"),
    # Healthcare / Pharmaceuticals
    "600276": ("Healthcare", "Pharma"),
    # Materials / Building Materials
    "600585": ("Materials", "BuildingMaterials"),
    # Energy / Power Equipment
    "601012": ("Energy", "SolarPower"),
    # Insurance
    "601318": ("Financials", "Insurance"),
}

_INDUSTRY_PATH = _Path(STOCK_INDUSTRY)


class IndustryMapper:
    """Maps stock symbols to industry sector and sub-sector.

    Loads from ``data/stock_industry.json`` (name-keyword classifier);
    falls back to hardcoded map, then ``"Other"``.

    Usage:
        mapper = IndustryMapper()
        sector = mapper.get_sector("600519")   # "Consumer"
        group = mapper.get_sector_group("600519")  # "FoodBeverage"
    """

    def __init__(self) -> None:
        self._map: dict[str, tuple[str, str]] = {}
        self._load()

    def _load(self) -> None:
        """Load industry data from the JSON file if available."""
        if _INDUSTRY_PATH.exists():
            try:
                data = _json.loads(_INDUSTRY_PATH.read_text(encoding="utf-8"))
                for code, info in data.items():
                    self._map[code] = (
                        info.get("sector", "Other"),
                        info.get("subsector", "Other"),
                    )
            except Exception:
                pass

    def _lookup(self, clean: str) -> tuple[str, str] | None:
        """Look up sector mapping, preferring non-Other results.

        Priority: fallback map (curated) > JSON file (auto-classified).
        Falls back to JSON if fallback doesn't have the code.
        """
        fb = _FALLBACK_MAP.get(clean)
        if fb is not None:
            return fb
        return self._map.get(clean)

    def get_sector(self, symbol: str) -> str:
        """Get the top-level sector for a symbol.

        Returns ``"Other"`` for unknown symbols.
        """
        clean = symbol.split(".")[0] if "." in symbol else symbol
        mapping = self._lookup(clean)
        return mapping[0] if mapping else "Other"

    def get_sector_group(self, symbol: str) -> str:
        """Get the sub-sector group for a symbol.

        Returns ``"Other"`` for unknown symbols.
        """
        clean = symbol.split(".")[0] if "." in symbol else symbol
        mapping = self._lookup(clean)
        return mapping[1] if mapping else "Other"

    def get_symbols_in_sector(self, sector: str) -> list[str]:
        """Get all known symbols belonging to a sector.

        Fallback map takes priority over JSON file for well-known stocks.
        """
        merged: dict[str, tuple[str, str]] = {**self._map, **_FALLBACK_MAP}
        return [sym for sym, (s, _) in merged.items() if s == sector]

    def get_sector_weights(
        self,
        holdings: dict[str, float],
    ) -> dict[str, float]:
        """Compute sector exposure weights from a holdings dict."""
        sector_weights: dict[str, float] = {}
        for sym, w in holdings.items():
            sector = self.get_sector(sym)
            sector_weights[sector] = sector_weights.get(sector, 0.0) + w
        return sector_weights
