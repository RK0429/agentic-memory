"""Prepare distillation materials for the calling agent.

The prepare step is stateless and deterministic: it collects notes, lists
existing items, and builds instruction/schema payloads.  No LLM calls are made.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agentic_memory.core import index, sections, state
from agentic_memory.core.knowledge import KnowledgeRepository
from agentic_memory.core.values import ValuesRepository

_NOTE_DATE_DIR_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# ---------------------------------------------------------------------------
# Candidate schemas (returned to the calling agent)
# ---------------------------------------------------------------------------

KNOWLEDGE_CANDIDATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["title", "content", "domain"],
    "properties": {
        "title": {"type": "string", "description": "Concise knowledge title"},
        "content": {
            "type": "string",
            "description": "Knowledge body (facts, rules, procedures)",
        },
        "domain": {
            "type": "string",
            "description": "kebab-case domain (e.g. 'python', 'architecture')",
        },
        "tags": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Optional tags for discoverability",
        },
        "accuracy": {
            "type": "string",
            "enum": ["verified", "likely", "uncertain"],
            "description": "Confidence in factual accuracy (default: uncertain)",
        },
        "sources": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["type", "ref", "summary"],
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": [
                            "memory_note",
                            "web",
                            "user_direct",
                            "document",
                            "code",
                            "other",
                        ],
                        "description": "Reference type (ReferenceType enum value)",
                    },
                    "ref": {
                        "type": "string",
                        "description": "Source reference (note path, URL, etc.)",
                    },
                    "summary": {
                        "type": "string",
                        "description": "Brief source summary",
                    },
                },
                "additionalProperties": False,
            },
            "description": "Provenance sources for this knowledge item",
        },
        "user_understanding": {
            "type": "string",
            "enum": ["unknown", "novice", "familiar", "proficient", "expert"],
            "description": "User understanding level (default: unknown)",
        },
        "related": {
            "type": "array",
            "items": {"type": "string"},
            "description": "IDs of related knowledge entries (k-... format)",
        },
    },
    "additionalProperties": False,
}

VALUES_CANDIDATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["description", "category"],
    "properties": {
        "description": {
            "type": "string",
            "description": "Value/preference description",
        },
        "category": {
            "type": "string",
            "description": "kebab-case category (e.g. 'review', 'architecture')",
        },
        "confidence": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
            "description": "Initial confidence (default: 0.3)",
        },
        "evidence": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["ref", "summary", "date"],
                "properties": {
                    "ref": {
                        "type": "string",
                        "description": "Source reference (note path, _state.md#section, etc.)",
                    },
                    "summary": {
                        "type": "string",
                        "description": "Brief evidence summary",
                    },
                    "date": {
                        "type": "string",
                        "format": "date",
                        "description": "ISO YYYY-MM-DD date of the evidence",
                    },
                },
                "additionalProperties": False,
            },
            "description": "Supporting evidence items",
        },
    },
    "additionalProperties": False,
}

# ---------------------------------------------------------------------------
# Instruction templates
# ---------------------------------------------------------------------------

_KNOWLEDGE_INSTRUCTIONS = """\
You are distilling reusable Knowledge from the Memory notes below.

## Task
Analyze the provided notes and extract discrete knowledge items — facts, rules,
procedures, or concepts that would be valuable in future sessions.

## Guidelines
- Each item must have a clear, concise title and substantive content.
- Domain should be a kebab-case identifier (e.g. "python", "architecture", "ci-cd").
- Check `existing_items` to avoid duplicates.  If an existing item covers the same
  topic, do NOT create a new one unless the note adds materially new information.
- Set `accuracy` conservatively: use "verified" only for well-established facts,
  "likely" for reasonable inferences, "uncertain" for preliminary observations.
- Include `tags` for discoverability.
- Use `related` to link to relevant existing knowledge IDs.
- Do NOT include secrets, credentials, or API keys in content.
- Return an empty `candidates` array if no knowledge is worth extracting.

## Output
Return a JSON array of candidates matching the `candidate_schema`.\
"""

_VALUES_INSTRUCTIONS = """\
You are distilling Values (judgment patterns / preferences) from the Memory notes
and major decisions below.

## Task
Analyze the provided notes and decisions to identify recurring judgment patterns,
preferences, or principles that should guide future behavior.

## Guidelines
- Each item should describe a single preference or judgment tendency.
- Category should be a kebab-case identifier (e.g. "review", "architecture", "testing").
- Check `existing_items` to avoid duplicates.  If an existing value covers the same
  preference, reinforce it via `memory_values_update` instead of creating a duplicate.
- Set `confidence` conservatively (default 0.3 for new observations).
- Include `evidence` with references to the specific notes or decisions that support
  the value.  Date should be in ISO YYYY-MM-DD format.
- Do NOT include secrets, credentials, or API keys in descriptions.
- Return an empty `candidates` array if no values are worth extracting.

## Output
Return a JSON array of candidates matching the `candidate_schema`.\
"""


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PrepareResult:
    """Materials for the calling agent to perform distillation."""

    notes: list[dict[str, Any]]
    decisions: str | None
    existing_items: list[dict[str, Any]]
    instructions: str
    candidate_schema: dict[str, Any]


# ---------------------------------------------------------------------------
# Preparer
# ---------------------------------------------------------------------------


class DistillationPreparer:
    """Collect and package distillation materials.

    All methods are stateless and deterministic (no LLM calls).
    """

    def prepare_knowledge(
        self,
        memory_dir: str | Path,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
        domain: str | None = None,
    ) -> PrepareResult:
        resolved = Path(memory_dir)
        start_date, end_date = _validate_date_range(date_from, date_to)

        note_paths = _collect_note_paths(resolved, start_date=start_date, end_date=end_date)
        notes = [_build_knowledge_snapshot(path, resolved) for path in note_paths]

        existing = KnowledgeRepository(resolved).list_all()
        if domain is not None:
            from agentic_memory.core.knowledge.model import Domain

            normalized_domain = str(Domain.normalize(domain))
            existing = [e for e in existing if str(e.domain) == normalized_domain]

        existing_items = [
            {
                "id": str(e.id),
                "title": e.title,
                "domain": str(e.domain),
                "tags": list(e.tags),
            }
            for e in existing
        ]

        return PrepareResult(
            notes=notes,
            decisions=None,
            existing_items=existing_items,
            instructions=_KNOWLEDGE_INSTRUCTIONS,
            candidate_schema=KNOWLEDGE_CANDIDATE_SCHEMA,
        )

    def prepare_values(
        self,
        memory_dir: str | Path,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
        category: str | None = None,
    ) -> PrepareResult:
        resolved = Path(memory_dir)
        start_date, end_date = _validate_date_range(date_from, date_to)

        note_paths = _collect_note_paths(resolved, start_date=start_date, end_date=end_date)
        notes = [_build_values_snapshot(path, resolved) for path in note_paths]

        decisions = _collect_state_decisions(resolved / "_state.md")

        existing = ValuesRepository(resolved).list_all()
        if category is not None:
            from agentic_memory.core.values.model import Category

            normalized_category = str(Category.normalize(category))
            existing = [e for e in existing if str(e.category) == normalized_category]

        existing_items = [
            {
                "id": str(e.id),
                "description": e.description,
                "category": str(e.category),
            }
            for e in existing
        ]

        return PrepareResult(
            notes=notes,
            decisions=decisions,
            existing_items=existing_items,
            instructions=_VALUES_INSTRUCTIONS,
            candidate_schema=VALUES_CANDIDATE_SCHEMA,
        )


# ---------------------------------------------------------------------------
# Internal helpers (extracted from the former DistillationService)
# ---------------------------------------------------------------------------


def _validate_date_range(
    date_from: str | None,
    date_to: str | None,
) -> tuple[dt.date | None, dt.date]:
    start_date = dt.date.fromisoformat(date_from) if date_from is not None else None
    end_date = dt.date.fromisoformat(date_to) if date_to is not None else dt.date.today()
    if start_date is not None and start_date > end_date:
        raise ValueError("date_from must be on or before date_to")
    return start_date, end_date


def _collect_note_paths(
    memory_dir: Path,
    *,
    start_date: dt.date | None,
    end_date: dt.date,
) -> list[Path]:
    note_paths: list[Path] = []
    if not memory_dir.exists():
        return note_paths
    for child in sorted(memory_dir.iterdir()):
        if not child.is_dir() or not _NOTE_DATE_DIR_RE.fullmatch(child.name):
            continue
        dir_date = dt.date.fromisoformat(child.name)
        if start_date is not None and dir_date < start_date:
            continue
        if dir_date > end_date:
            continue
        note_paths.extend(sorted(path for path in child.glob("*.md") if path.is_file()))
    return note_paths


def _build_knowledge_snapshot(note_path: Path, memory_dir: Path) -> dict[str, Any]:
    markdown = index.read_text(note_path)
    parsed_sections = index.parse_sections(markdown)
    section_map = {
        "decisions": _section_items(parsed_sections, "判断"),
        "pitfalls": _section_items(parsed_sections, "注意点・残課題"),
        "outcome": _section_items(parsed_sections, "成果"),
        "work_log": _section_items(parsed_sections, "作業ログ"),
    }
    return _note_snapshot(note_path, memory_dir, markdown, section_map)


def _build_values_snapshot(note_path: Path, memory_dir: Path) -> dict[str, Any]:
    markdown = index.read_text(note_path)
    parsed_sections = index.parse_sections(markdown)
    section_map = {
        "decisions": _section_items(parsed_sections, "判断"),
    }
    return _note_snapshot(note_path, memory_dir, markdown, section_map)


def _note_snapshot(
    note_path: Path,
    memory_dir: Path,
    markdown: str,
    section_map: dict[str, list[str]],
) -> dict[str, Any]:
    note_id = _note_ref(note_path, memory_dir)
    title = index.first_h1(markdown)
    combined: list[str] = []
    for section_name, items in section_map.items():
        if not items:
            continue
        combined.append(f"## {section_name}\n" + "\n".join(f"- {item}" for item in items))

    tags: list[str] = []
    for section_name, items in section_map.items():
        if items:
            tags.append(section_name)

    return {
        "note_id": note_id,
        "title": title,
        "content": "\n\n".join(combined),
        "date": note_path.parent.name,
        "tags": tags,
    }


def _section_items(parsed_sections: dict[str, list[str]], section_name: str) -> list[str]:
    lines = sections.get_section(parsed_sections, section_name)
    items = state.bullets(lines)
    if items:
        return items
    return [line.strip() for line in lines if line.strip() and not line.strip().startswith("```")]


def _note_ref(note_path: Path, memory_dir: Path) -> str:
    try:
        return str(note_path.relative_to(memory_dir.parent))
    except ValueError:
        return str(note_path)


def _collect_state_decisions(state_path: Path) -> str | None:
    sections_data = state.load_state(state_path)
    decisions = sections_data.get(state.STATE_SHORT_KEYS["decisions"], [])
    if not decisions:
        return None
    return "\n".join(item.render() for item in decisions)


__all__ = [
    "DistillationPreparer",
    "KNOWLEDGE_CANDIDATE_SCHEMA",
    "PrepareResult",
    "VALUES_CANDIDATE_SCHEMA",
]
