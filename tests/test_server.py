from __future__ import annotations

import json
from pathlib import Path

from agentic_memory.server import (
    _resolve_dir,
    memory_evidence,
    memory_index_build,
    memory_index_upsert,
    memory_init,
    memory_note_new,
    memory_search,
    memory_state_add,
    memory_state_from_note,
    memory_state_prune,
    memory_state_remove,
    memory_state_set,
    memory_state_show,
)


def _write_note(memory_dir: Path, name: str = "source.md") -> Path:
    note_path = memory_dir / name
    note_path.write_text(
        (
            "# Server Source\n\n"
            "- Date: 2026-03-02\n"
            "- Time: 10:00 - 11:00\n"
            "- Context: test\n\n"
            "## 目標\n- validate server tools\n\n"
            "## 判断\n- call functions directly\n\n"
            "## 次のアクション\n- write assertions\n\n"
            "## 注意点・残課題\n- ensure stable output\n\n"
            "## スキル候補\n- pytest\n"
        ),
        encoding="utf-8",
    )
    return note_path


def test_resolve_dir_explicit(tmp_path: Path, monkeypatch) -> None:
    explicit = tmp_path / "explicit-memory"
    env_path = tmp_path / "env-memory"
    monkeypatch.setenv("MEMORY_DIR", str(env_path))

    resolved = _resolve_dir(str(explicit))
    assert resolved == explicit


def test_resolve_dir_env(tmp_path: Path, monkeypatch) -> None:
    memory_dir = tmp_path / "env-memory"
    monkeypatch.setenv("MEMORY_DIR", str(memory_dir))

    resolved = _resolve_dir()
    assert resolved == memory_dir


def test_memory_init(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    memory_dir = tmp_path / "memory"

    payload = json.loads(memory_init(str(memory_dir)))
    assert payload["status"] == "created"
    assert (memory_dir / "_state.md").exists()


def test_memory_note_new(tmp_memory_dir: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    memory_dir = tmp_memory_dir

    created_path = Path(memory_note_new(title="Server Note", memory_dir=str(memory_dir)))
    assert created_path.exists()
    assert created_path.suffix == ".md"


def test_memory_state_show(tmp_memory_dir: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    memory_dir = tmp_memory_dir

    output = memory_state_show(memory_dir=str(memory_dir))
    assert "現在のフォーカス" in output
    assert "- (empty)" in output


def test_memory_state_add(tmp_memory_dir: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    memory_dir = tmp_memory_dir

    result = memory_state_add(section="focus", items=["Task A", "Task B"], memory_dir=str(memory_dir))
    assert result.endswith("_state.md")

    output = memory_state_show(section="focus", memory_dir=str(memory_dir))
    assert "Task A" in output
    assert "Task B" in output


def test_memory_state_set(tmp_memory_dir: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    memory_dir = tmp_memory_dir

    memory_state_add(section="focus", items=["Old"], memory_dir=str(memory_dir))
    result = memory_state_set(section="focus", items=["New"], memory_dir=str(memory_dir))
    assert result.endswith("_state.md")

    output = memory_state_show(section="focus", memory_dir=str(memory_dir))
    assert "New" in output
    assert "Old" not in output


def test_memory_state_remove(tmp_memory_dir: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    memory_dir = tmp_memory_dir

    memory_state_add(section="focus", items=["Keep", "Drop"], memory_dir=str(memory_dir))
    removed = memory_state_remove(section="focus", pattern="Drop", memory_dir=str(memory_dir))
    assert removed.splitlines()[0].strip() == "1"

    output = memory_state_show(section="focus", memory_dir=str(memory_dir))
    assert "Keep" in output
    assert "Drop" not in output


def test_memory_state_prune(tmp_memory_dir: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    memory_dir = tmp_memory_dir

    memory_state_add(
        section="focus",
        items=["[2000-01-01 00:00] stale entry", "fresh entry"],
        memory_dir=str(memory_dir),
    )
    pruned = memory_state_prune(stale_days=7, section="focus", memory_dir=str(memory_dir))
    assert pruned.splitlines()[0].strip() == "1"

    output = memory_state_show(section="focus", memory_dir=str(memory_dir))
    assert "fresh entry" in output
    assert "stale entry" not in output


def test_memory_state_from_note(tmp_memory_dir: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    memory_dir = tmp_memory_dir

    note_path = _write_note(memory_dir, name="from_note.md")
    result = memory_state_from_note(
        note_path=str(note_path),
        no_auto_improve=True,
        memory_dir=str(memory_dir),
    )
    assert result.endswith("_state.md")

    output = memory_state_show(section="open", memory_dir=str(memory_dir))
    assert "write assertions" in output


def test_memory_search(tmp_memory_dir: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    memory_dir = tmp_memory_dir

    raw = memory_search(query="__no_result_expected__", engine="python", memory_dir=str(memory_dir))
    payload = json.loads(raw)
    assert payload["query"] == "__no_result_expected__"
    assert isinstance(payload["results"], list)


def test_memory_index_build(tmp_memory_dir: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    memory_dir = tmp_memory_dir

    created_path = Path(memory_note_new(title="Index Build", memory_dir=str(memory_dir)))
    assert created_path.exists()

    raw = memory_index_build(no_dense=True, memory_dir=str(memory_dir))
    payload = json.loads(raw)
    assert isinstance(payload, list)
    assert len(payload) >= 1
    assert (memory_dir / "_index.jsonl").exists()


def test_memory_index_upsert(tmp_memory_dir: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    memory_dir = tmp_memory_dir

    created_path = Path(memory_note_new(title="Upsert One", memory_dir=str(memory_dir)))
    raw = memory_index_upsert(note_path=str(created_path), no_dense=True, memory_dir=str(memory_dir))

    payload = json.loads(raw)
    assert isinstance(payload, dict)
    assert payload["path"].endswith(".md")


def test_memory_evidence(tmp_memory_dir: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    memory_dir = tmp_memory_dir

    note_path = _write_note(memory_dir, name="evidence.md")
    output = memory_evidence(query="validate", paths=[str(note_path)], memory_dir=str(memory_dir))
    assert "# DailyNote Evidence Pack" in output
    assert str(note_path) in output
