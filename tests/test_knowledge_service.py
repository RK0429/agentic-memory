from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from agentic_memory.core.knowledge import (
    Accuracy,
    DuplicateKnowledgeError,
    KnowledgeRepository,
    KnowledgeService,
    SourceType,
    UserUnderstanding,
)


def test_knowledge_service_add_creates_entry_and_secret_warning(
    tmp_memory_dir: Path,
) -> None:
    service = KnowledgeService()

    entry = service.add(
        memory_dir=tmp_memory_dir,
        title="Rust ownership",
        content='api_key="AbCdEf1234567890"',
        domain="rust",
        source_type=SourceType.USER_TAUGHT,
    )

    stored = KnowledgeRepository(tmp_memory_dir).load(entry.id)
    assert stored.id == entry.id
    assert service.last_warnings == [
        "Content may contain secrets (detected: generic_api_token). Review before sharing."
    ]


def test_knowledge_service_add_rejects_substantially_equivalent_duplicate(
    tmp_memory_dir: Path,
) -> None:
    service = KnowledgeService()
    service.add(
        memory_dir=tmp_memory_dir,
        title="Rust ownership",
        content="Ownership explains moves.",
        domain="rust",
    )

    with pytest.raises(DuplicateKnowledgeError):
        service.add(
            memory_dir=tmp_memory_dir,
            title="Rust ownership",
            content="Ownership   explains moves.",
            domain="Rust",
        )


def test_knowledge_service_add_links_related_bidirectionally(tmp_memory_dir: Path) -> None:
    service = KnowledgeService()
    first = service.add(
        memory_dir=tmp_memory_dir,
        title="Rust ownership",
        content="Ownership summary",
        domain="rust",
    )

    second = service.add(
        memory_dir=tmp_memory_dir,
        title="Rust lifetimes",
        content="Lifetime summary",
        domain="rust",
        related=[str(first.id)],
    )

    refreshed_first = KnowledgeRepository(tmp_memory_dir).load(first.id)
    assert [str(related_id) for related_id in refreshed_first.related] == [str(second.id)]


def test_knowledge_service_search_supports_query_domain_filters_and_sorting(
    tmp_memory_dir: Path,
) -> None:
    service = KnowledgeService()
    repository = KnowledgeRepository(tmp_memory_dir)

    rust_old = service.add(
        memory_dir=tmp_memory_dir,
        title="Rust ownership",
        content="Ownership and borrowing rules",
        domain="rust",
        accuracy=Accuracy.LIKELY,
        user_understanding=UserUnderstanding.FAMILIAR,
    )
    rust_new = service.add(
        memory_dir=tmp_memory_dir,
        title="Rust lifetimes",
        content="Lifetimes connect borrows to scopes",
        domain="rust",
        accuracy=Accuracy.VERIFIED,
        user_understanding=UserUnderstanding.PROFICIENT,
    )
    service.add(
        memory_dir=tmp_memory_dir,
        title="Python generators",
        content="yield from examples",
        domain="python",
    )

    old_payload = repository.load(rust_old.id).to_dict()
    old_payload["updated_at"] = dt.datetime(2026, 4, 10, 10, 0, 0).isoformat()
    repository.save(repository.load(rust_old.id).from_dict(old_payload))

    new_payload = repository.load(rust_new.id).to_dict()
    new_payload["updated_at"] = dt.datetime(2026, 4, 10, 11, 0, 0).isoformat()
    repository.save(repository.load(rust_new.id).from_dict(new_payload))

    query_results = service.search(
        memory_dir=tmp_memory_dir,
        query="ownership",
        top=5,
    )
    assert query_results[0][1].id == rust_old.id

    filtered_results = service.search(
        memory_dir=tmp_memory_dir,
        query="rust",
        accuracy=Accuracy.VERIFIED,
        user_understanding=UserUnderstanding.PROFICIENT,
        top=5,
    )
    assert [str(entry.id) for _, entry in filtered_results] == [str(rust_new.id)]

    domain_only_results = service.search(
        memory_dir=tmp_memory_dir,
        domain="rust",
        top=5,
    )
    assert [str(entry.id) for _, entry in domain_only_results] == [
        str(rust_new.id),
        str(rust_old.id),
    ]


def test_knowledge_service_search_requires_query_or_domain(tmp_memory_dir: Path) -> None:
    service = KnowledgeService()

    with pytest.raises(ValueError):
        service.search(memory_dir=tmp_memory_dir)


def test_knowledge_service_update_merges_sources_and_related_bidirectionally(
    tmp_memory_dir: Path,
) -> None:
    service = KnowledgeService()
    repository = KnowledgeRepository(tmp_memory_dir)

    first = service.add(
        memory_dir=tmp_memory_dir,
        title="Rust ownership",
        content="Ownership summary",
        domain="rust",
        sources=[
            {
                "type": "memory_distillation",
                "ref": "memory/2026-04-10/rust.md",
                "summary": "Ownership note",
            }
        ],
    )
    second = service.add(
        memory_dir=tmp_memory_dir,
        title="Rust lifetimes",
        content="Lifetime summary",
        domain="rust",
    )

    updated = service.update(
        memory_dir=tmp_memory_dir,
        id=str(first.id),
        sources=[
            {
                "type": "autonomous_research",
                "ref": "https://doc.rust-lang.org/book/ch10-03-lifetime-syntax.html",
                "summary": "Rust Book lifetimes",
            }
        ],
        related=[str(second.id)],
        tags=["systems", "rust"],
    )

    assert len(updated.sources) == 2
    assert updated.tags == ["systems", "rust"]
    assert [str(related_id) for related_id in updated.related] == [str(second.id)]

    refreshed_second = repository.load(second.id)
    assert [str(related_id) for related_id in refreshed_second.related] == [str(first.id)]


def test_knowledge_service_update_rejects_duplicate_content_and_missing_fields(
    tmp_memory_dir: Path,
) -> None:
    service = KnowledgeService()
    first = service.add(
        memory_dir=tmp_memory_dir,
        title="Rust ownership",
        content="Ownership summary",
        domain="rust",
    )
    second = service.add(
        memory_dir=tmp_memory_dir,
        title="Rust ownership",
        content="Borrow checker summary",
        domain="rust",
    )

    with pytest.raises(ValueError):
        service.update(memory_dir=tmp_memory_dir, id=str(first.id))

    with pytest.raises(DuplicateKnowledgeError):
        service.update(
            memory_dir=tmp_memory_dir,
            id=str(second.id),
            content="Ownership summary",
        )


def test_knowledge_service_delete_returns_metadata_and_removes_backlinks(
    tmp_memory_dir: Path,
) -> None:
    service = KnowledgeService()
    repository = KnowledgeRepository(tmp_memory_dir)
    first = service.add(
        memory_dir=tmp_memory_dir,
        title="Rust ownership",
        content="Ownership summary",
        domain="rust",
    )
    second = service.add(
        memory_dir=tmp_memory_dir,
        title="Rust lifetimes",
        content="Lifetime summary",
        domain="rust",
        related=[str(first.id)],
    )

    payload = service.delete(
        memory_dir=tmp_memory_dir,
        id=str(first.id),
        reason="cleanup duplicate knowledge",
    )

    assert payload == {
        "deleted_id": str(first.id),
        "title": "Rust ownership",
        "deleted": True,
        "reason": "cleanup duplicate knowledge",
    }
    assert repository.find_by_id(first.id) is None
    assert repository.load(second.id).related == []
