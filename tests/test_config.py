from __future__ import annotations

import json
from pathlib import Path

from agentic_memory.core import config


def test_resolve_memory_dir_default(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert config.resolve_memory_dir() == Path("memory")


def test_resolve_memory_dir_memory_exists(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "memory").mkdir()
    monkeypatch.chdir(tmp_path)
    assert config.resolve_memory_dir() == Path("memory")


def test_resolve_memory_dir_daily_note_fallback(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "daily_note").mkdir()
    monkeypatch.chdir(tmp_path)
    assert config.resolve_memory_dir() == Path("daily_note")


def test_resolve_memory_dir_both_exist(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "memory").mkdir()
    (tmp_path / "daily_note").mkdir()
    monkeypatch.chdir(tmp_path)
    assert config.resolve_memory_dir() == Path("memory")


def test_init_memory_dir_creates(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    result = config.init_memory_dir(memory_dir)

    assert result["status"] == "created"
    assert (memory_dir / "_state.md").exists()
    assert (memory_dir / "_index.jsonl").exists()
    assert (memory_dir / "_rag_config.json").exists()
    assert (memory_dir / "knowledge").is_dir()
    assert (memory_dir / "values").is_dir()
    assert "# 作業状態（ローリング）" in (memory_dir / "_state.md").read_text(encoding="utf-8")

    loaded = json.loads((memory_dir / "_rag_config.json").read_text(encoding="utf-8"))
    assert "weights" in loaded


def test_init_memory_dir_adds_promoted_values_markers_to_existing_agents_md(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    agents_path = tmp_path / "AGENTS.md"
    agents_path.write_text("# Agent Rules\n", encoding="utf-8")

    config.init_memory_dir(memory_dir)
    config.init_memory_dir(memory_dir)

    content = agents_path.read_text(encoding="utf-8")
    assert content.count(config.PROMOTED_VALUES_BEGIN) == 1
    assert content.count(config.PROMOTED_VALUES_END) == 1


def test_init_dense_config(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"

    config.init_memory_dir(memory_dir, enable_dense=True)

    loaded = json.loads((memory_dir / "_rag_config.json").read_text(encoding="utf-8"))
    assert loaded["dense"] == {
        "enabled": True,
        "model": "cl-nagoya/ruri-v3-70m",
        "dim": 384,
    }


def test_init_memory_dir_partially_existing(tmp_path: Path) -> None:
    """Directory exists with some files → status should be 'initialized'."""
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "_state.md").write_text("existing-state", encoding="utf-8")

    result = config.init_memory_dir(memory_dir)

    assert result["status"] == "initialized"
    assert result["state_content"] == "existing-state"


def test_init_memory_dir_already_exists(tmp_path: Path) -> None:
    """All files already exist → status should be 'already_exists'."""
    memory_dir = tmp_path / "memory"
    config.init_memory_dir(memory_dir)  # creates everything

    result = config.init_memory_dir(memory_dir)

    assert result["status"] == "already_exists"
    assert "state_content" not in result


def test_init_memory_dir_created_includes_state_content(tmp_path: Path) -> None:
    """Newly created directory includes state_content in result."""
    memory_dir = tmp_path / "new_memory"
    result = config.init_memory_dir(memory_dir)

    assert result["status"] == "created"
    assert "state_content" in result
    assert len(result["state_content"]) > 0


def test_load_template() -> None:
    template = config.load_template()
    assert "# <short title>" in template
    assert "## 目標" in template
    assert "## スキル候補" in template


def test_english_template() -> None:
    template = config.load_template(lang="en")

    assert "## Goals" in template
    assert "## Work Log" in template
    assert "## Skill Feedback" in template
    assert "## 目標" not in template


def test_update_weights(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    config.init_memory_dir(memory_dir)

    updated = config.update_weights(memory_dir, {"title": 9.5, "missing": 1.0})

    loaded = json.loads((memory_dir / "_rag_config.json").read_text(encoding="utf-8"))
    assert updated["weights"]["title"] == 9.5
    assert loaded["weights"]["title"] == 9.5
    assert "missing" not in loaded["weights"]
    assert len(updated["warnings"]) == 1
    assert "missing" in updated["warnings"][0]
