from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from agentic_memory.core.config import (
    PROMOTED_VALUES_BEGIN_RE,
    PROMOTED_VALUES_END_RE,
)
from agentic_memory.core.index import _acquire_index_lock, _atomic_write_text
from agentic_memory.core.values.model import ValuesEntry

_ENTRY_LINE_RE = re.compile(r"^- \[(?P<id>v-[^\]]+)\]\s+(?P<description>.+)$")
_PROJECTED_DESCRIPTION_LIMIT = 200
_BLOCKED_MARKERS = ("BEGIN:PROMOTED_VALUES", "END:PROMOTED_VALUES")


class AgentsMdAdapter:
    def resolve_agents_md_path(self, memory_dir: Path) -> Path | None:
        candidates: list[Path] = []
        env_path = os.environ.get("AGENTS_MD_PATH")
        if env_path:
            candidates.append(Path(env_path))
        candidates.extend(
            [
                Path(memory_dir).parent / "AGENTS.md",
                Path(memory_dir).parent / "CLAUDE.md",
            ]
        )
        for candidate in candidates:
            if not candidate.exists():
                continue
            return candidate.resolve() if candidate.is_symlink() else candidate
        return None

    def list_entries(self, agents_md_path: Path) -> list[str]:
        lines, begin_index, end_index = self._load_marked_lines(agents_md_path)
        return [line.strip() for line in lines[begin_index + 1 : end_index] if line.strip()]

    def append_entry(self, agents_md_path: Path, description: str, entry_id: str) -> None:
        entry_line = self._format_entry_line(description=description, entry_id=entry_id)
        lock_file = _acquire_index_lock(agents_md_path)
        try:
            lines, begin_index, end_index = self._load_marked_lines(agents_md_path)
            new_lines = [
                *lines[:end_index],
                entry_line,
                *lines[end_index:],
            ]
            self._write_lines(agents_md_path, new_lines)
        finally:
            lock_file.close()

    def update_entry(self, agents_md_path: Path, description: str, entry_id: str) -> bool:
        entry_line = self._format_entry_line(description=description, entry_id=entry_id)
        lock_file = _acquire_index_lock(agents_md_path)
        try:
            lines, begin_index, end_index = self._load_marked_lines(agents_md_path)
            updated = False
            new_lines = list(lines)
            for index in range(begin_index + 1, end_index):
                parsed = self._parse_entry(lines[index])
                if parsed is None or parsed["id"] != entry_id:
                    continue
                new_lines[index] = entry_line
                updated = True
                break
            if updated:
                self._write_lines(agents_md_path, new_lines)
            return updated
        finally:
            lock_file.close()

    def remove_entry(self, agents_md_path: Path, entry_id: str) -> bool:
        lock_file = _acquire_index_lock(agents_md_path)
        try:
            lines, begin_index, end_index = self._load_marked_lines(agents_md_path)
            kept_entries: list[str] = []
            removed = False
            for line in lines[begin_index + 1 : end_index]:
                parsed_entry_id = self._parse_entry_id(line)
                if parsed_entry_id == entry_id:
                    removed = True
                    continue
                kept_entries.append(line)
            new_lines = [
                *lines[: begin_index + 1],
                *kept_entries,
                *lines[end_index:],
            ]
            self._write_lines(agents_md_path, new_lines)
            return removed
        finally:
            lock_file.close()

    def sync_check(
        self,
        agents_md_path: Path,
        promoted_entries: list[ValuesEntry],
    ) -> dict[str, Any]:
        agents_md_entries = {
            parsed["id"]: parsed["description"]
            for parsed in (self._parse_entry(line) for line in self.list_entries(agents_md_path))
            if parsed is not None
        }
        promoted_ids = {str(entry.id) for entry in promoted_entries if entry.promoted}
        description_mismatches = [
            {
                "id": str(entry.id),
                "agents_md_description": agents_md_entries[str(entry.id)],
                "projected_description": self.project_description(entry.description),
            }
            for entry in promoted_entries
            if entry.promoted
            and str(entry.id) in agents_md_entries
            and agents_md_entries[str(entry.id)] != self.project_description(entry.description)
        ]
        return {
            "orphan_in_agents_md": sorted(set(agents_md_entries) - promoted_ids),
            "missing_in_agents_md": sorted(promoted_ids - set(agents_md_entries)),
            "description_mismatches": sorted(
                description_mismatches,
                key=lambda item: item["id"],
            ),
        }

    @classmethod
    def project_description(cls, description: str) -> str:
        projected = str(description)
        if any(marker in projected for marker in _BLOCKED_MARKERS):
            raise ValueError("Promoted value description cannot include promoted values markers")
        projected = projected.replace("\r\n", "\n").replace("\r", "\n").replace("\n", " ")
        projected = projected.replace("<!--", "").replace("-->", "").strip()
        if not projected:
            raise ValueError("Promoted value description cannot be empty")
        if len(projected) > _PROJECTED_DESCRIPTION_LIMIT:
            projected = projected[: _PROJECTED_DESCRIPTION_LIMIT - 1].rstrip() + "…"
        return projected

    @classmethod
    def _format_entry_line(cls, *, description: str, entry_id: str) -> str:
        return f"- [{entry_id}] {cls.project_description(description)}"

    @staticmethod
    def _parse_entry_id(line: str) -> str | None:
        match = _ENTRY_LINE_RE.fullmatch(line.strip())
        if match is None:
            return None
        return match.group("id")

    @staticmethod
    def _parse_entry(line: str) -> dict[str, str] | None:
        match = _ENTRY_LINE_RE.fullmatch(line.strip())
        if match is None:
            return None
        return {
            "id": match.group("id"),
            "description": match.group("description"),
        }

    @staticmethod
    def _write_lines(path: Path, lines: list[str]) -> None:
        _atomic_write_text(path, "\n".join(lines).rstrip("\n") + "\n")

    @staticmethod
    def _load_marked_lines(path: Path) -> tuple[list[str], int, int]:
        lines = path.read_text(encoding="utf-8").splitlines()
        begin_index = next(
            (
                index
                for index, line in enumerate(lines)
                if PROMOTED_VALUES_BEGIN_RE.match(line.strip())
            ),
            None,
        )
        end_index = next(
            (
                index
                for index, line in enumerate(lines)
                if PROMOTED_VALUES_END_RE.match(line.strip())
            ),
            None,
        )
        if begin_index is None or end_index is None:
            raise ValueError("AGENTS.md is missing promoted values markers")
        if begin_index >= end_index:
            raise ValueError("AGENTS.md promoted values markers are malformed")
        return lines, begin_index, end_index


__all__ = ["AgentsMdAdapter"]
