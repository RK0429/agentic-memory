from __future__ import annotations

import json
from pathlib import Path

import agentic_memory.server as server_module
from agentic_memory.core import state
from agentic_memory.core.distillation import KnowledgeCandidate, MockExtractorPort, ValuesCandidate
from agentic_memory.core.knowledge import KnowledgeRepository
from agentic_memory.core.values import ValuesRepository
from agentic_memory.server import (
    memory_distill_knowledge,
    memory_distill_values,
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


def test_memory_distill_knowledge_persists_entries_and_exposes_frontmatter(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    note_path = _write_note(
        tmp_memory_dir,
        date="2026-04-09",
        name="0900_rust.md",
        title="Rust Note",
        decisions=["Ownership came up repeatedly"],
    )
    monkeypatch.setattr(
        server_module,
        "_distillation_extractor",
        MockExtractorPort(
            knowledge_candidates=[
                KnowledgeCandidate(
                    title="Rust ownership",
                    content="Ownership explains moves and borrows.",
                    domain="rust",
                    source_ref=str(note_path.relative_to(tmp_memory_dir.parent)),
                    source_summary="Rust Note (2026-04-09)",
                )
            ]
        ),
    )

    payload = json.loads(
        memory_distill_knowledge(
            dry_run=False,
            memory_dir=str(tmp_memory_dir),
        )
    )

    assert payload["ok"] is True
    assert payload["new_count"] == 1
    assert len(KnowledgeRepository(tmp_memory_dir).list_all()) == 1
    state_payload = json.loads(memory_state_show(memory_dir=str(tmp_memory_dir)))
    assert state_payload["frontmatter"]["last_knowledge_evaluated_at"] is not None
    assert state_payload["frontmatter"]["last_knowledge_distilled_at"] is not None


def test_memory_distill_values_dry_run_does_not_persist(tmp_memory_dir: Path, monkeypatch) -> None:
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
    monkeypatch.setattr(
        server_module,
        "_distillation_extractor",
        MockExtractorPort(
            values_candidates=[
                ValuesCandidate(
                    description="Require regression tests for bug fixes",
                    category="review",
                    source_ref="_state.md#decisions",
                    source_summary="[2026-04-10 09:00] Asked for regression tests",
                )
            ]
        ),
    )

    payload = json.loads(
        memory_distill_values(
            dry_run=True,
            memory_dir=str(tmp_memory_dir),
        )
    )

    assert payload["ok"] is True
    assert payload["new_count"] == 1
    assert not (tmp_memory_dir / "_values.jsonl").exists()
    assert ValuesRepository(tmp_memory_dir).list_all() == []
