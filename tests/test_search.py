from __future__ import annotations

import json
from pathlib import Path

from agentic_memory.core import index, note, query, search


def test_search_no_index(
    tmp_memory_dir: Path, sample_note_path: Path, sample_index_path: Path
) -> None:
    sample_index_path.unlink()

    result = search.search(
        query="refresh",
        memory_dir=tmp_memory_dir,
        engine="auto",
    )

    assert sample_note_path.exists()
    assert result["engine"] in {"rg", "python"}
    assert result["results"]


def test_search_with_index(
    tmp_memory_dir: Path, sample_note_path: Path, sample_index_path: Path
) -> None:
    index.rebuild_index(
        index_path=sample_index_path,
        dailynote_dir=tmp_memory_dir,
        no_dense=True,
    )

    result = search.search(
        query="refresh",
        memory_dir=tmp_memory_dir,
        engine="auto",
    )

    assert sample_note_path.exists()
    assert result["engine"] == "index"
    assert result["results"]


def test_search_returns_dict(tmp_memory_dir: Path, sample_note_path: Path) -> None:
    result = search.search(
        query="auth",
        memory_dir=tmp_memory_dir,
        engine="auto",
    )

    assert sample_note_path.exists()
    assert isinstance(result, dict)
    assert {"engine", "query", "results", "warnings", "expanded_terms"} <= set(result.keys())


def test_extract_snippets(sample_note_path: Path) -> None:
    qterms = query.parse_query("refresh")
    snippets = search.extract_snippets(sample_note_path, qterms, top_snippets=2)

    assert snippets
    assert snippets[0].startswith("L")
    assert any("refresh" in snippet.lower() for snippet in snippets)


def test_search_filters_by_metadata(tmp_memory_dir: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    note_a = note.create_note(tmp_memory_dir, title="Alpha")
    note_b = note.create_note(tmp_memory_dir, title="Beta")

    index.index_note(
        note_path=note_a,
        index_path=tmp_memory_dir / "_index.jsonl",
        dailynote_dir=tmp_memory_dir,
        task_id="TASK-010",
        agent_id="coder",
        relay_session_id="relay-x",
        no_dense=True,
    )
    index.index_note(
        note_path=note_b,
        index_path=tmp_memory_dir / "_index.jsonl",
        dailynote_dir=tmp_memory_dir,
        task_id="TASK-011",
        agent_id="researcher",
        relay_session_id="relay-y",
        no_dense=True,
    )

    result = search.search(
        query="Alpha",
        memory_dir=tmp_memory_dir,
        engine="index",
        task_id="TASK-010",
        agent_id="coder",
        relay_session_id="relay-x",
    )
    assert result["results"]
    assert len(result["results"]) == 1


def test_search_backward_compatible_without_new_fields(tmp_memory_dir: Path) -> None:
    index_path = tmp_memory_dir / "_index.jsonl"
    legacy_entry = {
        "path": "memory/2026-01-01/legacy.md",
        "title": "legacy",
        "date": "2026-01-01",
    }
    index_path.write_text(json.dumps(legacy_entry, ensure_ascii=False) + "\n", encoding="utf-8")

    result = search.search(
        query="legacy",
        memory_dir=tmp_memory_dir,
        engine="index",
    )
    assert result["results"]

    filtered = search.search(
        query="legacy",
        memory_dir=tmp_memory_dir,
        engine="index",
        task_id="TASK-999",
    )
    assert filtered["results"] == []
