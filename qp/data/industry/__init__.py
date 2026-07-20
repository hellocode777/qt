"""Industry Classification Data Product — multi-source industry mapping.

Produces a trusted {symbol: industry_name} mapping for all A-share stocks.
Consumers use ``IndustryClassifier`` — they never know which source provided
the classification (Baostock, AkShare, or prefix fallback).

Usage:
    from qp.data.industry import IndustryClassifier, get_industry_map

    classifier = IndustryClassifier()
    industry_map = classifier.get_mapping(["600519", "000858", "300750"])
    # → {"600519": "C15酒、饮料和精制茶制造业", ...}

    # Quick one-shot:
    industry_map = get_industry_map(["600519", "000858"])
"""

from __future__ import annotations

from qp.data.industry.classifier import IndustryClassifier, get_industry_map

__all__ = [
    "IndustryClassifier",
    "get_industry_map",
]
