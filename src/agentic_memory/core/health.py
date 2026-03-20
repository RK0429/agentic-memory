"""Integrity checks for agentic-memory data."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from agentic_memory.core import index as index_module
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


def _config_is_valid(config_path: Path) -> tuple[bool, str | None]:
    """Check config file validity and return (is_valid, reason_if_invalid)."""
    if not config_path.exists():
        return False, "config file not found"
    if not config_path.is_file():
        return False, "config path is not a file"
    try:
        loaded = json.loads(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        return False, f"cannot read config file: {exc}"
    except json.JSONDecodeError as exc:
        return False, f"invalid JSON: {exc}"
    if not isinstance(loaded, dict):
        return False, f"expected JSON object, got {type(loaded).__name__}"
    return True, None


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
    config_valid, config_reason = _config_is_valid(config_path)

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

    result: dict[str, Any] = {
        "orphan_entries": orphan_entries,
        "unindexed_notes": unindexed_notes,
        "stale_entries": stale_entries,
        "state_valid": state_valid,
        "config_valid": config_valid,
        "summary": summary,
    }
    if config_reason is not None:
        result["config_invalid_reason"] = config_reason
    return result


def fix_issues(
    memory_dir: Path,
    *,
    force_reindex: bool = False,
) -> dict[str, Any]:
    """Re-index stale/unindexed notes and remove orphan index entries.

    When ``force_reindex`` is True, rebuilds the entire index from scratch
    instead of incrementally fixing stale/unindexed entries.  Use this after
    breaking schema changes (e.g. new index fields) that require all entries
    to be regenerated.

    Returns a report with counts of fixed issues.
    """
    index_path = memory_dir / "_index.jsonl"

    if force_reindex:
        notes = index_module.list_notes(memory_dir)
        entries = index_module.rebuild_index(
            index_path=index_path,
            dailynote_dir=memory_dir,
            no_dense=True,
        )
        post_check = health_check(memory_dir)
        return {
            "reindexed": [_normalize_note_path(p, memory_dir) for p in notes],
            "failed": [],
            "orphans_removed": 0,
            "force_reindex": True,
            "total_entries": len(entries),
            "post_fix_summary": post_check["summary"],
        }

    report = health_check(memory_dir)
    fixed: dict[str, Any] = {
        "reindexed": [],
        "failed": [],
        "orphans_removed": 0,
    }

    # Re-index stale entries
    paths_to_reindex: list[str] = list(report["stale_entries"]) + list(report["unindexed_notes"])
    for path_text in paths_to_reindex:
        resolved = _resolve_note_path(path_text, memory_dir)
        if not resolved.exists():
            fixed["failed"].append({"path": path_text, "error": "file not found"})
            continue
        try:
            index_module.index_note(
                note_path=resolved,
                index_path=index_path,
                dailynote_dir=memory_dir,
                no_dense=True,
            )
            fixed["reindexed"].append(path_text)
        except Exception as exc:
            fixed["failed"].append({"path": path_text, "error": str(exc)})

    # Remove orphan entries using the index module's lock mechanism
    orphans = set(report["orphan_entries"])
    if orphans:
        entries, _ = _load_index_entries(index_path)
        kept: list[dict[str, Any]] = [
            entry for entry in entries if str(entry.get("path", "")).strip() not in orphans
        ]
        removed = len(entries) - len(kept)
        if removed > 0:
            index_module._replace_all(index_path, kept)
            fixed["orphans_removed"] = removed

    # Re-run health check to get updated summary
    post_check = health_check(memory_dir)
    fixed["post_fix_summary"] = post_check["summary"]
    return fixed
