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


def test_init_memory_dir_recognizes_annotated_promoted_values_markers(tmp_path: Path) -> None:
    """Annotated marker lines must be recognized as the existing block.

    Regression: ``_ensure_promoted_values_markers`` previously used a substring
    check against the bare ``<!-- BEGIN:PROMOTED_VALUES -->`` constant, which
    failed to match a hand-annotated form such as
    ``<!-- BEGIN:PROMOTED_VALUES (agentic-memory managed — do not edit manually) -->``.
    The detector then appended a fresh bare-marker block at the end of the
    file, leaving the AGENTS.md with two PROMOTED_VALUES blocks (one annotated,
    one bare). The annotated block must be treated as the existing block so
    that ``init_memory_dir`` is idempotent regardless of marker decoration.
    """

    memory_dir = tmp_path / "memory"
    agents_path = tmp_path / "AGENTS.md"
    annotated_begin = (
        "<!-- BEGIN:PROMOTED_VALUES (agentic-memory managed — do not edit manually) -->"
    )
    annotated_end = "<!-- END:PROMOTED_VALUES (agentic-memory managed) -->"
    original = (
        "# Agent Rules\n\n"
        "## 内面化された価値観\n\n"
        f"{annotated_begin}\n\n{annotated_end}\n\n"
        "## 継続的改善\n"
    )
    agents_path.write_text(original, encoding="utf-8")

    config.init_memory_dir(memory_dir)
    config.init_memory_dir(memory_dir)

    content = agents_path.read_text(encoding="utf-8")
    # Both annotated marker lines must be preserved unchanged.
    assert annotated_begin in content
    assert annotated_end in content
    # No bare-form duplicate should be appended.
    assert content.count("BEGIN:PROMOTED_VALUES") == 1
    assert content.count("END:PROMOTED_VALUES") == 1


def test_init_memory_dir_ignores_similarly_named_markers(tmp_path: Path) -> None:
    """Marker detection must use word-boundary anchors to reject typos.

    The PROMOTED_VALUES detection regex uses ``\\b`` (word boundary) so that
    derivative names such as ``PROMOTED_VALUES_FOO`` or ``PROMOTED_VALUESXYZ``
    are *not* mistaken for the canonical PROMOTED_VALUES markers. Without the
    word boundary, a future refactor that simplifies the regex (for example,
    relaxing ``\\b.*-->$`` to ``\\s*.*-->$``) would silently start matching
    these typos. This negative test locks in the false-positive protection.
    """

    memory_dir = tmp_path / "memory"
    agents_path = tmp_path / "AGENTS.md"
    agents_path.write_text(
        "# Agent Rules\n\n<!-- BEGIN:PROMOTED_VALUES_FOO -->\n<!-- END:PROMOTED_VALUES_FOO -->\n",
        encoding="utf-8",
    )

    config.init_memory_dir(memory_dir)

    content = agents_path.read_text(encoding="utf-8")
    # The unrelated _FOO markers must remain untouched.
    assert "BEGIN:PROMOTED_VALUES_FOO" in content
    assert "END:PROMOTED_VALUES_FOO" in content
    # And the canonical bare markers must be appended exactly once because
    # the _FOO markers are not recognized as the canonical block.
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
