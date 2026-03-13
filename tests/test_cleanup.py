from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from agentic_memory.core import cleanup, index


def test_list_stale_notes_uses_date_directories(tmp_memory_dir: Path) -> None:
    old_date = (dt.date.today() - dt.timedelta(days=120)).isoformat()
    fresh_date = (dt.date.today() - dt.timedelta(days=7)).isoformat()

    old_dir = tmp_memory_dir / old_date
    old_dir.mkdir(parents=True, exist_ok=True)
    old_note = old_dir / "0900_old.md"
    old_note.write_text("# Old Session\n", encoding="utf-8")

    fresh_dir = tmp_memory_dir / fresh_date
    fresh_dir.mkdir(parents=True, exist_ok=True)
    fresh_note = fresh_dir / "0900_fresh.md"
    fresh_note.write_text("# Fresh Session\n", encoding="utf-8")

    stale_notes = cleanup.list_stale_notes(tmp_memory_dir, days=90)

    assert stale_notes == [
        {
            "path": f"memory/{old_date}/0900_old.md",
            "date": old_date,
            "title": "Old Session",
            "size_bytes": old_note.stat().st_size,
        }
    ]
    assert fresh_note.exists()


def test_cleanup_notes_dry_run_keeps_note_and_index(
    sample_note_path: Path,
    tmp_memory_dir: Path,
) -> None:
    entry = index.index_note(
        note_path=sample_note_path,
        index_path=tmp_memory_dir / "_index.jsonl",
        dailynote_dir=tmp_memory_dir,
        no_dense=True,
    )

    result = cleanup.cleanup_notes(tmp_memory_dir, [entry["path"]], dry_run=True)

    rows = [
        json.loads(line)
        for line in (tmp_memory_dir / "_index.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert result == {
        "removed": ["memory/2026-01-01/1015_sample-session.md"],
        "count": 1,
        "dry_run": True,
    }
    assert sample_note_path.exists()
    assert len(rows) == 1


def test_cleanup_notes_removes_note_and_index_entry(
    sample_note_path: Path,
    tmp_memory_dir: Path,
) -> None:
    second_dir = tmp_memory_dir / "2026-01-02"
    second_dir.mkdir(parents=True, exist_ok=True)
    second_note = second_dir / "0900_second.md"
    second_note.write_text("# Keep Session\n", encoding="utf-8")
    index.rebuild_index(
        index_path=tmp_memory_dir / "_index.jsonl",
        dailynote_dir=tmp_memory_dir,
        no_dense=True,
    )

    result = cleanup.cleanup_notes(
        tmp_memory_dir,
        ["memory/2026-01-01/1015_sample-session.md"],
        dry_run=False,
    )

    rows = [
        json.loads(line)
        for line in (tmp_memory_dir / "_index.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert result == {
        "removed": ["memory/2026-01-01/1015_sample-session.md"],
        "count": 1,
        "dry_run": False,
    }
    assert not sample_note_path.exists()
    assert second_note.exists()
    assert len(rows) == 1
    assert rows[0]["path"] == "memory/2026-01-02/0900_second.md"
