from __future__ import annotations

import json
from contextlib import suppress
from pathlib import Path
from typing import Any, cast

from agentic_memory.core.index import (
    _acquire_index_lock,
    _atomic_write_text,
    _read_index_rows,
    _write_index_rows,
)
from agentic_memory.core.values.model import ValuesEntry, ValuesId


class ValuesRepository:
    def __init__(self, memory_dir: Path) -> None:
        self.memory_dir = Path(memory_dir)
        self.entries_dir = self.memory_dir / "values"
        self.index_path = self.memory_dir / "_values.jsonl"

    def save(self, entry: ValuesEntry) -> Path:
        path = self._entry_path(entry.id)
        payload = entry.to_dict()
        body = payload.pop("description")
        _atomic_write_text(path, self._render_document(payload, str(body)))
        self._upsert_index_row(self._build_index_row(entry))
        return path

    def load(self, values_id: ValuesId | str) -> ValuesEntry:
        return self._load_path(self._entry_path(values_id))

    def delete(self, values_id: ValuesId | str) -> bool:
        path = self._entry_path(values_id)
        deleted = False
        if path.exists():
            path.unlink()
            deleted = True
        self._delete_index_row(path)
        return deleted

    def list_all(self) -> list[ValuesEntry]:
        entries: list[ValuesEntry] = []
        for row in _read_index_rows(self.index_path):
            path_value = row.get("path")
            if not isinstance(path_value, str) or not path_value.strip():
                continue
            path = self.memory_dir / path_value
            with suppress(FileNotFoundError, ValueError):
                entries.append(self._load_path(path))
        return entries

    def find_by_id(self, values_id: ValuesId | str) -> ValuesEntry | None:
        with suppress(FileNotFoundError, ValueError):
            return self.load(values_id)
        return None

    def _entry_path(self, values_id: ValuesId | str) -> Path:
        return self.entries_dir / f"{ValuesId(str(values_id))}.md"

    def _load_path(self, path: Path) -> ValuesEntry:
        text = path.read_text(encoding="utf-8")
        frontmatter, body = self._parse_document(text)
        frontmatter["description"] = body
        return ValuesEntry.from_dict(frontmatter)

    def _upsert_index_row(self, entry: dict[str, Any]) -> None:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        lock_file = _acquire_index_lock(self.index_path)
        try:
            rows = _read_index_rows(self.index_path)
            output: list[dict[str, Any]] = []
            replaced = False
            for row in rows:
                if row.get("id") == entry["id"] or row.get("path") == entry["path"]:
                    output.append(entry)
                    replaced = True
                else:
                    output.append(row)
            if not replaced:
                output.append(entry)
            _write_index_rows(self.index_path, output)
        finally:
            lock_file.close()

    def _delete_index_row(self, path: Path) -> None:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        lock_file = _acquire_index_lock(self.index_path)
        try:
            relative_path = str(path.relative_to(self.memory_dir))
            rows = [
                row for row in _read_index_rows(self.index_path) if row.get("path") != relative_path
            ]
            _write_index_rows(self.index_path, rows)
        finally:
            lock_file.close()

    def _build_index_row(self, entry: ValuesEntry) -> dict[str, Any]:
        serialized = entry.to_dict()
        source_type = cast(str, serialized["source_type"])
        return {
            "id": str(entry.id),
            "path": str(self._entry_path(entry.id).relative_to(self.memory_dir)),
            "description": entry.description,
            "category": str(entry.category),
            "confidence": entry.confidence,
            "evidence_count": entry.total_evidence_count,
            "source_type": source_type,
            "promoted": entry.promoted,
            "promoted_at": serialized["promoted_at"],
            "promoted_confidence": serialized["promoted_confidence"],
            "demotion_reason": entry.demotion_reason,
            "demoted_at": serialized["demoted_at"],
            "created_at": serialized["created_at"],
            "updated_at": serialized["updated_at"],
        }

    @staticmethod
    def _render_document(frontmatter: dict[str, Any], body: str) -> str:
        lines = ["---"]
        for key, value in frontmatter.items():
            lines.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
        lines.extend(["---", body.rstrip(), ""])
        return "\n".join(lines)

    @staticmethod
    def _parse_document(text: str) -> tuple[dict[str, Any], str]:
        lines = text.splitlines()
        if not lines or lines[0].strip() != "---":
            raise ValueError("Missing YAML frontmatter")

        end_index = None
        for index, line in enumerate(lines[1:], start=1):
            if line.strip() == "---":
                end_index = index
                break
        if end_index is None:
            raise ValueError("Unterminated YAML frontmatter")

        payload: dict[str, Any] = {}
        for line in lines[1:end_index]:
            if not line.strip():
                continue
            key, separator, value = line.partition(":")
            if not separator:
                raise ValueError(f"Invalid frontmatter line: {line!r}")
            payload[key.strip()] = json.loads(value.strip())
        body = "\n".join(lines[end_index + 1 :]).rstrip("\n")
        return payload, body


__all__ = ["ValuesRepository"]
