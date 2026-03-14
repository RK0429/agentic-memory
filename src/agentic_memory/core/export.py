"""Backup/export utilities for agentic-memory."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

from agentic_memory.core.stats import _iter_note_paths, _normalize_note_path


def _read_text_if_exists(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def export_memory(memory_dir: Path, output_path: Path, fmt: str = "json") -> dict[str, Any]:
    """Export memory contents to a JSON bundle or ZIP archive."""
    note_paths = _iter_note_paths(memory_dir)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if fmt == "json":
        payload = {
            "memory_dir": str(memory_dir),
            "notes": [
                {
                    "path": _normalize_note_path(note_path, memory_dir),
                    "content": note_path.read_text(encoding="utf-8", errors="ignore"),
                }
                for note_path in note_paths
            ],
            "index": {
                "path": "_index.jsonl",
                "content": _read_text_if_exists(memory_dir / "_index.jsonl"),
            },
            "state": {
                "path": "_state.md",
                "content": _read_text_if_exists(memory_dir / "_state.md"),
            },
            "config": {
                "path": "_rag_config.json",
                "content": _read_text_if_exists(memory_dir / "_rag_config.json"),
            },
        }
        output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    elif fmt == "zip":
        output_resolved = output_path.resolve()
        with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for file_path in sorted(memory_dir.rglob("*")):
                if not file_path.is_file():
                    continue
                if file_path.suffix == ".lock":
                    continue
                if file_path.resolve() == output_resolved:
                    continue
                archive.write(file_path, arcname=str(file_path.relative_to(memory_dir.parent)))
    else:
        raise ValueError("fmt must be 'json' or 'zip'")

    return {
        "output_path": str(output_path),
        "format": fmt,
        "notes_count": len(note_paths),
        "total_size_bytes": output_path.stat().st_size,
    }
