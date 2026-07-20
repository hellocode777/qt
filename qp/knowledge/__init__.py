"""Knowledge Layer — long-term memory and organizational learning.

Provides:
  - KnowledgeArchive: file-based knowledge management (Markdown + YAML frontmatter)
  - KnowledgeEntry: structured entry with metadata, tags, and search
  - KnowledgeCategory: RESEARCH_DEBT | DECISION_AUDIT | EXPERIMENT_SUMMARY | FAILURE_ANALYSIS | POST_MORTEM
  - Templates: experiment summary, failure analysis, post-mortem, decision audit

The Knowledge Layer is intentionally lightweight — a Markdown folder.
See plan_v1.md §9 M5.5.
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

__all__ = [
    "KnowledgeArchive",
    "KnowledgeCategory",
    "KnowledgeEntry",
    # Templates
    "EXPERIMENT_SUMMARY_TEMPLATE",
    "FAILURE_ANALYSIS_TEMPLATE",
    "POST_MORTEM_TEMPLATE",
    "DECISION_AUDIT_TEMPLATE",
]
