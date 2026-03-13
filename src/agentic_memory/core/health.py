"""Integrity checks for agentic-memory data."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from agentic_memory.core import signals, state
from agentic_memory.core.stats import _iter_note_paths, _normalize_note_path

_INDEXED_AT_TOLERANCE_SECONDS = 1.0


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


def _parse_indexed_at(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _load_index_entries(index_path: Path) -> tuple[list[dict[str, Any]], str | None]:
    if not index_path.exists():
        return [], None
    try:
        return signals.load_index(index_path), None
    except (FileNotFoundError, ValueError) as exc:
        return [], str(exc)


def _state_is_valid(state_path: Path) -> bool:
    if not state_path.exists() or not state_path.is_file():
        return False
    try:
        loaded = state.load_state(state_path)
    except OSError:
        return False
    return set(state.SECTION_ORDER).issubset(loaded)


def _config_is_valid(config_path: Path) -> bool:
    if not config_path.exists() or not config_path.is_file():
        return False
    try:
        loaded = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(loaded, dict)


def health_check(memory_dir: Path) -> dict[str, Any]:
    """Check index/state/config consistency for a memory directory."""
    index_path = memory_dir / "_index.jsonl"
    state_path = memory_dir / "_state.md"
    config_path = memory_dir / "_rag_config.json"

    entries, index_error = _load_index_entries(index_path)
    orphan_entries: list[str] = []
    stale_entries: list[str] = []
    indexed_resolved_paths: set[Path] = set()

    for entry in entries:
        path_text = str(entry.get("path", "")).strip()
        if not path_text:
            continue

        resolved_note_path = _resolve_note_path(path_text, memory_dir)
        if (
            not _is_within_memory_dir(resolved_note_path, memory_dir)
            or not resolved_note_path.exists()
        ):
            orphan_entries.append(path_text)
            continue

        indexed_resolved_paths.add(resolved_note_path.resolve())
        indexed_at = _parse_indexed_at(entry.get("indexed_at"))
        try:
            note_mtime = resolved_note_path.stat().st_mtime
        except OSError:
            orphan_entries.append(path_text)
            continue

        if (
            indexed_at is None
            or (note_mtime - indexed_at.timestamp()) > _INDEXED_AT_TOLERANCE_SECONDS
        ):
            stale_entries.append(path_text)

    unindexed_notes = [
        _normalize_note_path(note_path, memory_dir)
        for note_path in _iter_note_paths(memory_dir)
        if note_path.resolve() not in indexed_resolved_paths
    ]
    orphan_entries = sorted(set(orphan_entries))
    stale_entries = sorted(set(stale_entries))
    unindexed_notes = sorted(set(unindexed_notes))
    state_valid = _state_is_valid(state_path)
    config_valid = _config_is_valid(config_path)

    if index_error:
        summary = (
            "要確認: "
            f"インデックスの読み込みに失敗しました ({index_error})。"
            f" 未索引ノート {len(unindexed_notes)} 件。"
        )
    else:
        status = (
            "正常"
            if (
                not orphan_entries
                and not unindexed_notes
                and not stale_entries
                and state_valid
                and config_valid
            )
            else "要確認"
        )
        summary = (
            f"{status}: orphan_entries {len(orphan_entries)} 件, "
            f"unindexed_notes {len(unindexed_notes)} 件, "
            f"stale_entries {len(stale_entries)} 件, "
            f"state {'有効' if state_valid else '無効'}, "
            f"config {'有効' if config_valid else '無効'}。"
        )

    return {
        "orphan_entries": orphan_entries,
        "unindexed_notes": unindexed_notes,
        "stale_entries": stale_entries,
        "state_valid": state_valid,
        "config_valid": config_valid,
        "summary": summary,
    }
