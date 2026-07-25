"""Knowledge Layer — long-term memory and organizational learning.

Provides:
  - KnowledgeArchive: file-based knowledge management (Markdown + YAML frontmatter)
  - KnowledgeEntry: structured entry with metadata, tags, and search
  - KnowledgeCategory: RESEARCH_DEBT | DECISION_AUDIT | EXPERIMENT_SUMMARY | FAILURE_ANALYSIS | POST_MORTEM
  - Templates: experiment summary, failure analysis, post-mortem, decision audit
  - DecisionAuditLogger: structured trade decision records (T2 table)
  - FailureArchiveLogger: stop-loss / black-swan event records (T3 table)
  - RegimeNoteLogger: market regime ↔ strategy performance notes

The Knowledge Layer is intentionally lightweight — a Markdown folder + Parquet tables.
See plan_v1.md §9 M5.5 and docs/11_12.md.
"""

from qp.knowledge.archive import (
    DECISION_AUDIT_TEMPLATE,
    EXPERIMENT_SUMMARY_TEMPLATE,
    FAILURE_ANALYSIS_TEMPLATE,
    POST_MORTEM_TEMPLATE,
    KnowledgeArchive,
    KnowledgeCategory,
    KnowledgeEntry,
)
from qp.knowledge.cluster_analyzer import (
    BlacklistRule,
    FailureClusterAnalyzer,
    FeatureSuggestion,
    StrategyAdjustment,
)
from qp.knowledge.decision_audit_logger import (
    DecisionAuditLogger,
    DecisionRecord,
    ReasonTag,
    TradeAction,
)
from qp.knowledge.failure_archive_logger import (
    FailureArchiveLogger,
    FailureRecord,
    FailureType,
)
from qp.knowledge.regime_notes import (
    RegimeNote,
    RegimeNoteLogger,
)
from qp.knowledge.version_tree import (
    StrategyVersionTree,
    VersionNode,
)

__all__ = [
    "KnowledgeArchive",
    "KnowledgeCategory",
    "KnowledgeEntry",
    # Templates
    "EXPERIMENT_SUMMARY_TEMPLATE",
    "FAILURE_ANALYSIS_TEMPLATE",
    "POST_MORTEM_TEMPLATE",
    "DECISION_AUDIT_TEMPLATE",
    # Decision audit logger (T2)
    "DecisionAuditLogger",
    "DecisionRecord",
    "ReasonTag",
    "TradeAction",
    # Failure archive logger (T3)
    "FailureArchiveLogger",
    "FailureRecord",
    "FailureType",
    # Regime notes
    "RegimeNote",
    "RegimeNoteLogger",
    # Version tree
    "StrategyVersionTree",
    "VersionNode",
    # Cluster analyzer
    "BlacklistRule",
    "FailureClusterAnalyzer",
    "FeatureSuggestion",
    "StrategyAdjustment",
]
