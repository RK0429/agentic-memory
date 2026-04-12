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
        origin=SourceType.USER_TAUGHT,
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


def test_values_repository_loads_legacy_source_type_frontmatter(
    tmp_memory_dir: Path,
) -> None:
    repository = ValuesRepository(tmp_memory_dir)
    path = tmp_memory_dir / "values" / "v-11111111-1111-1111-1111-111111111111.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "---",
                'id: "v-11111111-1111-1111-1111-111111111111"',
                'category: "workflow"',
                "confidence: 0.9",
                "evidence: []",
                "total_evidence_count: 5",
                'source_type: "user_taught"',
                "promoted: false",
                "promoted_at: null",
                "promoted_confidence: null",
                "demoted_at: null",
                "demotion_reason: null",
                'created_at: "2026-04-10T09:00:00"',
                'updated_at: "2026-04-10T09:00:00"',
                "---",
                "Legacy description",
                "",
            ]
        ),
        encoding="utf-8",
    )

    loaded = repository.load("v-11111111-1111-1111-1111-111111111111")

    assert loaded.origin == SourceType.USER_TAUGHT
    assert loaded.to_dict()["origin"] == "user_taught"
