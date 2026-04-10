from __future__ import annotations

import pytest

from agentic_memory.core.knowledge import (
    Accuracy,
    Domain,
    KnowledgeEntry,
    KnowledgeId,
    Source,
    SourceType,
    UserUnderstanding,
    is_substantially_equal,
)


def test_knowledge_id_generate_uses_k_prefix() -> None:
    generated = KnowledgeId.generate()
    assert str(generated).startswith("k-")


def test_knowledge_entry_roundtrip_serialization() -> None:
    entry = KnowledgeEntry(
        title="Rust Ownership",
        content="Each value has one owner.",
        domain=" Rust ",
        tags=["rust", "ownership", "rust"],
        accuracy=Accuracy.VERIFIED,
        sources=[
            Source(
                type=SourceType.MEMORY_DISTILLATION,
                ref="memory/2026-04-10/rust.md",
                summary="Ownership notes",
            )
        ],
        source_type=SourceType.AUTONOMOUS_RESEARCH,
        user_understanding=UserUnderstanding.FAMILIAR,
        related=[KnowledgeId.generate()],
    )

    payload = entry.to_dict()
    restored = KnowledgeEntry.from_dict(payload)

    assert payload["accuracy"] == "verified"
    assert payload["source_type"] == "autonomous_research"
    assert payload["user_understanding"] == "familiar"
    assert restored.id == entry.id
    assert restored.domain == "rust"
    assert restored.tags == ["rust", "ownership"]
    assert restored.sources == entry.sources
    assert restored.to_dict() == payload


def test_knowledge_entry_rejects_invalid_accuracy() -> None:
    with pytest.raises(ValueError):
        KnowledgeEntry(
            title="Invalid",
            content="Accuracy should fail.",
            domain="python",
            accuracy="wrong",
            source_type=SourceType.USER_TAUGHT,
        )


def test_knowledge_entry_add_sources_merges_without_replacing_existing() -> None:
    original = Source(
        type=SourceType.MEMORY_DISTILLATION,
        ref="memory/2026-04-10/original.md",
        summary="Original source",
    )
    extra = Source(
        type=SourceType.AUTONOMOUS_RESEARCH,
        ref="https://example.com/rust",
        summary="External source",
    )
    entry = KnowledgeEntry(
        title="Merge sources",
        content="content",
        domain="rust",
        sources=[original],
        source_type=SourceType.MEMORY_DISTILLATION,
    )

    entry.add_sources([extra, original])

    assert entry.sources == [original, extra]


def test_domain_normalization_and_substantial_equality() -> None:
    assert Domain.normalize("  Python  ") == "python"
    assert Domain.normalize("coding style") == "coding-style"
    assert Domain.normalize("  Coding   Style  ") == "coding-style"
    assert Domain.normalize("code_review / guide!") == "code-review-guide"
    assert is_substantially_equal("A  B", "A B")
    assert not is_substantially_equal("A B", "a b")
