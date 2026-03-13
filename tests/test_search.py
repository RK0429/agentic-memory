from __future__ import annotations

import json
from pathlib import Path

from agentic_memory.core import config, index, note, query, search


def _write_note(memory_dir: Path, date: str, filename: str, title: str, body: str) -> Path:
    note_dir = memory_dir / date
    note_dir.mkdir(parents=True, exist_ok=True)
    note_path = note_dir / filename
    note_path.write_text(
        "\n".join(
            [
                f"# {title}",
                "",
                f"- Date: {date}",
                "- Time: 10:00 - 10:30",
                "- Context: N/A",
                "- Tags: search",
                "- Keywords: refresh",
                "",
                "## 作業ログ",
                f"- {body}",
                "",
                "## 変更点",
                "- Files:",
                "  - src/search.py",
                "",
                "## 成果",
                f"- {body}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return note_path


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


def test_human_readable_explain(
    tmp_memory_dir: Path, sample_note_path: Path, sample_index_path: Path
) -> None:
    index.rebuild_index(
        index_path=sample_index_path,
        dailynote_dir=tmp_memory_dir,
        no_dense=True,
    )

    result = search.search(
        query="tags:backend files:src/auth.py",
        memory_dir=tmp_memory_dir,
        engine="index",
        explain=True,
        no_expand=True,
        no_feedback_expand=True,
        no_fuzzy=True,
    )

    assert sample_note_path.exists()
    assert result["results"]

    _, entry, explain_data = result["results"][0]

    assert entry.explain_summary is not None
    assert entry.explain_summary == search.human_readable_explain(explain_data)
    assert "tags一致" in entry.explain_summary
    assert "files一致" in entry.explain_summary
    assert "合計:" in entry.explain_summary


def test_search_global(tmp_path: Path) -> None:
    memory_dir_a = tmp_path / "project-a" / "memory"
    memory_dir_b = tmp_path / "project-b" / "memory"
    config.init_memory_dir(memory_dir_a)
    config.init_memory_dir(memory_dir_b)

    note_a = _write_note(
        memory_dir_a,
        "2026-01-01",
        "1000_alpha.md",
        "Alpha Session",
        "refresh cache investigation",
    )
    note_b = _write_note(
        memory_dir_b,
        "2026-01-02",
        "1100_beta.md",
        "Beta Session",
        "refresh token investigation",
    )

    index.rebuild_index(
        index_path=memory_dir_a / "_index.jsonl",
        dailynote_dir=memory_dir_a,
        no_dense=True,
    )
    index.rebuild_index(
        index_path=memory_dir_b / "_index.jsonl",
        dailynote_dir=memory_dir_b,
        no_dense=True,
    )

    result = search.search_global(
        query="refresh",
        memory_dirs=[memory_dir_a, memory_dir_b],
        engine="index",
        top=10,
    )

    assert result["engine"] == "global"
    assert len(result["results"]) == 2

    result_paths = {Path(entry.path).name for _, entry, _ in result["results"]}
    source_dirs = {entry.source_dir for _, entry, _ in result["results"]}

    assert result_paths == {note_a.name, note_b.name}
    assert source_dirs == {str(memory_dir_a), str(memory_dir_b)}
