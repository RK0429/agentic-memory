from __future__ import annotations

from pathlib import Path

from agentic_memory.core import index
from agentic_memory.core import query
from agentic_memory.core import search


def test_search_no_index(tmp_memory_dir: Path, sample_note_path: Path, sample_index_path: Path) -> None:
    sample_index_path.unlink()

    result = search.search(
        query="refresh",
        memory_dir=tmp_memory_dir,
        engine="auto",
    )

    assert sample_note_path.exists()
    assert result["engine"] in {"rg", "python"}
    assert result["results"]


def test_search_with_index(tmp_memory_dir: Path, sample_note_path: Path, sample_index_path: Path) -> None:
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
