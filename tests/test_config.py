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

    loaded = json.loads((memory_dir / "_rag_config.json").read_text(encoding="utf-8"))
    assert "weights" in loaded


def test_init_memory_dir_already_exists(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "_state.md").write_text("existing-state", encoding="utf-8")

    result = config.init_memory_dir(memory_dir)

    assert result["status"] == "already_exists"
    assert result["state_content"] == "existing-state"


def test_load_template() -> None:
    template = config.load_template()
    assert "# 作業状態（ローリング）" in template
    assert "## 現在のフォーカス" in template
    assert "## 改善バックログ" in template
