"""Knowledge Archive — long-term memory for experiments, failures, and decisions.

Provides a file-based knowledge management system. Each entry is a
structured Markdown file with YAML frontmatter for machine querying.

Storage layout:
    data/knowledge/
    ├── research_debt/     # Failed hypotheses
    ├── decision_audit/    # Human decision logs
    ├── experiment_summary/# Experiment learnings
    ├── failure_analysis/  # Failure post-mortems
    └── post_mortem/       # Significant event reviews

Usage:
    archive = KnowledgeArchive()
    archive.log_research_debt("Hypothesis: momentum works in bear markets...")
    archive.log_decision("Accepted model v1.3 after review", reason="IC stable")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

# ------------------------------------------------------------------
# Categories
# ------------------------------------------------------------------


class KnowledgeCategory(StrEnum):
    """Categories for knowledge entries."""

    RESEARCH_DEBT = "research_debt"
    DECISION_AUDIT = "decision_audit"
    EXPERIMENT_SUMMARY = "experiment_summary"
    FAILURE_ANALYSIS = "failure_analysis"
    POST_MORTEM = "post_mortem"


# ------------------------------------------------------------------
# Entry data model
# ------------------------------------------------------------------


@dataclass
class KnowledgeEntry:
    """A single knowledge entry with metadata.

    Attributes:
        entry_id: Unique identifier (filename-safe).
        category: KnowledgeCategory.
        title: Short descriptive title.
        content: Main Markdown body.
        tags: Searchable tags.
        created_at: ISO timestamp.
        related: Related entry IDs.
        metadata: Arbitrary extra key-value pairs.
    """

    entry_id: str
    category: KnowledgeCategory
    title: str
    content: str = ""
    tags: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    related: list[str] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)

    def to_markdown(self) -> str:
        """Serialize to Markdown with YAML frontmatter."""
        lines = [
            "---",
            f"id: {self.entry_id}",
            f"category: {self.category.value}",
            f"title: {self.title}",
            f"created_at: {self.created_at}",
            f"tags: [{', '.join(self.tags)}]",
        ]
        if self.related:
            lines.append(f"related: [{', '.join(self.related)}]")
        if self.metadata:
            for k, v in self.metadata.items():
                lines.append(f"{k}: {v}")
        lines.append("---")
        lines.append("")
        lines.append(f"# {self.title}")
        lines.append("")
        lines.append(self.content)
        return "\n".join(lines)

    @classmethod
    def from_markdown(cls, raw: str) -> KnowledgeEntry:
        """Parse a Markdown file with YAML frontmatter."""
        import yaml

        parts = raw.split("---", 2)
        if len(parts) < 3:
            return cls(
                entry_id="unknown",
                category=KnowledgeCategory.RESEARCH_DEBT,
                title="Untitled",
                content=raw,
            )

        frontmatter = yaml.safe_load(parts[1]) or {}
        content = parts[2].strip()

        return cls(
            entry_id=frontmatter.get("id", "unknown"),
            category=KnowledgeCategory(frontmatter.get("category", "research_debt")),
            title=frontmatter.get("title", "Untitled"),
            content=content,
            tags=frontmatter.get("tags", []),
            created_at=frontmatter.get("created_at", ""),
            related=frontmatter.get("related", []),
            metadata={
                k: str(v)
                for k, v in frontmatter.items()
                if k not in ("id", "category", "title", "created_at", "tags", "related")
            },
        )


# ------------------------------------------------------------------
# Template generators
# ------------------------------------------------------------------


EXPERIMENT_SUMMARY_TEMPLATE = """## Background
<!-- What problem were you trying to solve? What was the motivation? -->

{background}

## Hypothesis
<!-- What did you expect to find? Be specific. -->

{hypothesis}

## Method
<!-- What did you do? Data, features, model, CV approach. -->

{method}

## Results
<!-- What happened? Include key metrics. -->

{results}

## Lessons Learned
<!-- What would you do differently? What surprised you? -->

{lessons}

## Action Items
<!-- What follow-up work is needed? -->

{action_items}
"""

FAILURE_ANALYSIS_TEMPLATE = """## Event Summary
<!-- What failed? When? How was it detected? -->

{event_summary}

## Root Cause Analysis
<!-- Why did it happen? Use 5-Whys or similar method. -->

{root_cause}

## Impact Assessment
<!-- Financial impact, model performance, data quality, trust. -->

{impact}

## Detection
<!-- How quickly was this caught? Could it have been caught sooner? -->

{detection}

## Mitigation
<!-- What was done to stop the damage? What safeguards are now in place? -->

{mitigation}

## Prevention
<!-- What process or code changes prevent recurrence? -->

{prevention}

## Classification
<!-- Category: Overfitting | Data Leakage | Market Regime | Implementation Bug | External -->

**Category**: {category}
**Severity**: {severity} (1-5, 5=worst)
"""

POST_MORTEM_TEMPLATE = """## Incident Timeline
<!-- Chronological account of what happened. -->

{timeline}

## What Went Well
<!-- Things that worked during the incident response. -->

{went_well}

## What Went Wrong
<!-- Things that failed or could have been better. -->

{went_wrong}

## Where We Got Lucky
<!-- Near-misses or fortunate coincidences. -->

{lucky}

## Root Causes
<!-- Underlying causes, not symptoms. -->

{root_causes}

## Action Items
<!-- Specific, assigned, time-bound follow-ups. -->

{action_items}

## Risk Assessment
<!-- Likelihood of recurrence and residual risk. -->

**Likelihood**: {likelihood} (Low/Medium/High)
**Impact**: {impact} (Low/Medium/High)
**Residual Risk**: {residual_risk}
"""

DECISION_AUDIT_TEMPLATE = """## Context
<!-- What was the situation? What alternatives were considered? -->

{context}

## Decision
<!-- What was decided? Who made the call? -->

{decision}

## Rationale
<!-- Why this choice? What was the expected outcome? -->

{rationale}

## Alternatives Considered
<!-- What else was on the table and why was it rejected? -->

{alternatives}

## Outcome
<!-- What actually happened? (Fill in later during review.) -->

{outcome}

## Review
<!-- Did the decision turn out well? What would we change? (Fill in later.) -->

{review}
"""


# ------------------------------------------------------------------
# Knowledge Archive Manager
# ------------------------------------------------------------------


class KnowledgeArchive:
    """File-based knowledge archive manager.

    Reads and writes structured Markdown files under a data directory.
    Provides search, filtering, and template generation.

    Usage:
        archive = KnowledgeArchive(base_dir="data/knowledge")
        archive.create_experiment_summary(
            title="Momentum factor in 2024 bear market",
            background="...",
            hypothesis="...",
            method="...",
            results="...",
            lessons="...",
        )
        entries = archive.search(tags=["momentum"])
    """

    def __init__(self, base_dir: str = "data/knowledge") -> None:
        self._base = Path(base_dir)
        self._ensure_directories()

    def _ensure_directories(self) -> None:
        """Create category directories if they don't exist."""
        for cat in KnowledgeCategory:
            (self._base / cat.value).mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Entry creation
    # ------------------------------------------------------------------

    def create_entry(
        self,
        category: KnowledgeCategory,
        title: str,
        content: str,
        tags: list[str] | None = None,
        related: list[str] | None = None,
        metadata: dict[str, str] | None = None,
    ) -> KnowledgeEntry:
        """Create and persist a knowledge entry.

        Args:
            category: Knowledge category.
            title: Short descriptive title.
            content: Markdown body content.
            tags: Searchable tags.
            related: Related entry IDs.
            metadata: Extra key-value pairs.

        Returns:
            The created KnowledgeEntry.
        """
        import re
        from datetime import datetime

        # Generate ID: timestamp + slugified title
        ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:50]
        entry_id = f"{ts}-{slug}"

        entry = KnowledgeEntry(
            entry_id=entry_id,
            category=category,
            title=title,
            content=content,
            tags=tags or [],
            created_at=datetime.now(UTC).isoformat(),
            related=related or [],
            metadata=metadata or {},
        )

        # Write to file
        filepath = self._base / category.value / f"{entry_id}.md"
        filepath.write_text(entry.to_markdown(), encoding="utf-8")

        return entry

    # Convenience methods using templates

    def create_experiment_summary(
        self,
        title: str,
        background: str = "",
        hypothesis: str = "",
        method: str = "",
        results: str = "",
        lessons: str = "",
        action_items: str = "",
        tags: list[str] | None = None,
    ) -> KnowledgeEntry:
        """Create an experiment summary entry."""
        content = EXPERIMENT_SUMMARY_TEMPLATE.format(
            background=background or "(待补充 / TBD)",
            hypothesis=hypothesis or "(待补充 / TBD)",
            method=method or "(待补充 / TBD)",
            results=results or "(待补充 / TBD)",
            lessons=lessons or "(待补充 / TBD)",
            action_items=action_items or "(待补充 / TBD)",
        )
        return self.create_entry(
            category=KnowledgeCategory.EXPERIMENT_SUMMARY,
            title=title,
            content=content,
            tags=tags,
        )

    def create_failure_analysis(
        self,
        title: str,
        event_summary: str = "",
        root_cause: str = "",
        impact: str = "",
        detection: str = "",
        mitigation: str = "",
        prevention: str = "",
        category: str = "TBD",
        severity: str = "3",
        tags: list[str] | None = None,
    ) -> KnowledgeEntry:
        """Create a failure analysis entry."""
        content = FAILURE_ANALYSIS_TEMPLATE.format(
            event_summary=event_summary or "(待补充 / TBD)",
            root_cause=root_cause or "(待补充 / TBD)",
            impact=impact or "(待补充 / TBD)",
            detection=detection or "(待补充 / TBD)",
            mitigation=mitigation or "(待补充 / TBD)",
            prevention=prevention or "(待补充 / TBD)",
            category=category,
            severity=severity,
        )
        return self.create_entry(
            category=KnowledgeCategory.FAILURE_ANALYSIS,
            title=title,
            content=content,
            tags=tags,
        )

    def create_post_mortem(
        self,
        title: str,
        timeline: str = "",
        went_well: str = "",
        went_wrong: str = "",
        lucky: str = "",
        root_causes: str = "",
        action_items: str = "",
        likelihood: str = "Low",
        impact: str = "Low",
        residual_risk: str = "Low",
        tags: list[str] | None = None,
    ) -> KnowledgeEntry:
        """Create a post-mortem entry."""
        content = POST_MORTEM_TEMPLATE.format(
            timeline=timeline or "(待补充 / TBD)",
            went_well=went_well or "(待补充 / TBD)",
            went_wrong=went_wrong or "(待补充 / TBD)",
            lucky=lucky or "(N/A)",
            root_causes=root_causes or "(待补充 / TBD)",
            action_items=action_items or "(待补充 / TBD)",
            likelihood=likelihood,
            impact=impact,
            residual_risk=residual_risk,
        )
        return self.create_entry(
            category=KnowledgeCategory.POST_MORTEM,
            title=title,
            content=content,
            tags=tags,
        )

    def create_decision_audit(
        self,
        title: str,
        context: str = "",
        decision: str = "",
        rationale: str = "",
        alternatives: str = "",
        outcome: str = "",
        review: str = "",
        tags: list[str] | None = None,
    ) -> KnowledgeEntry:
        """Create a decision audit log entry."""
        content = DECISION_AUDIT_TEMPLATE.format(
            context=context or "(待补充 / TBD)",
            decision=decision or "(待补充 / TBD)",
            rationale=rationale or "(待补充 / TBD)",
            alternatives=alternatives or "(N/A)",
            outcome=outcome or "(待追踪 / Pending)",
            review=review or "(待复盘 / Pending review)",
        )
        return self.create_entry(
            category=KnowledgeCategory.DECISION_AUDIT,
            title=title,
            content=content,
            tags=tags,
        )

    def create_research_debt(
        self,
        title: str,
        content: str,
        tags: list[str] | None = None,
    ) -> KnowledgeEntry:
        """Log a failed/abandoned research hypothesis."""
        return self.create_entry(
            category=KnowledgeCategory.RESEARCH_DEBT,
            title=title,
            content=content,
            tags=tags,
        )

    # ------------------------------------------------------------------
    # Querying
    # ------------------------------------------------------------------

    def get(self, category: KnowledgeCategory, entry_id: str) -> KnowledgeEntry | None:
        """Retrieve a single entry by category and ID."""
        filepath = self._base / category.value / f"{entry_id}.md"
        if not filepath.exists():
            return None
        raw = filepath.read_text(encoding="utf-8")
        return KnowledgeEntry.from_markdown(raw)

    def list_entries(
        self,
        category: KnowledgeCategory | None = None,
        tags: list[str] | None = None,
        limit: int = 50,
    ) -> list[KnowledgeEntry]:
        """List entries, optionally filtered by category and tags.

        Args:
            category: Filter by category (None = all).
            tags: Filter by tags (any match).
            limit: Max entries to return.

        Returns:
            List of KnowledgeEntry, newest first.
        """
        categories = [category] if category else list(KnowledgeCategory)
        entries: list[KnowledgeEntry] = []

        for cat in categories:
            cat_dir = self._base / cat.value
            if not cat_dir.exists():
                continue
            for filepath in sorted(cat_dir.glob("*.md"), reverse=True):
                try:
                    raw = filepath.read_text(encoding="utf-8")
                    entry = KnowledgeEntry.from_markdown(raw)
                    if tags and not any(t in entry.tags for t in tags):
                        continue
                    entries.append(entry)
                except Exception:
                    continue

        # Sort by created_at (newest first) and limit
        entries.sort(key=lambda e: e.created_at, reverse=True)
        return entries[:limit]

    def search(self, query: str, limit: int = 50) -> list[KnowledgeEntry]:
        """Full-text search across titles, content, and tags.

        Args:
            query: Search text (case-insensitive).
            limit: Max results.

        Returns:
            Matching entries, best matches first.
        """
        q = query.lower()
        results: list[tuple[KnowledgeEntry, int]] = []

        for cat in KnowledgeCategory:
            cat_dir = self._base / cat.value
            if not cat_dir.exists():
                continue
            for filepath in cat_dir.glob("*.md"):
                try:
                    raw = filepath.read_text(encoding="utf-8")
                    entry = KnowledgeEntry.from_markdown(raw)
                    score = 0
                    if q in entry.title.lower():
                        score += 3
                    if q in entry.content.lower():
                        score += 1
                    if any(q in t.lower() for t in entry.tags):
                        score += 2
                    if score > 0:
                        results.append((entry, score))
                except Exception:
                    continue

        results.sort(key=lambda x: x[1], reverse=True)
        return [e for e, _ in results[:limit]]

    def stats(self) -> dict[str, int]:
        """Get entry counts per category."""
        counts: dict[str, int] = {}
        for cat in KnowledgeCategory:
            cat_dir = self._base / cat.value
            if cat_dir.exists():
                counts[cat.value] = len(list(cat_dir.glob("*.md")))
            else:
                counts[cat.value] = 0
        counts["total"] = sum(counts.values())
        return counts
