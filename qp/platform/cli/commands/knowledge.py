"""CLI command handlers for the "knowledge" group."""

from __future__ import annotations

import sys

from qp.shared.paths import KNOWLEDGE_DIR


def cmd_knowledge_stats() -> int:
    """Show knowledge archive statistics."""
    from qp.knowledge.archive import KnowledgeArchive

    print("=== QP 知识库统计 / Knowledge Archive Stats ===")
    print()

    archive = KnowledgeArchive()
    stats = archive.stats()

    category_names = {
        "research_debt": "研究债务 / Research Debt",
        "decision_audit": "决策审计 / Decision Audit",
        "experiment_summary": "实验总结 / Experiment Summary",
        "failure_analysis": "失败分析 / Failure Analysis",
        "post_mortem": "事后复盘 / Post Mortem",
    }

    for cat, name in category_names.items():
        count = stats.get(cat, 0)
        bar = "█" * min(count, 30)
        print(f"  {name:40s} {count:3d} {bar}")

    print(f"  {'─' * 55}")
    print(f"  {'总计 / Total':40s} {stats.get('total', 0):3d}")
    print()
    print(f"  存储位置 / Storage: {KNOWLEDGE_DIR}/")
    return 0


def cmd_knowledge_search() -> int:
    """Search knowledge archive."""
    from qp.knowledge.archive import KnowledgeArchive

    if len(sys.argv) < 3:
        print("qp knowledge search <query>", file=sys.stderr)
        return 1

    query = " ".join(sys.argv[2:])
    print(f"=== QP 知识库搜索 / Knowledge Search: '{query}' ===")
    print()

    archive = KnowledgeArchive()
    results = archive.search(query, limit=20)

    if not results:
        print(f"  未找到匹配 '{query}' 的条目。")
        print(f"  No entries match '{query}'.")
        return 0

    print(f"  找到 / Found: {len(results)} 条")
    print()

    for i, entry in enumerate(results, 1):
        cat_names = {
            "research_debt": "研究债务",
            "decision_audit": "决策审计",
            "experiment_summary": "实验总结",
            "failure_analysis": "失败分析",
            "post_mortem": "事后复盘",
        }
        cat_zh = cat_names.get(entry.category.value, entry.category.value)
        print(f"  {i}. [{cat_zh}] {entry.title}")
        print(f"     ID: {entry.entry_id}")
        print(f"     标签 / Tags: {', '.join(entry.tags) if entry.tags else '(无)'}")
        # Show first 120 chars of content
        preview = entry.content.strip()[:120].replace("\n", " ")
        print(f"     预览 / Preview: {preview}...")
        print()

    return 0
