"""Tests for memory_distill_prepare and memory_distill_commit MCP tools."""

from __future__ import annotations

import json
from pathlib import Path

from agentic_memory.core import state
from agentic_memory.core.knowledge import KnowledgeRepository, KnowledgeService, SourceType
from agentic_memory.core.values import ValuesRepository, ValuesService
from agentic_memory.server import (
    memory_distill_commit,
    memory_distill_prepare,
    memory_state_show,
)


def _write_note(
    memory_dir: Path,
    *,
    date: str,
    name: str,
    title: str,
    decisions: list[str],
) -> Path:
    note_dir = memory_dir / date
    note_dir.mkdir(parents=True, exist_ok=True)
    note_path = note_dir / name
    note_path.write_text(
        "\n".join(
            [
                f"# {title}",
                "",
                f"- Date: {date}",
                "- Time: 09:00 - 09:30",
                "",
                "## 判断",
                "",
                *[f"- {item}" for item in decisions],
                "",
            ]
        ),
        encoding="utf-8",
    )
    return note_path


# ---------------------------------------------------------------------------
# memory_distill_prepare
# ---------------------------------------------------------------------------


def test_prepare_knowledge_returns_notes_and_schema(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    _write_note(
        tmp_memory_dir,
        date="2026-04-09",
        name="0900_rust.md",
        title="Rust Note",
        decisions=["Ownership came up repeatedly"],
    )

    payload = json.loads(
        memory_distill_prepare(
            type="knowledge",
            date_from="2026-04-01",
            date_to="2026-04-10",
            memory_dir=str(tmp_memory_dir),
        )
    )

    assert payload["ok"] is True
    assert len(payload["notes"]) == 1
    assert payload["notes"][0]["title"] == "Rust Note"
    assert "candidate_schema" in payload
    assert "instructions" in payload
    assert "decisions" not in payload


def test_prepare_values_returns_decisions(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    _write_note(
        tmp_memory_dir,
        date="2026-04-09",
        name="0900_review.md",
        title="Review Note",
        decisions=["Asked for regression tests"],
    )
    state.cmd_add(
        tmp_memory_dir / "_state.md",
        "decisions",
        ["[2026-04-10 09:00] Asked for regression tests"],
    )

    payload = json.loads(
        memory_distill_prepare(
            type="values",
            memory_dir=str(tmp_memory_dir),
        )
    )

    assert payload["ok"] is True
    assert len(payload["notes"]) >= 1
    assert "decisions" in payload
    assert "regression tests" in payload["decisions"]


# ---------------------------------------------------------------------------
# memory_distill_commit — knowledge
# ---------------------------------------------------------------------------


def test_commit_knowledge_creates_entry(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)

    payload = json.loads(
        memory_distill_commit(
            type="knowledge",
            candidates=[
                {
                    "title": "Rust ownership",
                    "content": "Ownership explains moves and borrows.",
                    "domain": "rust",
                    "tags": ["memory-management"],
                    "accuracy": "uncertain",
                }
            ],
            memory_dir=str(tmp_memory_dir),
        )
    )

    assert payload["ok"] is True
    assert len(payload["created"]) == 1
    assert payload["created"][0]["title"] == "Rust ownership"
    assert "id" in payload["created"][0]

    entries = KnowledgeRepository(tmp_memory_dir).list_all()
    assert len(entries) == 1
    assert entries[0].origin.value == "memory_distillation"

    state_payload = json.loads(memory_state_show(memory_dir=str(tmp_memory_dir)))
    assert state_payload["frontmatter"]["last_knowledge_evaluated_at"] is not None
    assert state_payload["frontmatter"]["last_knowledge_distilled_at"] is not None


def test_commit_knowledge_skips_duplicate(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)

    KnowledgeService().add(
        tmp_memory_dir,
        title="Rust ownership",
        content="Ownership explains moves and borrows.",
        domain="rust",
        origin=SourceType.USER_TAUGHT,
    )

    payload = json.loads(
        memory_distill_commit(
            type="knowledge",
            candidates=[
                {
                    "title": "Rust ownership",
                    "content": "Ownership explains moves and borrows.",
                    "domain": "rust",
                }
            ],
            memory_dir=str(tmp_memory_dir),
        )
    )

    assert payload["ok"] is True
    assert len(payload["created"]) == 0
    assert len(payload["skipped"]) == 1
    assert payload["skipped"][0]["reason"] == "duplicate"


def test_commit_knowledge_dry_run_does_not_persist(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)

    payload = json.loads(
        memory_distill_commit(
            type="knowledge",
            candidates=[
                {
                    "title": "New knowledge",
                    "content": "Some content here.",
                    "domain": "test",
                }
            ],
            dry_run=True,
            memory_dir=str(tmp_memory_dir),
        )
    )

    assert payload["ok"] is True
    assert len(payload["created"]) == 1
    assert payload["created"][0]["dry_run"] is True

    assert KnowledgeRepository(tmp_memory_dir).list_all() == []
    frontmatter = state.load_state_frontmatter(tmp_memory_dir / "_state.md")
    assert frontmatter["last_knowledge_evaluated_at"] is None


def test_commit_knowledge_skips_missing_fields(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)

    payload = json.loads(
        memory_distill_commit(
            type="knowledge",
            candidates=[
                {"title": "No content or domain"},
            ],
            memory_dir=str(tmp_memory_dir),
        )
    )

    assert payload["ok"] is True
    assert len(payload["skipped"]) == 1
    assert "Missing required field" in payload["skipped"][0]["reason"]


def test_commit_knowledge_warns_on_secrets(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)

    payload = json.loads(
        memory_distill_commit(
            type="knowledge",
            candidates=[
                {
                    "title": "Secret knowledge",
                    "content": "Use ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZab to authenticate",
                    "domain": "secrets",
                }
            ],
            memory_dir=str(tmp_memory_dir),
        )
    )

    assert payload["ok"] is True
    assert len(payload.get("warnings", [])) >= 1
    assert any("secrets" in w.lower() for w in payload["warnings"])


# ---------------------------------------------------------------------------
# memory_distill_commit — values
# ---------------------------------------------------------------------------


def test_commit_values_creates_entry(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)

    payload = json.loads(
        memory_distill_commit(
            type="values",
            candidates=[
                {
                    "description": "Require regression tests for bug fixes",
                    "category": "review",
                    "confidence": 0.5,
                    "evidence": [
                        {
                            "ref": "_state.md#decisions",
                            "summary": "Asked for regression tests",
                            "date": "2026-04-10",
                        }
                    ],
                }
            ],
            memory_dir=str(tmp_memory_dir),
        )
    )

    assert payload["ok"] is True
    assert len(payload["created"]) == 1
    assert "id" in payload["created"][0]

    entries = ValuesRepository(tmp_memory_dir).list_all()
    assert len(entries) == 1
    assert entries[0].origin.value == "memory_distillation"
    assert entries[0].confidence == 0.5
    assert len(entries[0].evidence) == 1

    state_payload = json.loads(memory_state_show(memory_dir=str(tmp_memory_dir)))
    assert state_payload["frontmatter"]["last_values_evaluated_at"] is not None
    assert state_payload["frontmatter"]["last_values_distilled_at"] is not None


def test_commit_values_skips_duplicate(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)

    ValuesService().add(
        tmp_memory_dir,
        description="Require regression tests for bug fixes",
        category="review",
    )

    payload = json.loads(
        memory_distill_commit(
            type="values",
            candidates=[
                {
                    "description": "Require regression tests for bug fixes",
                    "category": "review",
                }
            ],
            memory_dir=str(tmp_memory_dir),
        )
    )

    assert payload["ok"] is True
    assert len(payload["created"]) == 0
    assert len(payload["skipped"]) == 1
    assert payload["skipped"][0]["reason"] == "duplicate"


def test_commit_values_dry_run_does_not_persist(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)

    payload = json.loads(
        memory_distill_commit(
            type="values",
            candidates=[
                {
                    "description": "New value pattern",
                    "category": "testing",
                }
            ],
            dry_run=True,
            memory_dir=str(tmp_memory_dir),
        )
    )

    assert payload["ok"] is True
    assert len(payload["created"]) == 1
    assert payload["created"][0]["dry_run"] is True
    assert ValuesRepository(tmp_memory_dir).list_all() == []


def test_commit_values_warns_on_secrets(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)

    payload = json.loads(
        memory_distill_commit(
            type="values",
            candidates=[
                {
                    "description": "Authenticate with ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZab token",
                    "category": "secrets",
                }
            ],
            memory_dir=str(tmp_memory_dir),
        )
    )

    assert payload["ok"] is True
    assert len(payload.get("warnings", [])) >= 1
    assert any("secrets" in w.lower() for w in payload["warnings"])


def test_commit_values_skips_missing_fields(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)

    payload = json.loads(
        memory_distill_commit(
            type="values",
            candidates=[
                {"description": "No category"},
            ],
            memory_dir=str(tmp_memory_dir),
        )
    )

    assert payload["ok"] is True
    assert len(payload["skipped"]) == 1
    assert "Missing required field" in payload["skipped"][0]["reason"]


# ---------------------------------------------------------------------------
# Extended tests: sources, user_understanding, invalid candidates
# ---------------------------------------------------------------------------


def test_commit_knowledge_persists_sources_and_user_understanding(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)

    payload = json.loads(
        memory_distill_commit(
            type="knowledge",
            candidates=[
                {
                    "title": "Rust borrowing",
                    "content": "Borrowing rules prevent data races.",
                    "domain": "rust",
                    "sources": [
                        {
                            "type": "memory_distillation",
                            "ref": "memory/2026-04-09/rust.md",
                            "summary": "Distilled from Rust session",
                        }
                    ],
                    "user_understanding": "proficient",
                }
            ],
            memory_dir=str(tmp_memory_dir),
        )
    )

    assert payload["ok"] is True
    assert len(payload["created"]) == 1

    entries = KnowledgeRepository(tmp_memory_dir).list_all()
    assert len(entries) == 1
    assert len(entries[0].sources) == 1
    assert entries[0].sources[0].ref == "memory/2026-04-09/rust.md"
    assert entries[0].user_understanding.value == "proficient"


def test_commit_knowledge_skips_invalid_accuracy(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)

    payload = json.loads(
        memory_distill_commit(
            type="knowledge",
            candidates=[
                {
                    "title": "Bad accuracy",
                    "content": "Content here.",
                    "domain": "test",
                    "accuracy": "bogus_level",
                }
            ],
            memory_dir=str(tmp_memory_dir),
        )
    )

    assert payload["ok"] is True
    assert len(payload["skipped"]) == 1
    assert "bogus_level" in payload["skipped"][0]["reason"]


def test_commit_knowledge_skips_invalid_user_understanding(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)

    payload = json.loads(
        memory_distill_commit(
            type="knowledge",
            candidates=[
                {
                    "title": "Bad understanding",
                    "content": "Content here.",
                    "domain": "test",
                    "user_understanding": "grandmaster",
                }
            ],
            memory_dir=str(tmp_memory_dir),
        )
    )

    assert payload["ok"] is True
    assert len(payload["skipped"]) == 1
    assert "grandmaster" in payload["skipped"][0]["reason"]


def test_commit_knowledge_dry_run_uses_service_validation(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    """Dry-run should detect duplicates via KnowledgeService.add, not independent logic."""
    monkeypatch.chdir(tmp_memory_dir.parent)

    KnowledgeService().add(
        tmp_memory_dir,
        title="Existing knowledge",
        content="Already known content.",
        domain="test",
        origin=SourceType.USER_TAUGHT,
    )

    payload = json.loads(
        memory_distill_commit(
            type="knowledge",
            candidates=[
                {
                    "title": "Existing knowledge",
                    "content": "Already known content.",
                    "domain": "test",
                }
            ],
            dry_run=True,
            memory_dir=str(tmp_memory_dir),
        )
    )

    assert payload["ok"] is True
    assert len(payload["skipped"]) == 1
    assert payload["skipped"][0]["reason"] == "duplicate"
    assert len(KnowledgeRepository(tmp_memory_dir).list_all()) == 1


def test_commit_values_skips_malformed_evidence(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)

    payload = json.loads(
        memory_distill_commit(
            type="values",
            candidates=[
                {
                    "description": "Some value with bad evidence",
                    "category": "testing",
                    "evidence": [{"missing_ref": True}],
                }
            ],
            memory_dir=str(tmp_memory_dir),
        )
    )

    assert payload["ok"] is True
    assert len(payload["skipped"]) == 1
    assert "Malformed evidence" in payload["skipped"][0]["reason"]
    assert ValuesRepository(tmp_memory_dir).list_all() == []


def test_commit_values_dry_run_uses_service_validation(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    """Dry-run should detect duplicates via ValuesService.add, not independent logic."""
    monkeypatch.chdir(tmp_memory_dir.parent)

    ValuesService().add(
        tmp_memory_dir,
        description="Existing value pattern",
        category="testing",
    )

    payload = json.loads(
        memory_distill_commit(
            type="values",
            candidates=[
                {
                    "description": "Existing value pattern",
                    "category": "testing",
                }
            ],
            dry_run=True,
            memory_dir=str(tmp_memory_dir),
        )
    )

    assert payload["ok"] is True
    assert len(payload["skipped"]) == 1
    assert payload["skipped"][0]["reason"] == "duplicate"
    assert len(ValuesRepository(tmp_memory_dir).list_all()) == 1


def test_commit_knowledge_dry_run_does_not_mutate_related_links(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    """dry_run must not leave bidirectional link side-effects on existing entries."""
    monkeypatch.chdir(tmp_memory_dir.parent)

    # Create an existing entry
    existing = KnowledgeService().add(
        tmp_memory_dir,
        title="Existing topic",
        content="Existing content for linking test.",
        domain="test",
        origin=SourceType.USER_TAUGHT,
    )
    existing_id = str(existing.id)
    assert existing.related == []

    # dry_run with a candidate that references the existing entry
    payload = json.loads(
        memory_distill_commit(
            type="knowledge",
            candidates=[
                {
                    "title": "New related topic",
                    "content": "New content referencing existing.",
                    "domain": "test",
                    "related": [existing_id],
                }
            ],
            dry_run=True,
            memory_dir=str(tmp_memory_dir),
        )
    )

    assert payload["ok"] is True
    assert len(payload["created"]) == 1
    assert payload["created"][0]["dry_run"] is True

    # Verify: only the original entry exists, with no mutation
    entries = KnowledgeRepository(tmp_memory_dir).list_all()
    assert len(entries) == 1
    assert str(entries[0].id) == existing_id
    # The crucial check: related must still be empty (no bidirectional link added)
    assert entries[0].related == []
