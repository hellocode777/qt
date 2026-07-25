"""Strategy Version Tree — structured strategy evolution tracking.

Per docs/11_12.md L12-2.3: Track strategy version lineage as a directed
tree. Each node captures what changed, why, and the performance delta
from the parent version.

Enables queries like:
  - "What was the full evolution of alpha_multi_factor?"
  - "Which version first added anti-chase logic?"
  - "Show me the IC trajectory across all versions."

Storage: JSON file under data/knowledge/version_tree.json, plus
Markdown entries per version in KnowledgeArchive.

Usage:
    tree = StrategyVersionTree()
    tree.register_version(
        strategy_name="alpha_multi_factor",
        version="v2.1",
        parent_version="v2.0",
        changelog="Added P0 safety triggers to KillSwitch pipeline.",
        ic_mean=0.025,
        sharpe=0.45,
    )
    lineage = tree.get_lineage("alpha_multi_factor")
    # → [v1.0, v2.0, v2.1]
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from qp.knowledge.archive import KnowledgeArchive, KnowledgeCategory

DEFAULT_VERSION_TREE_PATH = "data/knowledge/version_tree.json"


@dataclass
class VersionNode:
    """One node in a strategy version tree.

    Attributes:
        strategy_name: Which strategy family.
        version: Version string (e.g., "v2.1").
        parent_version: Parent version (empty for root).
        created_at: ISO timestamp.
        changelog: What changed from parent.
        author: Who made the change.
        ic_mean: IC performance at registration time.
        sharpe: Sharpe at registration time.
        max_drawdown_pct: Max DD at registration time.
        config_snapshot: Key config parameters for this version.
        tags: Searchable tags.
        status: active / retired / experimental.
    """

    strategy_name: str = ""
    version: str = ""
    parent_version: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    changelog: str = ""
    author: str = ""
    ic_mean: float = 0.0
    sharpe: float = 0.0
    max_drawdown_pct: float = 0.0
    config_snapshot: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    status: str = "active"  # active / retired / experimental

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_name": self.strategy_name,
            "version": self.version,
            "parent_version": self.parent_version,
            "created_at": self.created_at,
            "changelog": self.changelog,
            "author": self.author,
            "ic_mean": self.ic_mean,
            "sharpe": self.sharpe,
            "max_drawdown_pct": self.max_drawdown_pct,
            "config_snapshot": self.config_snapshot,
            "tags": self.tags,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> VersionNode:
        return cls(
            strategy_name=d.get("strategy_name", ""),
            version=d.get("version", ""),
            parent_version=d.get("parent_version", ""),
            created_at=d.get("created_at", ""),
            changelog=d.get("changelog", ""),
            author=d.get("author", ""),
            ic_mean=float(d.get("ic_mean", 0.0)),
            sharpe=float(d.get("sharpe", 0.0)),
            max_drawdown_pct=float(d.get("max_drawdown_pct", 0.0)),
            config_snapshot=d.get("config_snapshot", {}),
            tags=d.get("tags", []),
            status=d.get("status", "active"),
        )


class StrategyVersionTree:
    """Version tree for tracking strategy evolution across time.

    Each strategy family gets its own lineage. Every version links to
    its parent, forming a chain from root to latest. Performance
    deltas at each node enable "which change improved IC?" queries.

    Usage:
        tree = StrategyVersionTree()
        tree.register_version(
            strategy_name="alpha_multi_factor",
            version="v2.1",
            parent_version="v2.0",
            changelog="Fixed direction sign bug in weight optimization.",
            ic_mean=0.028,
        )
        lineage = tree.get_lineage("alpha_multi_factor")
        diff = tree.diff("alpha_multi_factor", "v2.0", "v2.1")
    """

    def __init__(self, filepath: str = DEFAULT_VERSION_TREE_PATH) -> None:
        self._filepath = Path(filepath)
        self._filepath.parent.mkdir(parents=True, exist_ok=True)
        self._archive = KnowledgeArchive()
        self._nodes: dict[str, VersionNode] = {}
        self._load()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_version(
        self,
        strategy_name: str,
        version: str,
        parent_version: str = "",
        changelog: str = "",
        author: str = "",
        ic_mean: float = 0.0,
        sharpe: float = 0.0,
        max_drawdown_pct: float = 0.0,
        config_snapshot: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        status: str = "active",
    ) -> VersionNode:
        """Register a new version in the tree.

        If parent_version is specified, it must already exist or be
        empty (root node). Automatically retires the parent version
        when a new child is registered.

        Args:
            strategy_name: Strategy family name.
            version: New version string.
            parent_version: Direct parent version (empty = root).
            changelog: What changed.
            author: Who made the change.
            ic_mean: IC at registration.
            sharpe: Sharpe at registration.
            max_drawdown_pct: Max DD at registration.
            config_snapshot: Key config params.
            tags: Tags.
            status: active / retired / experimental.

        Returns:
            The created VersionNode.

        Raises:
            ValueError: If version already exists.
        """
        key = _make_key(strategy_name, version)
        if key in self._nodes:
            raise ValueError(f"Version already exists: {key}")

        # Auto-retire parent
        if parent_version:
            parent_key = _make_key(strategy_name, parent_version)
            if parent_key in self._nodes:
                self._nodes[parent_key].status = "retired"

        node = VersionNode(
            strategy_name=strategy_name,
            version=version,
            parent_version=parent_version,
            changelog=changelog,
            author=author,
            ic_mean=ic_mean,
            sharpe=sharpe,
            max_drawdown_pct=max_drawdown_pct,
            config_snapshot=config_snapshot or {},
            tags=tags or [],
            status=status,
        )

        self._nodes[key] = node
        self._save()
        self._archive_version(node)
        return node

    # ------------------------------------------------------------------
    # Query API
    # ------------------------------------------------------------------

    def get(self, strategy_name: str, version: str) -> VersionNode | None:
        """Get a specific version node."""
        return self._nodes.get(_make_key(strategy_name, version))

    def get_latest(self, strategy_name: str) -> VersionNode | None:
        """Get the latest (newest) version of a strategy."""
        family = self._get_family(strategy_name)
        if not family:
            return None
        # Return the one with latest created_at
        return max(family, key=lambda n: n.created_at)

    def get_lineage(self, strategy_name: str) -> list[VersionNode]:
        """Get the full version lineage from root to latest.

        Returns:
            Sorted list: [root, ..., latest].
        """
        family = sorted(self._get_family(strategy_name), key=lambda n: n.created_at)
        if not family:
            return []

        # Build parent chain
        by_version = {n.version: n for n in family}
        result: list[VersionNode] = []

        # Find root (no parent or parent not in family)
        current = None
        for n in family:
            if not n.parent_version or n.parent_version not in by_version:
                current = n
                break
        if current is None:
            current = family[0]

        # Walk the chain
        while current:
            result.append(current)
            # Find child
            children = [n for n in family if n.parent_version == current.version]
            current = children[0] if children else None

        return result

    def diff(
        self,
        strategy_name: str,
        from_version: str,
        to_version: str,
    ) -> dict[str, Any]:
        """Compute performance delta between two versions.

        Args:
            strategy_name: Strategy family.
            from_version: Base version.
            to_version: Target version.

        Returns:
            Dict with ic_delta, sharpe_delta, dd_delta, changelog.
        """
        v_from = self.get(strategy_name, from_version)
        v_to = self.get(strategy_name, to_version)

        if not v_from or not v_to:
            return {"error": "Version not found"}

        return {
            "strategy_name": strategy_name,
            "from_version": from_version,
            "to_version": to_version,
            "ic_delta": v_to.ic_mean - v_from.ic_mean,
            "sharpe_delta": v_to.sharpe - v_from.sharpe,
            "dd_delta": v_to.max_drawdown_pct - v_from.max_drawdown_pct,
            "changelog": v_to.changelog,
            "from_status": v_from.status,
            "to_status": v_to.status,
        }

    def list_strategies(self) -> list[str]:
        """List all strategy families."""
        return sorted({n.strategy_name for n in self._nodes.values()})

    def list_versions(self, strategy_name: str) -> list[VersionNode]:
        """List all versions of a strategy, newest first."""
        family = self._get_family(strategy_name)
        return sorted(family, key=lambda n: n.created_at, reverse=True)

    def query_by_tag(self, tag: str) -> list[VersionNode]:
        """Find versions with a specific tag."""
        return [n for n in self._nodes.values() if tag in n.tags]

    def stats(self, strategy_name: str = "") -> dict[str, Any]:
        """Version tree statistics."""
        if strategy_name:
            family = self._get_family(strategy_name)
            return {
                "strategy_name": strategy_name,
                "n_versions": len(family),
                "latest": family[-1].version if family else "N/A",
                "root": family[0].version if family else "N/A",
                "active": sum(1 for n in family if n.status == "active"),
                "retired": sum(1 for n in family if n.status == "retired"),
            }

        all_strategies = self.list_strategies()
        return {
            "n_strategies": len(all_strategies),
            "n_total_versions": len(self._nodes),
            "strategies": {s: self.stats(s) for s in all_strategies},
        }

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load version tree from JSON file."""
        if not self._filepath.exists():
            return
        try:
            data = json.loads(self._filepath.read_text(encoding="utf-8"))
            for node_data in data.get("nodes", []):
                node = VersionNode.from_dict(node_data)
                self._nodes[_make_key(node.strategy_name, node.version)] = node
        except (json.JSONDecodeError, KeyError):
            pass

    def _save(self) -> None:
        """Persist version tree to JSON file."""
        data = {
            "updated_at": datetime.now(UTC).isoformat(),
            "n_nodes": len(self._nodes),
            "nodes": [n.to_dict() for n in self._nodes.values()],
        }
        self._filepath.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _get_family(self, strategy_name: str) -> list[VersionNode]:
        """Get all versions for a strategy family."""
        return [n for n in self._nodes.values() if n.strategy_name == strategy_name]

    def _archive_version(self, node: VersionNode) -> None:
        """Also create a research debt entry documenting this version."""
        try:
            content = (
                f"## Version {node.version}\n\n"
                f"- **Strategy**: {node.strategy_name}\n"
                f"- **Parent**: {node.parent_version or 'ROOT'}\n"
                f"- **Created**: {node.created_at[:19]}\n"
                f"- **Author**: {node.author or 'system'}\n"
                f"- **Status**: {node.status}\n\n"
                f"## Changelog\n\n{node.changelog}\n\n"
                f"## Performance at Registration\n\n"
                f"- IC Mean: {node.ic_mean:.4f}\n"
                f"- Sharpe: {node.sharpe:.2f}\n"
                f"- Max DD: {node.max_drawdown_pct:.1f}%\n\n"
                f"## Config Snapshot\n\n"
                f"```json\n{json.dumps(node.config_snapshot, indent=2, ensure_ascii=False)}\n```\n"
            )
            self._archive.create_entry(
                category=KnowledgeCategory.RESEARCH_DEBT,
                title=f"[{node.strategy_name}] {node.version}",
                content=content,
                tags=node.tags + [node.strategy_name, node.version],
            )
        except Exception:
            pass


def _make_key(strategy_name: str, version: str) -> str:
    """Create a unique key for a version node."""
    return f"{strategy_name}@{version}"
