"""Signal Post-Processing — normalization, smoothing, thresholding, confidence.

Per docs/6_Strategy_Engine.md §模块四, Raw Score should go through:
  Raw Score → Normalize → Clip → Threshold → Confidence → Final Score
"""

from qp.strategy.signal.confidence import ConfidenceScorer
from qp.strategy.signal.normalizer import NormMethod, SignalNormalizer
from qp.strategy.signal.smoother import SignalSmoother, SmoothMethod
from qp.strategy.signal.threshold import ClipMethod, SignalClipper, SignalThreshold

__all__ = [
    "SignalNormalizer",
    "NormMethod",
    "SignalSmoother",
    "SmoothMethod",
    "SignalClipper",
    "ClipMethod",
    "SignalThreshold",
    "ConfidenceScorer",
]
