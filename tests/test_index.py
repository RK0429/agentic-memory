from __future__ import annotations

import json
from pathlib import Path

from agentic_memory.core import index


def test_build_entry(sample_note_path: Path, tmp_memory_dir: Path) -> None:
    entry = index.build_entry(sample_note_path, max_summary_chars=280, dailynote_dir=tmp_memory_dir)

    assert entry["title"] == "Sample Session"
    assert entry["date"] == "2026-01-01"
    assert entry["tags"] == ["backend", "auth"]
    assert entry["keywords"] == ["token", "refresh"]
    assert entry["files"] == ["src/auth.py", "tests/test_auth.py"]
    assert "uv run pytest tests/test_auth.py" in entry["commands"]
    assert any(err == "AuthError" for err in entry["errors"])
    assert entry["path"].startswith("memory/2026-01-01/")


def test_upsert_new(sample_index_path: Path) -> None:
    entry = {"path": "memory/2026-01-01/a.md", "title": "A"}
    index.upsert(sample_index_path, entry)

    rows = [
        json.loads(line)
        for line in sample_index_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(rows) == 1
    assert rows[0]["title"] == "A"


def test_upsert_replace(sample_index_path: Path) -> None:
    first = {"path": "memory/2026-01-01/a.md", "title": "A"}
    second = {"path": "memory/2026-01-01/a.md", "title": "B"}
    index.upsert(sample_index_path, first)
    index.upsert(sample_index_path, second)

    rows = [
        json.loads(line)
        for line in sample_index_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(rows) == 1
    assert rows[0]["title"] == "B"


def test_rebuild_index(
    sample_note_path: Path, sample_index_path: Path, tmp_memory_dir: Path
) -> None:
    second_dir = tmp_memory_dir / "2026-01-02"
    second_dir.mkdir(parents=True, exist_ok=True)
    second_note = second_dir / "0900_second.md"
    second_note.write_text(
        (
            "# Another Session\n\n"
            "- Date: 2026-01-02\n"
            "- Time: 09:00 - 09:30\n"
            "- Context: N/A\n"
            "- Tags: backend\n"
            "- Keywords: cache\n\n"
            "## 目標\n\n- Improve cache hit rate\n\n"
        ),
        encoding="utf-8",
    )

    entries = index.rebuild_index(
        index_path=sample_index_path,
        dailynote_dir=tmp_memory_dir,
        no_dense=True,
    )

    assert len(entries) == 2
    rows = [
        line for line in sample_index_path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    assert len(rows) == 2
    assert sample_note_path.exists()
    assert second_note.exists()


def test_index_note(sample_note_path: Path, sample_index_path: Path, tmp_memory_dir: Path) -> None:
    entry = index.index_note(
        note_path=sample_note_path,
        index_path=sample_index_path,
        dailynote_dir=tmp_memory_dir,
        no_dense=True,
    )

    rows = [
        json.loads(line)
        for line in sample_index_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert rows[0]["path"] == entry["path"]


def test_list_notes(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    note_dir = memory_dir / "2026-01-01"
    note_dir.mkdir(parents=True, exist_ok=True)

    keep = note_dir / "ok.md"
    ignored_nested = note_dir / "_ignored.md"
    ignored_root = memory_dir / "_state.md"
    non_md = note_dir / "note.txt"

    keep.write_text("# ok\n", encoding="utf-8")
    ignored_nested.write_text("# ignored\n", encoding="utf-8")
    ignored_root.write_text("# state\n", encoding="utf-8")
    non_md.write_text("x", encoding="utf-8")

    notes = index.list_notes(memory_dir)
    assert notes == [keep]


def test_extract_files() -> None:
    changes_lines = [
        "- Files:",
        "  - src/auth.py",
        "  - tests/test_auth.py",
        "- Notes:",
        "  - updated parser",
    ]
    files = index.extract_files(changes_lines)
    assert files == ["src/auth.py", "tests/test_auth.py"]


def test_extract_commands() -> None:
    cmd_lines = [
        "- uv run pytest tests/test_auth.py",
        "```bash",
        "uv run ruff check .",
        "```",
    ]
    commands = index.extract_commands(cmd_lines)
    assert "uv run pytest tests/test_auth.py" in commands
    assert "uv run ruff check ." in commands


def test_extract_errors() -> None:
    md = "Traceback: ECONNRESET and HTTP 500 caused ValueError."
    errors = index.extract_errors(md)
    assert "Traceback" in errors
    assert "ECONNRESET" in errors
    assert "HTTP 500" in errors
    assert "ValueError" in errors


def test_build_entry_with_identifier_fields(tmp_memory_dir: Path) -> None:
    note_dir = tmp_memory_dir / "2026-01-10"
    note_dir.mkdir(parents=True, exist_ok=True)
    note_path = note_dir / "1000_identifiers.md"
    note_path.write_text(
        (
            "# Identifier Note\n\n"
            "- Date: 2026-01-10\n"
            "- Task-ID: TASK-999\n"
            "- Agent-ID: coder\n"
            "- Relay-Session-ID: relay-abc\n\n"
            "## 目標\n- verify metadata\n"
        ),
        encoding="utf-8",
    )

    entry = index.build_entry(note_path, max_summary_chars=280, dailynote_dir=tmp_memory_dir)
    assert entry["task_id"] == "TASK-999"
    assert entry["agent_id"] == "coder"
    assert entry["relay_session_id"] == "relay-abc"


def test_index_note_overrides_identifier_fields(tmp_memory_dir: Path) -> None:
    note_dir = tmp_memory_dir / "2026-01-11"
    note_dir.mkdir(parents=True, exist_ok=True)
    note_path = note_dir / "1100_override.md"
    note_path.write_text(
        ("# Override Note\n\n- Date: 2026-01-11\n\n## 目標\n- verify overrides\n"),
        encoding="utf-8",
    )

    entry = index.index_note(
        note_path=note_path,
        index_path=tmp_memory_dir / "_index.jsonl",
        dailynote_dir=tmp_memory_dir,
        task_id="TASK-123",
        agent_id="researcher",
        relay_session_id="relay-xyz",
        no_dense=True,
    )
    assert entry["task_id"] == "TASK-123"
    assert entry["agent_id"] == "researcher"
    assert entry["relay_session_id"] == "relay-xyz"
