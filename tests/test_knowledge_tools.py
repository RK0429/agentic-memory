from __future__ import annotations

import json
from pathlib import Path

from agentic_memory.core.knowledge import KnowledgeRepository
from agentic_memory.server import (
    memory_knowledge_add,
    memory_knowledge_delete,
    memory_knowledge_search,
    memory_knowledge_update,
)


def test_memory_knowledge_tools_add_search_update_flow(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    repository = KnowledgeRepository(tmp_memory_dir)

    base = json.loads(
        memory_knowledge_add(
            title="Rust ownership",
            content="Ownership explains moves and borrows.",
            domain="rust",
            tags=["rust"],
            accuracy="likely",
            sources=[
                {
                    "type": "memory_distillation",
                    "ref": "memory/2026-04-10/rust.md",
                    "summary": "Ownership note",
                }
            ],
            memory_dir=str(tmp_memory_dir),
        )
    )
    related = json.loads(
        memory_knowledge_add(
            title="Rust lifetimes",
            content="Lifetimes connect borrows to scopes.",
            domain="rust",
            memory_dir=str(tmp_memory_dir),
        )
    )

    assert base["ok"] is True
    assert base["path"] == f"knowledge/{base['id']}.md"

    search_payload = json.loads(
        memory_knowledge_search(
            query="ownership",
            memory_dir=str(tmp_memory_dir),
        )
    )
    assert search_payload["ok"] is True
    assert search_payload["results"][0]["id"] == base["id"]
    assert "Ownership explains moves" in search_payload["results"][0]["content_snippet"]
    assert search_payload["results"][0]["score"] > 0

    update_payload = json.loads(
        memory_knowledge_update(
            id=base["id"],
            accuracy="verified",
            user_understanding="familiar",
            related=[related["id"]],
            sources=[
                {
                    "type": "autonomous_research",
                    "ref": "https://doc.rust-lang.org/book/ch04-01-what-is-ownership.html",
                    "summary": "Rust Book ownership",
                }
            ],
            tags=["rust", "systems"],
            memory_dir=str(tmp_memory_dir),
        )
    )

    assert update_payload == {"ok": True, "id": base["id"]}

    updated_entry = repository.load(base["id"])
    related_entry = repository.load(related["id"])
    assert str(updated_entry.accuracy) == "verified"
    assert str(updated_entry.user_understanding) == "familiar"
    assert len(updated_entry.sources) == 2
    assert updated_entry.tags == ["rust", "systems"]
    assert [str(related_id) for related_id in updated_entry.related] == [related["id"]]
    assert [str(related_id) for related_id in related_entry.related] == [base["id"]]


def test_memory_knowledge_add_returns_secret_warning(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)

    payload = json.loads(
        memory_knowledge_add(
            title="Secret example",
            content='api_key="AbCdEf1234567890"',
            domain="security",
            memory_dir=str(tmp_memory_dir),
        )
    )

    assert payload["ok"] is True
    assert payload["warnings"] == [
        "Content may contain secrets (detected: generic_api_token). Review before sharing."
    ]


def test_memory_knowledge_add_malformed_sources_returns_validation_error(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)

    payload = json.loads(
        memory_knowledge_add(
            title="Rust ownership",
            content="Ownership summary",
            domain="rust",
            sources=[{"type": "user_taught", "ref": "memory/2026-04-10/rust.md"}],
            memory_dir=str(tmp_memory_dir),
        )
    )

    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert "{type, ref, summary}" in payload["hint"]
    assert "summary" in payload["hint"]


def test_memory_knowledge_add_invalid_source_type_returns_valid_values(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)

    payload = json.loads(
        memory_knowledge_add(
            title="Rust ownership",
            content="Ownership summary",
            domain="rust",
            source_type="invalid_source_type",
            memory_dir=str(tmp_memory_dir),
        )
    )

    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert "is not a valid SourceType" in payload["message"]
    assert '"memory_distillation"' in payload["hint"]
    assert '"autonomous_research"' in payload["hint"]
    assert '"user_taught"' in payload["hint"]


def test_memory_knowledge_add_defaults_source_type_to_user_taught(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    repository = KnowledgeRepository(tmp_memory_dir)

    payload = json.loads(
        memory_knowledge_add(
            title="Rust ownership",
            content="Ownership summary",
            domain="rust",
            memory_dir=str(tmp_memory_dir),
        )
    )

    assert payload["ok"] is True
    entry = repository.load(payload["id"])
    assert str(entry.source_type) == "user_taught"


def test_memory_knowledge_update_returns_secret_warning_for_content_update(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)

    added = json.loads(
        memory_knowledge_add(
            title="Secret example",
            content="Safe content",
            domain="security",
            memory_dir=str(tmp_memory_dir),
        )
    )

    payload = json.loads(
        memory_knowledge_update(
            id=added["id"],
            content='auth_token="AbCdEf1234567890"',
            memory_dir=str(tmp_memory_dir),
        )
    )

    assert payload["ok"] is True
    assert payload["id"] == added["id"]
    assert payload["warnings"] == [
        "Content may contain secrets (detected: generic_api_token). Review before sharing."
    ]


def test_memory_knowledge_update_malformed_sources_returns_validation_error(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)

    added = json.loads(
        memory_knowledge_add(
            title="Rust ownership",
            content="Ownership summary",
            domain="rust",
            memory_dir=str(tmp_memory_dir),
        )
    )

    payload = json.loads(
        memory_knowledge_update(
            id=added["id"],
            sources=[{"type": "user_taught", "ref": "memory/2026-04-10/rust.md"}],
            memory_dir=str(tmp_memory_dir),
        )
    )

    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert "{type, ref, summary}" in payload["hint"]
    assert "summary" in payload["hint"]


def test_memory_knowledge_tools_validate_inputs_and_duplicates(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)

    search_payload = json.loads(memory_knowledge_search(memory_dir=str(tmp_memory_dir)))
    assert search_payload["ok"] is False
    assert search_payload["error_type"] == "validation_error"

    added = json.loads(
        memory_knowledge_add(
            title="Rust ownership",
            content="Ownership summary",
            domain="rust",
            memory_dir=str(tmp_memory_dir),
        )
    )
    assert added["ok"] is True

    duplicate_payload = json.loads(
        memory_knowledge_add(
            title="Rust ownership",
            content="Ownership   summary",
            domain="Rust",
            memory_dir=str(tmp_memory_dir),
        )
    )
    assert duplicate_payload["ok"] is False
    assert duplicate_payload["error_type"] == "validation_error"
    assert "Duplicate knowledge entry" in duplicate_payload["message"]

    update_payload = json.loads(
        memory_knowledge_update(id=added["id"], memory_dir=str(tmp_memory_dir))
    )
    assert update_payload["ok"] is False
    assert update_payload["error_type"] == "validation_error"


def test_memory_knowledge_delete_removes_entry_and_related_links(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    repository = KnowledgeRepository(tmp_memory_dir)

    base = json.loads(
        memory_knowledge_add(
            title="Rust ownership",
            content="Ownership summary",
            domain="rust",
            memory_dir=str(tmp_memory_dir),
        )
    )
    related = json.loads(
        memory_knowledge_add(
            title="Rust borrowing",
            content="Borrowing summary",
            domain="rust",
            related=[base["id"]],
            memory_dir=str(tmp_memory_dir),
        )
    )

    payload = json.loads(
        memory_knowledge_delete(
            id=base["id"],
            memory_dir=str(tmp_memory_dir),
        )
    )

    assert payload == {
        "ok": True,
        "deleted_id": base["id"],
        "title": "Rust ownership",
        "deleted": True,
    }
    assert repository.find_by_id(base["id"]) is None
    assert not (tmp_memory_dir / f"knowledge/{base['id']}.md").exists()
    assert repository.load(related["id"]).related == []


def test_memory_knowledge_delete_with_reason_echoes_back(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    added = json.loads(
        memory_knowledge_add(
            title="Rust ownership",
            content="Ownership summary",
            domain="rust",
            memory_dir=str(tmp_memory_dir),
        )
    )

    payload = json.loads(
        memory_knowledge_delete(
            id=added["id"],
            reason="cleanup duplicate knowledge",
            memory_dir=str(tmp_memory_dir),
        )
    )

    assert payload == {
        "ok": True,
        "deleted_id": added["id"],
        "title": "Rust ownership",
        "deleted": True,
        "reason": "cleanup duplicate knowledge",
    }
