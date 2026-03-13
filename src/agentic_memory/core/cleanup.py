"""Note lifecycle helpers for agentic-memory."""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import suppress
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from agentic_memory.core import index
from agentic_memory.core.stats import _iter_note_paths, _normalize_note_path


def _today() -> date:
    return date.today()


def _resolve_note_path(path_text: str, memory_dir: Path) -> Path:
    candidate = Path(path_text)
    if candidate.is_absolute():
        return candidate.resolve()

    parent_dir = memory_dir.resolve().parent
    if candidate.parts and candidate.parts[0] == memory_dir.name:
        primary = parent_dir / candidate
        secondary = memory_dir / candidate
    else:
        primary = memory_dir / candidate
        secondary = parent_dir / candidate

    for option in (primary, secondary):
        resolved = option.resolve()
        if resolved.exists():
            return resolved
    return primary.resolve()


def _is_within_memory_dir(path: Path, memory_dir: Path) -> bool:
    try:
        path.resolve().relative_to(memory_dir.resolve())
        return True
    except ValueError:
        return False


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(tmp_path, path)
    except BaseException:
        with suppress(OSError):
            os.unlink(tmp_path)
        raise


def _load_index_records(index_path: Path) -> list[tuple[str, dict[str, Any] | None]]:
    if not index_path.exists():
        return []

    records: list[tuple[str, dict[str, Any] | None]] = []
    for raw_line in index_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            loaded = json.loads(line)
        except json.JSONDecodeError:
            records.append((raw_line, None))
            continue
        records.append((raw_line, loaded if isinstance(loaded, dict) else None))
    return records


def _write_index_records(
    index_path: Path,
    records: list[tuple[str, dict[str, Any] | None]],
) -> None:
    content = "\n".join(raw_line for raw_line, _ in records)
    if content:
        content += "\n"
    _atomic_write_text(index_path, content)


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    deduped: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        deduped.append(resolved)
    return deduped


def list_stale_notes(memory_dir: Path, days: int = 90) -> list[dict[str, Any]]:
    """List notes whose date directory is older than the given threshold."""
    if days < 0:
        raise ValueError("days must be >= 0")

    cutoff = _today() - timedelta(days=days)
    stale_notes: list[dict[str, Any]] = []
    for note_path in _iter_note_paths(memory_dir):
        try:
            note_date = date.fromisoformat(note_path.parent.name)
        except ValueError:
            continue
        if note_date > cutoff:
            continue

        stale_notes.append(
            {
                "path": _normalize_note_path(note_path, memory_dir),
                "date": note_path.parent.name,
                "title": index.first_h1(note_path.read_text(encoding="utf-8", errors="ignore")),
                "size_bytes": note_path.stat().st_size,
            }
        )

    stale_notes.sort(key=lambda item: (str(item["date"]), str(item["path"])))
    return stale_notes


def cleanup_notes(memory_dir: Path, paths: list[str], dry_run: bool = True) -> dict[str, Any]:
    """Delete selected note files and remove them from the JSONL index."""
    if not paths:
        return {"removed": [], "count": 0, "dry_run": dry_run}

    index_path = memory_dir / "_index.jsonl"
    index_records = _load_index_records(index_path)
    indexed_targets: set[Path] = set()
    for _, row in index_records:
        if not isinstance(row, dict):
            continue
        path_text = str(row.get("path", "")).strip()
        if not path_text:
            continue
        resolved = _resolve_note_path(path_text, memory_dir)
        if _is_within_memory_dir(resolved, memory_dir):
            indexed_targets.add(resolved)

    candidate_paths = _dedupe_paths(
        [_resolve_note_path(path_text, memory_dir) for path_text in paths]
    )
    removable_paths: list[Path] = []
    for candidate in candidate_paths:
        if not _is_within_memory_dir(candidate, memory_dir):
            continue
        if candidate.exists() or candidate in indexed_targets:
            removable_paths.append(candidate)

    removed = [_normalize_note_path(path, memory_dir) for path in removable_paths]
    if dry_run:
        return {"removed": removed, "count": len(removed), "dry_run": True}

    for path in removable_paths:
        if path.exists():
            path.unlink()

    if index_records:
        removable_set = {path.resolve() for path in removable_paths}
        filtered_records: list[tuple[str, dict[str, Any] | None]] = []
        for raw_line, row in index_records:
            if not isinstance(row, dict):
                filtered_records.append((raw_line, row))
                continue
            path_text = str(row.get("path", "")).strip()
            if not path_text:
                filtered_records.append((raw_line, row))
                continue
            resolved = _resolve_note_path(path_text, memory_dir)
            if resolved.resolve() in removable_set:
                continue
            filtered_records.append((raw_line, row))
        _write_index_records(index_path, filtered_records)

    return {"removed": removed, "count": len(removed), "dry_run": False}
