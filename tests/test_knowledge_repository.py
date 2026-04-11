from __future__ import annotations

import json
from pathlib import Path

from agentic_memory.core.knowledge import (
    Accuracy,
    KnowledgeEntry,
    KnowledgeRepository,
    ReferenceType,
    Source,
    SourceType,
)


def test_knowledge_repository_save_load_delete_roundtrip(tmp_memory_dir: Path) -> None:
    repository = KnowledgeRepository(tmp_memory_dir)
    entry = KnowledgeEntry(
        title="Rust ownership",
        content="Ownership rules summary",
        domain="rust",
        accuracy=Accuracy.VERIFIED,
        sources=[
            Source(
                type=ReferenceType.MEMORY_NOTE,
                ref="memory/2026-04-10/rust.md",
                summary="Rust note",
            )
        ],
        source_type=SourceType.MEMORY_DISTILLATION,
    )

    path = repository.save(entry)
    index_path = tmp_memory_dir / "_knowledge.jsonl"

    assert path.exists()
    assert index_path.exists()
    loaded = repository.load(entry.id)
    assert loaded.to_dict() == entry.to_dict()
    assert repository.find_by_id(entry.id) is not None
    assert repository.list_all()[0].id == entry.id

    index_rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines()]
    assert index_rows[0]["path"] == f"knowledge/{entry.id}.md"
    assert index_rows[0]["content_preview"] == "Ownership rules summary"

    assert repository.delete(entry.id) is True
    assert not path.exists()
    assert repository.find_by_id(entry.id) is None
    assert repository.list_all() == []
