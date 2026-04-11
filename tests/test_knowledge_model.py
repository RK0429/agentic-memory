from __future__ import annotations

import pytest

from agentic_memory.core.knowledge import (
    Accuracy,
    Domain,
    KnowledgeEntry,
    KnowledgeId,
    ReferenceType,
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
                type=ReferenceType.MEMORY_NOTE,
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
    assert payload["sources"][0]["type"] == "memory_note"
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
        type=ReferenceType.MEMORY_NOTE,
        ref="memory/2026-04-10/original.md",
        summary="Original source",
    )
    extra = Source(
        type=ReferenceType.WEB,
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


def test_source_from_dict_accepts_legacy_source_type_values() -> None:
    """Legacy SourceType values should map to corresponding ReferenceType."""
    legacy_mapping = {
        "memory_distillation": ReferenceType.MEMORY_NOTE,
        "autonomous_research": ReferenceType.WEB,
        "user_taught": ReferenceType.USER_DIRECT,
    }

    for legacy_value, expected in legacy_mapping.items():
        source = Source.from_dict({"type": legacy_value, "ref": "test", "summary": "test"})
        assert source.type == expected


def test_source_from_dict_rejects_invalid_type() -> None:
    """Invalid type values should raise ValueError."""
    with pytest.raises(ValueError):
        Source.from_dict({"type": "invalid_type", "ref": "test", "summary": "test"})


def test_knowledge_entry_roundtrip_with_new_reference_type() -> None:
    """New ReferenceType values should roundtrip correctly."""
    entry = KnowledgeEntry(
        title="Test",
        content="Test content",
        domain="test",
        sources=[Source(type=ReferenceType.DOCUMENT, ref="doc.pdf", summary="A doc")],
        source_type=SourceType.USER_TAUGHT,
    )

    payload = entry.to_dict()
    restored = KnowledgeEntry.from_dict(payload)

    assert restored.sources[0].type == ReferenceType.DOCUMENT
    assert payload["sources"][0]["type"] == "document"


def test_knowledge_entry_loads_legacy_source_in_sources() -> None:
    """Legacy source values inside KnowledgeEntry payloads should remain loadable."""
    entry = KnowledgeEntry.from_dict(
        {
            "title": "Test",
            "content": "Test content",
            "domain": "test",
            "sources": [
                {
                    "type": "memory_distillation",
                    "ref": "memory/2026-04-10/test.md",
                    "summary": "Legacy note",
                }
            ],
            "source_type": "user_taught",
        }
    )

    assert entry.sources[0].type == ReferenceType.MEMORY_NOTE
    assert entry.to_dict()["sources"][0]["type"] == "memory_note"


def test_domain_normalization_and_substantial_equality() -> None:
    assert Domain.normalize("  Python  ") == "python"
    assert Domain.normalize("coding style") == "coding-style"
    assert Domain.normalize("  Coding   Style  ") == "coding-style"
    assert Domain.normalize("code_review / guide!") == "code-review-guide"
    assert is_substantially_equal("A  B", "A B")
    assert not is_substantially_equal("A B", "a b")
