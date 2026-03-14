from __future__ import annotations

import json
import zipfile
from pathlib import Path

from agentic_memory.core import export, index


def test_export_memory_json_includes_all_core_files(
    sample_note_path: Path,
    tmp_memory_dir: Path,
    tmp_path: Path,
) -> None:
    index.index_note(
        note_path=sample_note_path,
        index_path=tmp_memory_dir / "_index.jsonl",
        dailynote_dir=tmp_memory_dir,
        no_dense=True,
    )
    output_path = tmp_path / "memory-export.json"

    result = export.export_memory(tmp_memory_dir, output_path, fmt="json")
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert result["output_path"] == str(output_path)
    assert result["format"] == "json"
    assert result["notes_count"] == 1
    assert result["total_size_bytes"] == output_path.stat().st_size
    assert payload["notes"][0]["path"] == "memory/2026-01-01/1015_sample-session.md"
    assert "# Sample Session" in payload["notes"][0]["content"]
    assert '"title": "Sample Session"' in payload["index"]["content"]
    assert "# 作業状態（ローリング）" in payload["state"]["content"]
    assert '"weights"' in payload["config"]["content"]


def test_export_memory_zip_preserves_directory_layout(
    sample_note_path: Path,
    tmp_memory_dir: Path,
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "memory-export.zip"

    result = export.export_memory(tmp_memory_dir, output_path, fmt="zip")

    assert result["format"] == "zip"
    assert result["notes_count"] == 1
    assert result["total_size_bytes"] == output_path.stat().st_size

    with zipfile.ZipFile(output_path) as archive:
        names = sorted(archive.namelist())

    assert "memory/_index.jsonl" in names
    assert "memory/_rag_config.json" in names
    assert "memory/_state.md" in names
    assert "memory/2026-01-01/1015_sample-session.md" in names
    assert sample_note_path.exists()


def test_export_memory_rejects_unknown_format(
    sample_note_path: Path,
    tmp_memory_dir: Path,
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "memory-export.dat"

    try:
        export.export_memory(tmp_memory_dir, output_path, fmt="yaml")
    except ValueError as exc:
        assert str(exc) == "fmt must be 'json' or 'zip'"
    else:
        raise AssertionError("ValueError was not raised")

    assert sample_note_path.exists()


def test_zip_export_excludes_lock_files(tmp_path: Path) -> None:
    """ZIP export should not include .lock files."""
    mem = tmp_path / "mem"
    mem.mkdir()
    (mem / "_state.md").write_text("# state")
    (mem / "_index.jsonl").write_text("")
    (mem / "_index.jsonl.lock").write_text("")
    (mem / "_state.md.lock").write_text("")
    out = tmp_path / "out.zip"

    export.export_memory(mem, out, fmt="zip")

    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()

    assert not any(n.endswith(".lock") for n in names), (
        f"Lock files found: {[n for n in names if n.endswith('.lock')]}"
    )
