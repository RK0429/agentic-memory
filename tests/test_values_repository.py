from __future__ import annotations

import json
from pathlib import Path

from agentic_memory.core.values import Evidence, SourceType, ValuesEntry, ValuesRepository


def test_values_repository_save_load_delete_roundtrip(tmp_memory_dir: Path) -> None:
    repository = ValuesRepository(tmp_memory_dir)
    entry = ValuesEntry(
        description="Prefer reversible changes.",
        category="workflow",
        confidence=0.9,
        evidence=[
            Evidence(
                ref="memory/2026-04-10/review.md",
                summary="Review note",
                date="2026-04-10",
            )
        ],
        total_evidence_count=6,
        source_type=SourceType.USER_TAUGHT,
        promoted=True,
        promoted_confidence=0.9,
    )

    path = repository.save(entry)
    index_path = tmp_memory_dir / "_values.jsonl"

    assert path.exists()
    assert index_path.exists()
    loaded = repository.load(entry.id)
    assert loaded.to_dict() == entry.to_dict()
    assert repository.find_by_id(entry.id) is not None
    assert repository.list_all()[0].id == entry.id

    index_rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines()]
    assert index_rows[0]["path"] == f"values/{entry.id}.md"
    assert index_rows[0]["evidence_count"] == 6
    assert index_rows[0]["promoted"] is True
    assert index_rows[0]["promoted_confidence"] == 0.9

    assert repository.delete(entry.id) is True
    assert not path.exists()
    assert repository.find_by_id(entry.id) is None
    assert repository.list_all() == []
