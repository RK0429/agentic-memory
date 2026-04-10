from __future__ import annotations

from agentic_memory.core.distillation import KnowledgeCandidate
from agentic_memory.core.knowledge import KnowledgeEntry, SourceType
from agentic_memory.core.knowledge.integrator import (
    KnowledgeIntegrationAction,
    KnowledgeIntegrator,
)


def _entry(title: str, content: str, domain: str) -> KnowledgeEntry:
    return KnowledgeEntry(
        title=title,
        content=content,
        domain=domain,
        source_type=SourceType.MEMORY_DISTILLATION,
    )


def _candidate(title: str, content: str, domain: str) -> KnowledgeCandidate:
    return KnowledgeCandidate(
        title=title,
        content=content,
        domain=domain,
        source_ref=f"memory/2026-04-10/{title}.md",
        source_summary=f"{title} summary",
    )


def test_integrate_skips_duplicate_knowledge() -> None:
    integrator = KnowledgeIntegrator()
    existing = [_entry("Rust ownership", "Ownership explains moves and borrows.", "rust")]

    result = integrator.integrate(
        _candidate("Rust ownership", "Ownership explains moves and borrows.", "rust"),
        existing,
    )

    assert result.action is KnowledgeIntegrationAction.SKIP_DUPLICATE
    assert result.target_id is None


def test_integrate_merges_same_topic_knowledge() -> None:
    integrator = KnowledgeIntegrator()
    existing = [
        _entry(
            "Rust ownership",
            "Ownership explains moves and borrows.",
            "rust",
        )
    ]

    result = integrator.integrate(
        _candidate(
            "Rust ownership",
            "Ownership also clarifies how borrowing affects mutation.",
            "rust",
        ),
        existing,
    )

    assert result.action is KnowledgeIntegrationAction.MERGE_EXISTING
    assert result.target_id == str(existing[0].id)
    assert result.merged_content is not None
    assert "Ownership explains moves and borrows." in result.merged_content
    assert "borrowing affects mutation" in result.merged_content


def test_integrate_links_related_knowledge_in_same_domain() -> None:
    integrator = KnowledgeIntegrator()
    existing = [
        _entry(
            "Rust ownership",
            "Ownership controls moves and borrows in Rust.",
            "rust",
        )
    ]

    result = integrator.integrate(
        _candidate(
            "Rust lifetimes",
            "Lifetimes describe how borrows relate to scopes in Rust.",
            "rust",
        ),
        existing,
    )

    assert result.action is KnowledgeIntegrationAction.LINK_RELATED
    assert result.target_id == str(existing[0].id)


def test_integrate_creates_new_for_distinct_knowledge() -> None:
    integrator = KnowledgeIntegrator()
    existing = [_entry("Rust ownership", "Ownership explains moves and borrows.", "rust")]

    result = integrator.integrate(
        _candidate("Python generators", "Generators use yield for lazy iteration.", "python"),
        existing,
    )

    assert result.action is KnowledgeIntegrationAction.CREATE_NEW
    assert result.target_id is None
