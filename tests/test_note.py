from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from agentic_memory.core import index as memory_index
from agentic_memory.core import note


def test_slugify_basic() -> None:
    assert note.slugify("Fix Auth Bug") == "fix-auth-bug"


def test_slugify_special_chars() -> None:
    assert note.slugify("Fix @Auth! Bug #42") == "fix-auth-bug-42"


def test_slugify_empty() -> None:
    assert note.slugify("!!!") == "session"


def test_create_note_basic(tmp_memory_dir: Path, monkeypatch) -> None:
    monkeypatch.setattr(note, "now_local", lambda: dt.datetime(2026, 1, 2, 3, 4))

    created = note.create_note(tmp_memory_dir, title="Fix Auth Bug", auto_index=False)

    expected = tmp_memory_dir / "2026-01-02" / "0304_fix-auth-bug.md"
    assert created == expected
    assert created.exists()


def test_create_note_metadata(tmp_memory_dir: Path, monkeypatch) -> None:
    monkeypatch.setattr(note, "now_local", lambda: dt.datetime(2026, 1, 3, 8, 9))

    created = note.create_note(
        tmp_memory_dir,
        title="Auth Followup",
        context="https://example.com/pr/1",
        tags="auth,backend",
        keywords="token,refresh",
        auto_index=False,
    )
    text = created.read_text(encoding="utf-8")

    assert "# Auth Followup" in text
    assert "- Date: 2026-01-03" in text
    assert "- Time: 08:09 - 08:09" in text
    assert "- Context: https://example.com/pr/1" in text
    assert "- Tags: auth,backend" in text
    assert "- Keywords: token,refresh" in text


def test_create_note_duplicate_suffix(tmp_memory_dir: Path, monkeypatch) -> None:
    monkeypatch.setattr(note, "now_local", lambda: dt.datetime(2026, 1, 2, 3, 4))

    first = note.create_note(tmp_memory_dir, title="Fix Auth Bug", auto_index=False)
    second = note.create_note(tmp_memory_dir, title="Fix Auth Bug", auto_index=False)

    assert first.name == "0304_fix-auth-bug.md"
    assert second.name == "0304_fix-auth-bug_2.md"
    assert first.exists()
    assert second.exists()


def test_create_note_auto_index(tmp_memory_dir: Path, monkeypatch) -> None:
    monkeypatch.setattr(note, "now_local", lambda: dt.datetime(2026, 1, 4, 9, 10))
    monkeypatch.setattr(memory_index, "upsert_dense", lambda *_args, **_kwargs: True)

    created = note.create_note(tmp_memory_dir, title="Index Me")

    rows = [
        json.loads(line)
        for line in (tmp_memory_dir / "_index.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert created.exists()
    assert len(rows) == 1
    assert rows[0]["title"] == "Index Me"


def test_english_template(tmp_memory_dir: Path, monkeypatch) -> None:
    monkeypatch.setattr(note, "now_local", lambda: dt.datetime(2026, 1, 5, 10, 11))

    created = note.create_note(tmp_memory_dir, title="English Note", lang="en", auto_index=False)
    text = created.read_text(encoding="utf-8")

    assert "## Goals" in text
    assert "## Next Actions" in text
    assert "## Skill Feedback" in text
    assert "## 目標" not in text
