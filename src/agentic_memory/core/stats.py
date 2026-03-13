"""Storage statistics helpers for agentic-memory."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from agentic_memory.core import signals, state

_DATE_DIR_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _iter_note_paths(memory_dir: Path) -> list[Path]:
    if not memory_dir.exists():
        return []

    notes: list[Path] = []
    for child in sorted(memory_dir.iterdir()):
        if not child.is_dir() or not _DATE_DIR_RE.fullmatch(child.name):
            continue
        for note_path in sorted(child.glob("*.md")):
            if not note_path.is_file() or note_path.name.startswith("_"):
                continue
            notes.append(note_path)
    return notes


def _normalize_note_path(note_path: Path, memory_dir: Path) -> str:
    base_dir = memory_dir.resolve().parent
    try:
        return str(note_path.resolve().relative_to(base_dir))
    except ValueError:
        return str(note_path)


def _count_index_lines(index_path: Path) -> int:
    if not index_path.exists():
        return 0
    return sum(
        1
        for line in index_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        if line.strip()
    )


def _load_index_entries(index_path: Path) -> list[dict[str, Any]]:
    if not index_path.exists():
        return []
    try:
        return signals.load_index(index_path)
    except (FileNotFoundError, ValueError):
        return []


def _get_storage_bytes(memory_dir: Path) -> int:
    if not memory_dir.exists():
        return 0

    total = 0
    for path in memory_dir.rglob("*"):
        if not path.is_file():
            continue
        try:
            total += path.stat().st_size
        except OSError:
            continue
    return total


def _build_sigfb_summary(entries: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    aggregated = signals.aggregate_signals(entries)
    skills = aggregated.get("skills", {})
    if not isinstance(skills, dict):
        return {}

    summary: dict[str, dict[str, int]] = {}
    for skill, data in skills.items():
        if not isinstance(skill, str) or not isinstance(data, dict):
            continue
        summary[skill] = {
            signal_type: int(data.get(signal_type, 0))
            for signal_type in (*signals.SIGNAL_TYPES, "total", "total_negative")
        }
    return summary


def get_stats(memory_dir: Path) -> dict[str, Any]:
    """Collect storage statistics for a memory directory."""
    note_paths = _iter_note_paths(memory_dir)
    notes_by_date: dict[str, int] = {}
    for note_path in note_paths:
        notes_by_date[note_path.parent.name] = notes_by_date.get(note_path.parent.name, 0) + 1

    dates = sorted(notes_by_date)
    index_path = memory_dir / "_index.jsonl"
    state_path = memory_dir / "_state.md"
    state_items = {
        section_name: len(items)
        for section_name, items in state.load_state(state_path).items()
    }
    index_entries = _load_index_entries(index_path)

    return {
        "notes_count": len(note_paths),
        "notes_by_date": notes_by_date,
        "index_entries": _count_index_lines(index_path),
        "storage_bytes": _get_storage_bytes(memory_dir),
        "date_range": {
            "oldest": dates[0] if dates else "",
            "newest": dates[-1] if dates else "",
        },
        "sigfb_summary": _build_sigfb_summary(index_entries),
        "state_items": state_items,
    }
