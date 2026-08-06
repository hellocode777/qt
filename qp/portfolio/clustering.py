"""Dynamic Risk Clustering — hierarchical clustering on return correlations.

Per docs/7_Portfolio_Risk_Layer.md 精细化建议 §1:
  "不要只依赖传统的行业划分（申万/中信），建议直接对候选股票计算
   近 60 日收益率的相关系数矩阵，并使用简单的层次聚类
   （Hierarchical Clustering / Agglomerative Clustering）
   划分出 3~5 个动态 Risk Clusters。"

Why: stocks like 贵州茅台(白酒) and 伊利股份(乳业) have different Shenwan
industries but 0.92 correlation — same risk. Clustering captures this.

Pipeline:
  1. Compute daily return correlation matrix from price data
  2. Convert correlation → distance (1 - |corr|)
  3. Agglomerative clustering (Ward / average linkage)
  4. Cut dendrogram to produce 3~5 clusters
  5. Assign each stock to a Risk Cluster

Usage:
    from qp.portfolio.clustering import RiskClusterer

    clusterer = RiskClusterer(n_clusters=(3, 5))
    labels = clusterer.fit_predict(prices_df, symbols)
    # → {"600519.SH": "Cluster_1", "000858.SZ": "Cluster_1", ...}
    report = clusterer.get_cluster_report(labels)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

import numpy as np
import polars as pl

from qp.portfolio.correlation import CorrelationAnalyzer


@dataclass
class RiskClusterer:
    """Dynamic risk-based clustering via hierarchical agglomerative clustering.

    Attributes:
        n_clusters: (min, max) number of clusters. The dendrogram is cut
            to produce between min and max clusters.
        linkage_method: "ward", "average", "complete", or "single".
        lookback: Days of return history for correlation estimation.
        min_cluster_size: Minimum stocks per cluster.
    """

    n_clusters: tuple[int, int] = (3, 5)
    linkage_method: str = "ward"
    lookback: int = 60
    min_cluster_size: int = 1

    def __post_init__(self) -> None:
        if self.linkage_method not in ("ward", "average", "complete", "single"):
            raise ValueError(f"Unknown linkage method: {self.linkage_method}")

    # ------------------------------------------------------------------
    # Main API
    # ------------------------------------------------------------------

    def fit_predict(
        self,
        prices: pl.DataFrame,
        symbols: list[str],
    ) -> dict[str, str]:
        """Cluster stocks by return correlation.

        Args:
            prices: DataFrame with [trade_date, symbol, close].
            symbols: Stock codes to cluster.

        Returns:
            {symbol: cluster_label} mapping (e.g. "Cluster_1").
        """
        if len(symbols) < 2:
            return dict.fromkeys(symbols, "Cluster_1")

        # 1. Compute correlation matrix
        corr_matrix = self._correlation_matrix(prices, symbols)
        if corr_matrix is None or len(corr_matrix) < 2:
            return {s: f"Cluster_{i}" for i, s in enumerate(symbols, 1)}

        # 2. Correlation → distance
        dist_matrix = 1.0 - np.abs(corr_matrix)
        # Ensure symmetry and zero diagonal
        dist_matrix = (dist_matrix + dist_matrix.T) / 2.0
        np.fill_diagonal(dist_matrix, 0.0)

        # 3. Hierarchical clustering
        try:
            from scipy.cluster.hierarchy import linkage
        except ImportError:
            # Fallback: use simple threshold-based grouping
            return self._fallback_cluster(corr_matrix, symbols)

        # Condensed distance matrix (upper triangle)
        n = len(symbols)
        triu_idx = np.triu_indices(n, k=1)
        condensed = dist_matrix[triu_idx]

        # Ward's method requires Euclidean distance; use correlation distance
        Z = linkage(condensed, method=self.linkage_method)

        # 4. Cut dendrogram for 3-5 clusters
        n_min, n_max = self.n_clusters
        labels = self._cut_dendrogram(Z, n, n_min, n_max)

        # 5. Map to symbol → cluster names
        return {symbols[i]: f"Cluster_{labels[i]}" for i in range(n)}

    # ------------------------------------------------------------------
    # Cluster report
    # ------------------------------------------------------------------

    def get_cluster_report(
        self,
        labels: dict[str, str],
        prices: pl.DataFrame | None = None,
    ) -> dict[str, Any]:
        """Generate a cluster summary report.

        Args:
            labels: {symbol: cluster_label} from fit_predict.
            prices: Optional price data for intra-cluster correlation.

        Returns:
            {
                "n_clusters": int,
                "clusters": {label: {"size": int, "symbols": [...], "intra_corr": float}},
                "silhouette": float (if prices provided),
            }
        """
        clusters: dict[str, list[str]] = {}
        for sym, lbl in labels.items():
            clusters.setdefault(lbl, []).append(sym)

        report: dict[str, Any] = {
            "n_clusters": len(clusters),
            "clusters": {},
        }

        for lbl, syms in sorted(clusters.items()):
            cluster_info: dict[str, Any] = {
                "size": len(syms),
                "symbols": syms,
                "intra_corr": None,
            }
            # Compute intra-cluster correlation if prices available
            if prices is not None and len(syms) >= 2:
                corr = CorrelationAnalyzer(lookback=self.lookback)
                matrix = corr.get_correlation_matrix(prices, syms)
                if not matrix.is_empty():
                    vals = [
                        matrix[c].drop_nulls().mean()
                        for c in syms
                        if c in matrix.columns
                    ]
                    if vals:
                        cluster_info["intra_corr"] = round(
                            float(np.mean(cast("list[float]", vals))), 3
                        )
            report["clusters"][lbl] = cluster_info

        return report

    # ------------------------------------------------------------------
    # Constraint: cluster weight limit
    # ------------------------------------------------------------------

    def check_cluster_concentration(
        self,
        weights: dict[str, float],
        labels: dict[str, str],
        max_per_cluster: float = 0.30,
    ) -> list[str]:
        """Check if any cluster exceeds the weight limit.

        Args:
            weights: {symbol: weight} mapping.
            labels: {symbol: cluster_label} from fit_predict.
            max_per_cluster: Maximum weight allowed per cluster.

        Returns:
            List of violation messages (empty = all pass).
        """
        cluster_wt: dict[str, float] = {}
        for sym, w in weights.items():
            lbl = labels.get(sym, "Unknown")
            cluster_wt[lbl] = cluster_wt.get(lbl, 0.0) + w

        violations: list[str] = []
        for lbl, wt in sorted(cluster_wt.items(), key=lambda x: -x[1]):
            if wt > max_per_cluster:
                violations.append(
                    f"Cluster {lbl}: weight {wt:.1%} > {max_per_cluster:.0%}"
                )
        return violations

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _correlation_matrix(
        self,
        prices: pl.DataFrame,
        symbols: list[str],
    ) -> np.ndarray | None:
        """Compute N×N correlation matrix from price data."""
        analyzer = CorrelationAnalyzer(threshold=0.0, lookback=self.lookback)
        corr_df = analyzer.get_correlation_matrix(prices, symbols)
        if corr_df.is_empty():
            return None

        # Get column order
        cols = [c for c in corr_df.columns if c != "symbol"]
        if len(cols) < 2:
            return None

        # Build numpy matrix
        n = len(cols)
        mat = np.eye(n)
        col_to_idx = {c: i for i, c in enumerate(cols)}

        for row in corr_df.iter_rows(named=True):
            sym = row["symbol"]
            if sym not in col_to_idx:
                continue
            i = col_to_idx[sym]
            for j, c in enumerate(cols):
                mat[i, j] = float(row.get(c, 1.0 if i == j else 0.0))

        return mat

    def _cut_dendrogram(
        self,
        Z: np.ndarray,
        n: int,
        n_min: int,
        n_max: int,
    ) -> np.ndarray:
        """Cut dendrogram to get between n_min and n_max clusters."""
        from scipy.cluster.hierarchy import fcluster

        # Try different distance thresholds
        best_labels = None
        best_score = -1.0

        for _ in range(20):
            # Vary cutting height
            t = np.random.uniform(0.2, 0.8) * Z[-1, 2]
            labels = fcluster(Z, t, criterion="distance")

            n_unique = len(set(labels))
            if n_min <= n_unique <= n_max:
                # Check cluster size balance
                sizes = [np.sum(labels == lbl) for lbl in set(labels)]
                if min(sizes) >= self.min_cluster_size:
                    # Score = prefer more balanced clusters
                    score = -np.std(sizes) / max(np.mean(sizes), 1)
                    if score > best_score or best_labels is None:
                        best_score = score
                        best_labels = labels.copy()

        if best_labels is None:
            # Default: use n_max clusters
            best_labels = fcluster(Z, n_max, criterion="maxclust")

        return best_labels

    def _fallback_cluster(
        self,
        corr_matrix: np.ndarray,
        symbols: list[str],
    ) -> dict[str, str]:
        """Simple threshold-based clustering when scipy is unavailable."""
        n = len(symbols)
        threshold = 0.7
        visited: set[int] = set()
        clusters: list[set[int]] = []

        for i in range(n):
            if i in visited:
                continue
            cluster: set[int] = {i}
            visited.add(i)
            for j in range(n):
                if j not in visited and abs(corr_matrix[i, j]) > threshold:
                    cluster.add(j)
                    visited.add(j)
            clusters.append(cluster)

        result: dict[str, str] = {}
        for cid, cluster in enumerate(clusters, 1):
            for idx in cluster:
                result[symbols[idx]] = f"Cluster_{cid}"
        return result
