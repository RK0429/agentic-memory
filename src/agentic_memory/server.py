"""MCP server for agentic-memory tools."""

from __future__ import annotations

import dataclasses
import datetime as _dt
import io
import json
import os
from collections.abc import Callable, Mapping
from contextlib import redirect_stderr, redirect_stdout, suppress
from pathlib import Path
from typing import Any, Literal, cast

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from agentic_memory.core import (
    cleanup,
    config,
    evidence,
    export,
    health,
    index,
    note,
    search,
    sections,
    state,
    stats,
)
from agentic_memory.core.distillation.prepare import DistillationPreparer
from agentic_memory.core.knowledge import (
    DuplicateKnowledgeError,
    KnowledgeEntry,
    KnowledgeService,
    Source,
)
from agentic_memory.core.knowledge.model import Accuracy, SourceType
from agentic_memory.core.scorer import load_index
from agentic_memory.core.security import SecretScanPolicy
from agentic_memory.core.task_ids import (
    invalid_task_id_message,
)
from agentic_memory.core.task_ids import (
    normalize_task_id as _normalize_task_id,
)
from agentic_memory.core.values import (
    PromotionManager,
    PromotionService,
    ValuesEntry,
    ValuesService,
)

try:
    mcp = FastMCP(
        "memory",
        description="Persistent memory system for AI agents",
    )  # type: ignore[call-arg]
except TypeError:
    # Backward compatibility for mcp versions where FastMCP(description=...) is unavailable.
    mcp = FastMCP("memory")

# MCP tool annotations
_READONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
_READONLY_OPEN_WORLD = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    openWorldHint=True,
)
_ADDITIVE = ToolAnnotations(destructiveHint=False, openWorldHint=False)
_IDEMPOTENT = ToolAnnotations(destructiveHint=False, idempotentHint=True, openWorldHint=False)
_DESTRUCTIVE = ToolAnnotations(destructiveHint=True, openWorldHint=False)


def _resolve_dir(explicit: str | None = None) -> Path:
    """Resolve the memory directory from explicit input, env, or config defaults.

    Resolution order is:
    1. explicit `memory_dir`
    2. `MEMORY_DIR` environment variable
    3. `config.resolve_memory_dir()`
    """
    if explicit:
        return Path(explicit)
    env = os.environ.get("MEMORY_DIR")
    if env:
        return Path(env)
    return config.resolve_memory_dir()


def _state_path(memory_dir: Path) -> Path:
    return memory_dir / "_state.md"


def _index_path(memory_dir: Path) -> Path:
    return memory_dir / "_index.jsonl"


def _rollback_created_note(note_path: Path, memory_dir: Path) -> str | None:
    try:
        note_path.unlink(missing_ok=True)
    except OSError as exc:
        return str(exc)
    parent = note_path.parent
    if parent != memory_dir and parent.parent == memory_dir:
        with suppress(OSError):
            parent.rmdir()
    return None


def _rollback_indexing_failure(
    note_path: Path,
    memory_dir: Path,
    *,
    payload_factory: Callable[[], str],
    original_message: str,
) -> str:
    rollback_error = _rollback_created_note(note_path, memory_dir)
    if rollback_error is None:
        return payload_factory()
    return _error_payload(
        error_type="io_error",
        message=(
            f"{original_message} Note rollback also failed for '{note_path}': {rollback_error}"
        ),
        hint=(
            "Check filesystem permissions. The note may have been created but not "
            "indexed; inspect and remove it manually if needed."
        ),
    )


def _serialize_json(value: Any) -> str:
    return json.dumps(_to_jsonable(value), ensure_ascii=False, indent=2, default=str)


def _to_jsonable(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _to_jsonable(dataclasses.asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_to_jsonable(v) for v in value]
    return value


def _success_payload(value: Any) -> str:
    payload = _to_jsonable(value)
    if isinstance(payload, dict):
        data = dict(payload)
        data.setdefault("ok", True)
        return _serialize_json(data)
    return _serialize_json({"ok": True, "result": payload})


def _error_payload(
    *,
    error_type: str,
    message: str,
    hint: str | None = None,
    exit_code: int = 2,
) -> str:
    payload: dict[str, Any] = {
        "ok": False,
        "error_type": error_type,
        "message": message,
        "exit_code": exit_code,
    }
    if hint is not None:
        payload["hint"] = hint
    return _serialize_json(payload)


def _state_command_error_payload(message: str, *, exit_code: int) -> str:
    text = message.strip() or f"State command failed (exit_code={exit_code})"
    if text.startswith(f"{state.NOTE_NOT_FOUND_PREFIX}:"):
        return _error_payload(
            error_type="not_found",
            message=text,
            hint="Verify `note_path` exists. Use `memory_note_new` to create a note first.",
            exit_code=exit_code,
        )
    if text.startswith(f"{sections.UNKNOWN_SECTION_KEY_PREFIX}:"):
        return _error_payload(
            error_type="validation_error",
            message=text,
            hint="Use one of the accepted section keys or aliases shown in the message.",
            exit_code=exit_code,
        )
    if text.startswith(f"{state.FAILED_TO_READ_NOTE_PREFIX}:"):
        return _error_payload(
            error_type="io_error",
            message=text,
            hint="Check filesystem permissions and that the note file is readable.",
            exit_code=exit_code,
        )
    if (
        "Invalid auto_improve_mode:" in text
        or "must be non-negative" in text
        or "must be >= 0" in text
    ):
        return _error_payload(
            error_type="validation_error",
            message=text,
            hint="Adjust the auto-improve mode or numeric option and retry.",
            exit_code=exit_code,
        )
    return _error_payload(error_type="command_error", message=text, exit_code=exit_code)


def _index_upsert_error_payload(message: str) -> str:
    text = message.strip() or "Index upsert failed"
    if text.startswith(f"{state.NOTE_NOT_FOUND_PREFIX}:"):
        return _error_payload(
            error_type="not_found",
            message=text,
            hint="Verify `note_path` exists. Use `memory_note_new` to create a note first.",
        )
    if text.startswith("Invalid task_id:"):
        return _error_payload(
            error_type="validation_error",
            message=text,
            hint="Pass `task_id` as TASK-123 / GOAL-123 or a relay task UUID, or omit it.",
        )
    return _error_payload(
        error_type="validation_error",
        message=text,
        hint="Check the input parameters and retry.",
    )


def _validation_error_payload(message: str, *, default_hint: str) -> str:
    text = message.strip() or "Validation failed"
    if text.startswith("Invalid task_id:"):
        return _error_payload(
            error_type="validation_error",
            message=text,
            hint="Pass `task_id` as TASK-123 / GOAL-123 or a relay task UUID, or omit it.",
        )
    if text.startswith("Either 'paths' or 'task_id' must be provided"):
        return _error_payload(
            error_type="validation_error",
            message=text,
            hint="Pass explicit `paths` or one valid `task_id` to resolve note paths.",
        )
    if text.startswith("Cannot specify both 'paths' and 'task_id'."):
        return _error_payload(
            error_type="validation_error",
            message=text,
            hint="Pass either explicit `paths` or one valid `task_id`, but not both.",
        )
    if text.startswith("No notes found for task_id"):
        return _error_payload(
            error_type="not_found",
            message=text,
            hint="Index a note with the matching `task_id`, or pass explicit `paths`.",
        )
    if text.startswith("At least one of 'memory_dirs' or 'memory_dir' must be provided"):
        return _error_payload(
            error_type="validation_error",
            message=text,
            hint="Pass one or more memory directories via `memory_dirs` or `memory_dir`.",
        )
    if "is not a valid SourceType" in text or "is not a valid ReferenceType" in text:
        return _error_payload(
            error_type="validation_error",
            message=text,
            hint=(
                'Valid source reference type values: "memory_note", "web", '
                '"user_direct", "document", "code", "other".'
                if "is not a valid ReferenceType" in text
                else 'Valid `origin` values: "memory_distillation", '
                '"autonomous_research", "user_taught".'
            ),
        )
    if "is not a valid Accuracy" in text or "is not a valid UserUnderstanding" in text:
        return _error_payload(
            error_type="validation_error",
            message=text,
            hint=(
                'Valid `user_understanding` values: "unknown", "novice", '
                '"familiar", "proficient", "expert".'
                if "is not a valid UserUnderstanding" in text
                else 'Valid `accuracy` values: "verified", "likely", "uncertain".'
            ),
        )
    return _error_payload(
        error_type="validation_error",
        message=text,
        hint=default_hint,
    )


def _render_state_show_output(
    sections_payload: dict[str, Any],
    frontmatter: dict[str, Any] | None = None,
) -> str:
    lines: list[str] = []
    frontmatter_payload = frontmatter or {}
    if frontmatter_payload:
        lines.append("## 蒸留メタデータ")
        for key, value in frontmatter_payload.items():
            rendered = "null" if value is None else str(value)
            lines.append(f"- {key}: {rendered}")
        lines.append("")
    for section_name, rows in sections_payload.items():
        cap = state.get_cap(section_name)
        row_list = rows if isinstance(rows, list) else []
        lines.append(f"## {section_name} ({len(row_list)}/{cap})")
        if not row_list:
            lines.append("- (empty)")
            lines.append("")
            continue
        for row in row_list:
            if not isinstance(row, dict):
                continue
            date = row.get("date", "")
            text = row.get("text", "")
            stale_mark = " [STALE]" if row.get("stale") else ""
            lines.append(f"- [{date}] {text}{stale_mark}")
        lines.append("")
    return "\n".join(lines).rstrip()


def _capture_state_cmd(func: Callable[..., int], *args: Any, **kwargs: Any) -> str:
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = func(*args, **kwargs)

    stdout_text = out.getvalue().strip()
    stderr_text = err.getvalue().strip()

    if code != 0:
        return _state_command_error_payload(stderr_text or stdout_text, exit_code=code)
    if stdout_text:
        try:
            parsed = json.loads(stdout_text)
        except json.JSONDecodeError:
            payload: dict[str, Any] = {"raw_output": stdout_text}
            if stderr_text:
                payload["warnings"] = [stderr_text]
            return _success_payload(payload)
        if not isinstance(parsed, dict):
            payload = {"raw_output": stdout_text}
            if stderr_text:
                payload["warnings"] = [stderr_text]
            return _success_payload(payload)
        if stderr_text:
            warnings = parsed.get("warnings", [])
            if not isinstance(warnings, list):
                warnings = [str(warnings)]
            parsed["warnings"] = [*warnings, stderr_text]
        return _success_payload(parsed)
    if stderr_text:
        return _success_payload({"warnings": [stderr_text]})
    return _success_payload({})


def _resolve_note_path(note_path: str, memory_dir: Path) -> Path:
    p = Path(note_path)
    if p.is_absolute():
        return p
    if p.exists():
        return p
    parent_relative = memory_dir.parent / p
    if parent_relative.exists():
        return parent_relative
    # Path already starts with memory_dir name (e.g., from search results) —
    # return parent-relative form to avoid doubling (file may not exist yet)
    if p.parts and p.parts[0] == memory_dir.name:
        return parent_relative
    return memory_dir / p


def _normalize_paths_arg(paths: list[str] | str) -> list[str]:
    if isinstance(paths, str):
        return [paths]
    return paths


def _resolve_paths(paths: list[str] | str, memory_dir: Path) -> list[Path]:
    normalized_paths = _normalize_paths_arg(paths)
    resolved: list[Path] = []
    for raw in normalized_paths:
        p = Path(raw)
        if p.is_absolute() or p.exists():
            resolved.append(p)
        elif (memory_dir.parent / p).exists():
            resolved.append(memory_dir.parent / p)
        elif p.parts and p.parts[0] == memory_dir.name:
            # Avoid path doubling (e.g., memory/memory/...)
            resolved.append(memory_dir.parent / p)
        else:
            resolved.append(memory_dir / p)
    return resolved


def _entry_to_dict(entry: object, exclude: frozenset[str] = frozenset()) -> dict:
    """Convert an IndexEntry (dataclass or dict) to a plain dict, excluding specified fields."""
    if dataclasses.is_dataclass(entry) and not isinstance(entry, type):
        entry_dict = dataclasses.asdict(entry)
    elif isinstance(entry, dict):
        entry_dict = dict(entry)
    else:
        return {}
    if exclude:
        entry_dict = {k: v for k, v in entry_dict.items() if k not in exclude}
    return entry_dict


def _strip_null_empty(d: dict) -> dict:
    """Remove keys with None or empty string (``""``) values from a dict.

    Empty lists and dicts are preserved intentionally — they carry semantic
    meaning (e.g. ``tags: []`` means "no tags", not "unknown").
    """
    return {k: v for k, v in d.items() if v is not None and v != ""}


def _knowledge_content_snippet(content: str, limit: int = 200) -> str:
    normalized = " ".join(content.split())
    return normalized[:limit]


def _knowledge_entry_payload(
    entry: KnowledgeEntry,
    *,
    score: float | None,
    include_full_content: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": str(entry.id),
        "title": entry.title,
        "domain": str(entry.domain),
        "accuracy": str(entry.accuracy),
        "user_understanding": str(entry.user_understanding),
        "content_snippet": _knowledge_content_snippet(entry.content),
        "score": round(score, 6) if score is not None else None,
    }
    if include_full_content:
        entry_dict = entry.to_dict()
        payload.update(
            {
                "content": entry_dict["content"],
                "sources": entry_dict["sources"],
                "tags": entry_dict["tags"],
                "related": entry_dict["related"],
                "origin": entry_dict["origin"],
                "created_at": entry_dict["created_at"],
                "updated_at": entry_dict["updated_at"],
            }
        )
    return payload


def _flatten_results(
    results: list,
    exclude: frozenset[str] = frozenset(),
    *,
    strip_empty: bool = False,
    include_detail: bool = False,
) -> list[Any]:
    """Convert (score, entry, detail?) tuples to flat {score, ...entry} objects.

    Applied only at the MCP serialization boundary (server.py). Internal APIs
    (search.search, search.search_global) continue to use tuple format.
    """
    flat: list[Any] = []
    for item in results:
        if isinstance(item, tuple | list) and len(item) >= 2:
            score, entry, *rest = item
            entry_dict = _entry_to_dict(entry, exclude)
            if not entry_dict:
                flat.append(item)
                continue
            obj: dict[str, Any] = {"score": score, **entry_dict}
            detail = rest[0] if rest else {}
            if include_detail and detail:
                obj["score_detail"] = detail
            if strip_empty:
                obj = _strip_null_empty(obj)
            flat.append(obj)
        else:
            flat.append(item)
    return flat


def _strip_compact_fields(result: dict) -> dict:
    """Remove verbose index fields and settings echo-back from compact mode results."""
    result = dict(result)
    result["results"] = _flatten_results(
        result.get("results", []),
        search.COMPACT_EXCLUDE_FIELDS,
        strip_empty=True,
    )
    # Strip empty/null metadata fields
    for key in ("feedback_source_note", "feedback_terms_used", "suggestions"):
        val = result.get(key)
        if val is None or val == []:
            result.pop(key, None)
    filters = result.get("filters")
    if isinstance(filters, dict) and all(v is None for v in filters.values()):
        result.pop("filters", None)
    # Strip settings echo-back fields
    for key in (
        "expand_enabled",
        "feedback_expand",
        "top",
        "snippets",
        "rerank_enabled",
        "rerank_auto_enabled",
        "compact",
    ):
        result.pop(key, None)
    # Strip empty warnings list
    if result.get("warnings") == []:
        result.pop("warnings", None)
    return result


def _strip_global_compact_fields(result: dict) -> dict:
    """Apply tighter compact projection for global search results."""
    result = dict(result)
    result["results"] = _flatten_results(
        result.get("results", []),
        search.GLOBAL_COMPACT_EXCLUDE_FIELDS,
        strip_empty=True,
    )
    for key in ("feedback_source_note", "feedback_terms_used", "suggestions"):
        val = result.get(key)
        if val is None or val == []:
            result.pop(key, None)
    filters = result.get("filters")
    if isinstance(filters, dict) and all(v is None for v in filters.values()):
        result.pop("filters", None)
    for key in (
        "expand_enabled",
        "feedback_expand",
        "top",
        "snippets",
        "rerank_enabled",
        "rerank_auto_enabled",
        "compact",
        "source_engines",
    ):
        result.pop(key, None)
    if result.get("warnings") == []:
        result.pop("warnings", None)
    return result


def _strip_detailed_fields(result: dict) -> dict:
    """Remove verbose CJK n-gram arrays from detailed mode results."""
    result = dict(result)
    result["results"] = _flatten_results(
        result.get("results", []),
        search.DETAILED_EXCLUDE_FIELDS,
        include_detail=True,
    )
    return result


def _strip_debug_fields(result: dict) -> dict:
    """Flatten results for debug mode (include score_detail)."""
    result = dict(result)
    result["results"] = _flatten_results(
        result.get("results", []),
        include_detail=True,
    )
    return result


def _filter_notes_by_since(notes: list[Path], since: str | None) -> list[Path]:
    if since is None:
        return notes

    try:
        since_date = _dt.date.fromisoformat(since)
    except ValueError as exc:
        raise ValueError(f"Invalid since date: {since}") from exc

    filtered: list[Path] = []
    for note_path in notes:
        try:
            dir_date = _dt.date.fromisoformat(note_path.parent.name)
            if dir_date < since_date:
                continue
        except ValueError:
            pass
        filtered.append(note_path)
    return filtered


_SCORE_OMITTED = object()


def _values_entry_payload(
    entry: ValuesEntry,
    *,
    score: float | None | object = _SCORE_OMITTED,
    include_full_content: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": str(entry.id),
        "description": entry.description,
        "category": str(entry.category),
        "confidence": entry.confidence,
        "evidence_count": entry.total_evidence_count,
        "promoted": entry.promoted,
    }
    if score is not _SCORE_OMITTED:
        payload["score"] = score
    if include_full_content:
        entry_dict = entry.to_dict()
        payload.update(
            {
                "evidence": entry_dict["evidence"],
                "origin": entry_dict["origin"],
                "created_at": entry_dict["created_at"],
                "updated_at": entry_dict["updated_at"],
            }
        )
    return payload


def _values_error_payload(message: str) -> str:
    text = message.strip() or "Values operation failed"
    if text.startswith("Values entry not found:"):
        return _error_payload(
            error_type="not_found",
            message=text,
            hint="Verify the values `id` exists before retrying.",
        )
    if text == "AGENTS.md not found":
        return _error_payload(
            error_type="not_found",
            message=text,
            hint=(
                "Set `AGENTS_MD_PATH` or place `AGENTS.md` / `CLAUDE.md` "
                "next to the memory directory."
            ),
        )
    if "does not meet promotion criteria" in text:
        return _error_payload(
            error_type="validation_error",
            message=text,
            hint=(
                "Increase confidence to >= "
                f"{PromotionManager.CONFIDENCE_THRESHOLD} and accumulate >= "
                f"{PromotionManager.EVIDENCE_THRESHOLD} evidence items via "
                "memory_values_update, then retry promotion."
            ),
        )
    if text.startswith("Values entry is not promoted:"):
        return _error_payload(
            error_type="state_error",
            message=text,
            hint="This entry is not currently promoted. No demotion is needed.",
        )
    if "confidence must be between" in text:
        return _error_payload(
            error_type="validation_error",
            message=text,
            hint=(
                "Provide `confidence` as a float in the inclusive range [0.0, 1.0] "
                "(e.g. 0.8) and retry."
            ),
        )
    return _error_payload(
        error_type="validation_error",
        message=text,
        hint="Verify the values parameters and retry.",
    )


def _secret_validation_error_payload(*texts: str) -> str | None:
    detector_names: list[str] = []
    seen: set[str] = set()
    for text in texts:
        for match in SecretScanPolicy.scan(text):
            if match.pattern_name in seen:
                continue
            seen.add(match.pattern_name)
            detector_names.append(match.pattern_name)
    if not detector_names:
        return None
    return _error_payload(
        error_type="validation_error",
        message=(
            "Content appears to contain secrets "
            f"(detected: {', '.join(detector_names)}). "
            "Remove secrets or sanitize the content before retrying."
        ),
        hint=(
            "Sanitize sensitive values (API keys, tokens, high-entropy strings) "
            "from the content and retry."
        ),
        exit_code=2,
    )


def _required_schema_hint(
    field_name: str,
    schema_fields: tuple[str, ...],
    payload: Any,
    *,
    schema_repr: str | None = None,
) -> str:
    missing_fields = _missing_required_fields(payload, schema_fields)
    schema = schema_repr if schema_repr is not None else "{" + ", ".join(schema_fields) + "}"
    return (
        f"Pass `{field_name}` as a list of objects with shape {schema}. "
        f"Missing fields: {', '.join(missing_fields)}."
    )


def _missing_required_fields(payload: Any, schema_fields: tuple[str, ...]) -> list[str]:
    candidates = payload if isinstance(payload, list | tuple) else [payload]
    for item in candidates:
        if not isinstance(item, Mapping):
            return list(schema_fields)
        missing = [field for field in schema_fields if field not in item]
        if missing:
            return missing
    return list(schema_fields)


def _distillation_error_payload(message: str) -> str:
    text = message.strip() or "Distillation failed"
    return _error_payload(
        error_type="validation_error",
        message=text,
        hint="Check the distillation parameters and retry.",
    )


_DEFAULT_MAX_BATCH_SIZE = 50
_MAX_BATCH_SIZE_ENV_VAR = "AGENTIC_MEMORY_MAX_BATCH_SIZE"
_BATCH_ITEM_ID_MISSING = object()


def _deserialize_payload(raw: str) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(raw))


def _resolve_max_batch_size() -> int:
    raw_value = os.environ.get(_MAX_BATCH_SIZE_ENV_VAR, str(_DEFAULT_MAX_BATCH_SIZE)).strip()
    try:
        parsed = int(raw_value)
    except ValueError:
        return _DEFAULT_MAX_BATCH_SIZE
    return parsed if parsed > 0 else _DEFAULT_MAX_BATCH_SIZE


def _validate_batch_input(items: Any, *, field_name: str) -> str | None:
    if not isinstance(items, list):
        return _error_payload(
            error_type="validation_error",
            message=f"`{field_name}` must be a list.",
            hint=f"Pass `{field_name}` as a non-empty list and retry.",
            exit_code=2,
        )
    if not items:
        return _error_payload(
            error_type="validation_error",
            message="Batch cannot be empty",
            hint=f"Pass at least one item in `{field_name}` and retry.",
            exit_code=2,
        )

    max_batch_size = _resolve_max_batch_size()
    if len(items) > max_batch_size:
        return _error_payload(
            error_type="validation_error",
            message=(
                f"Batch size {len(items)} exceeds maximum {max_batch_size} "
                f"(configurable via {_MAX_BATCH_SIZE_ENV_VAR})"
            ),
            hint=(
                f"Split the request into batches of at most {max_batch_size} items, "
                f"or raise `{_MAX_BATCH_SIZE_ENV_VAR}` and retry."
            ),
            exit_code=2,
        )
    return None


def _batch_item_error_result(
    index: int,
    *,
    item_id: str | None,
    message: str,
    hint: str | None,
    error_type: str = "validation_error",
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "index": index,
        "ok": False,
        "error_type": error_type,
        "message": message,
    }
    result["id"] = item_id
    if hint is not None:
        result["hint"] = hint
    return result


def _invalid_batch_entry_result(
    index: int,
    *,
    field_name: str,
    schema_fields: tuple[str, ...],
    payload: Any,
    item_id: str | None,
) -> dict[str, Any]:
    return _batch_item_error_result(
        index,
        item_id=item_id,
        message=f"Invalid `{field_name}` entry: required fields are missing or malformed.",
        hint=_required_schema_hint(field_name, schema_fields, payload),
    )


def _batch_item_result_from_payload(
    index: int,
    raw_payload: str,
    *,
    item_id: object = _BATCH_ITEM_ID_MISSING,
) -> dict[str, Any]:
    payload = _deserialize_payload(raw_payload)
    ok = bool(payload.pop("ok", True))
    payload.pop("exit_code", None)

    result: dict[str, Any] = {
        "index": index,
        "ok": ok,
    }
    if item_id is _BATCH_ITEM_ID_MISSING:
        payload_id = payload.pop("id", None)
        if payload_id is not None or not ok:
            result["id"] = payload_id
    else:
        result["id"] = item_id
        payload.pop("id", None)

    result.update(payload)
    return result


def _entry_origin(
    payload: Mapping[str, Any],
) -> Literal["memory_distillation", "autonomous_research", "user_taught"] | None:
    raw_origin = payload.get("origin")
    if raw_origin is None and "source_type" in payload:
        raw_origin = payload.get("source_type")
    return cast(
        Literal["memory_distillation", "autonomous_research", "user_taught"] | None,
        raw_origin,
    )


def _batch_success_payload(results: list[dict[str, Any]]) -> str:
    success_count = sum(1 for result in results if result["ok"])
    return _success_payload(
        {
            "success_count": success_count,
            "error_count": len(results) - success_count,
            "results": results,
        }
    )


def _require_mapping_item(
    item: Any,
    *,
    index: int,
    field_name: str,
    schema_fields: tuple[str, ...],
    item_id: str | None = None,
) -> tuple[Mapping[str, Any] | None, dict[str, Any] | None]:
    if not isinstance(item, Mapping):
        return None, _invalid_batch_entry_result(
            index,
            field_name=field_name,
            schema_fields=schema_fields,
            payload=item,
            item_id=item_id,
        )

    missing_fields = [field for field in schema_fields if field not in item]
    if missing_fields:
        return None, _invalid_batch_entry_result(
            index,
            field_name=field_name,
            schema_fields=schema_fields,
            payload=item,
            item_id=item_id,
        )
    return item, None


def _require_non_empty_string_field(
    value: Any,
    *,
    index: int,
    field_name: str,
    item_id: str | None = None,
) -> tuple[str | None, dict[str, Any] | None]:
    if not isinstance(value, str) or not value.strip():
        return None, _batch_item_error_result(
            index,
            item_id=item_id,
            message=f"Invalid `{field_name}` entry: expected a non-empty string.",
            hint=f"Pass `{field_name}` as a non-empty string.",
        )
    return value, None


def _require_batch_id(
    item: Any, *, index: int, field_name: str = "ids"
) -> tuple[str | None, dict[str, Any] | None]:
    if not isinstance(item, str) or not item.strip():
        return None, _batch_item_error_result(
            index,
            item_id=None,
            message=f"Invalid `{field_name}` entry: expected a non-empty string id.",
            hint=f"Pass `{field_name}` as a non-empty list of strings.",
        )
    return item.strip(), None


_values_service = ValuesService()
_distillation_preparer = DistillationPreparer()
_promotion_service = PromotionService()


def _resolve_paths_from_task_id(task_id: str, memory_dir: Path) -> list[Path]:
    normalized_task_id = _normalize_task_id(task_id)
    if normalized_task_id is None:
        raise ValueError(invalid_task_id_message(task_id))

    entries = load_index(_index_path(memory_dir))
    resolved_paths: list[Path] = []
    seen: set[Path] = set()
    for entry in entries:
        if _normalize_task_id(entry.task_id) != normalized_task_id:
            continue
        resolved_path = _resolve_note_path(entry.path, memory_dir)
        if resolved_path in seen:
            continue
        seen.add(resolved_path)
        resolved_paths.append(resolved_path)
    if not resolved_paths:
        raise ValueError(
            f"No notes found for task_id: {task_id!r}. "
            "Run memory_search(query='task_id:...') to inspect matches "
            "or memory_index_upsert(...) to add/update the note index."
        )
    return resolved_paths


def _memory_values_add_single(
    description: str,
    category: str,
    confidence: float = 0.3,
    evidence: list[dict[str, Any]] | None = None,
    origin: Literal["memory_distillation", "autonomous_research", "user_taught"] | None = None,
    memory_dir: str | None = None,
) -> str:
    """Add one Values entry.

    `description` and `category` are required.
    `category` is normalized to kebab-case (e.g. `"coding_style"` → `"coding-style"`).
    `confidence` defaults to 0.3.
    `origin` is the entry-level provenance classification and accepts
    `"memory_distillation"`, `"autonomous_research"`, or `"user_taught"`
    (default: `"user_taught"`).
    Promotion eligibility requires `confidence >= PromotionManager.CONFIDENCE_THRESHOLD (0.8)` and
    `evidence_count >= PromotionManager.EVIDENCE_THRESHOLD (5)`.
    `evidence` accepts a list of evidence objects with shape
    `{ref: str, summary: str, date: "YYYY-MM-DD"}`.
    `evidence[].date` must use ISO 8601 date format (`YYYY-MM-DD`).
    The newest 10 evidence objects are stored.
    Secret detection blocks the call with `error_type="validation_error"`.
    Returns `{ok: true, id, path, category}` where `category` is the normalized value,
    plus optional warnings/notifications.
    """
    resolved = _resolve_dir(memory_dir)
    secret_check = _secret_validation_error_payload(
        description,
        *[
            summary
            for item in evidence or []
            if isinstance(item, Mapping) and isinstance(summary := item.get("summary"), str)
        ],
    )
    if secret_check is not None:
        return secret_check
    try:
        entry, warnings = _values_service.add(
            resolved,
            description=description,
            category=category,
            confidence=confidence,
            evidence=evidence,
            origin=origin or "user_taught",
        )
    except (KeyError, TypeError):
        return _error_payload(
            error_type="validation_error",
            message="Invalid `evidence` entry: required fields are missing or malformed.",
            hint=_required_schema_hint(
                "evidence",
                ("ref", "summary", "date"),
                evidence,
                schema_repr='{ref, summary, date: "YYYY-MM-DD"}',
            ),
        )
    except ValueError as exc:
        if evidence is not None and "isoformat" in str(exc).lower():
            return _error_payload(
                error_type="validation_error",
                message="Invalid `evidence[].date`: value must be an ISO 8601 date (YYYY-MM-DD).",
                hint="Format each evidence `date` as YYYY-MM-DD (e.g. '2026-04-12') and retry.",
            )
        return _values_error_payload(str(exc))

    payload: dict[str, Any] = {
        "id": str(entry.id),
        "path": f"values/{entry.id}.md",
        "category": str(entry.category),
    }
    if entry.promotion_state.eligible:
        payload["promotion_candidate"] = True
    if warnings:
        payload["warnings"] = warnings
    return _success_payload(payload)


@mcp.tool(annotations=_ADDITIVE)
def memory_values_add(
    entries: list[dict[str, Any]],
    memory_dir: str | None = None,
) -> str:
    """Add one or more Values entries.

    `entries` must be a non-empty list. Each item requires `description` and `category`,
    and may also include `confidence`, `evidence`, and `origin`.
    Each item's `category` is normalized to kebab-case (e.g. `"coding_style"` → `"coding-style"`).
    Each call validates batch size against `AGENTIC_MEMORY_MAX_BATCH_SIZE` (default 50).
    `origin` is the entry-level provenance classification and accepts
    `"memory_distillation"`, `"autonomous_research"`, or `"user_taught"`.
    For backward compatibility, each batch item may also pass `source_type` as an
    alias of `origin`; if both are present, `origin` takes precedence.
    Promotion eligibility still requires
    `confidence >= PromotionManager.CONFIDENCE_THRESHOLD (0.8)` and
    `evidence_count >= PromotionManager.EVIDENCE_THRESHOLD (5)`.
    Each item's `evidence` accepts a list of evidence objects with shape
    `{ref: str, summary: str, date: "YYYY-MM-DD"}`; the newest 10 are stored.
    `evidence[].date` must use ISO 8601 date format (`YYYY-MM-DD`).
    Secret detection rejects only the affected item with `validation_error`.
    Returns `{ok, success_count, error_count, results}`. Each result includes `index`,
    per-item `ok`, and either `{id, path, category}` plus optional warnings/notifications,
    or `{error_type, message, hint}`.
    """
    validation_error = _validate_batch_input(entries, field_name="entries")
    if validation_error is not None:
        return validation_error

    results: list[dict[str, Any]] = []
    for item_index, item in enumerate(entries):
        entry, item_error = _require_mapping_item(
            item,
            index=item_index,
            field_name="entries",
            schema_fields=("description", "category"),
        )
        if item_error is not None:
            results.append(item_error)
            continue
        assert entry is not None

        description, description_error = _require_non_empty_string_field(
            entry["description"],
            index=item_index,
            field_name="entries[].description",
        )
        if description_error is not None:
            results.append(description_error)
            continue
        assert description is not None

        category, category_error = _require_non_empty_string_field(
            entry["category"],
            index=item_index,
            field_name="entries[].category",
        )
        if category_error is not None:
            results.append(category_error)
            continue
        assert category is not None

        results.append(
            _batch_item_result_from_payload(
                item_index,
                _memory_values_add_single(
                    description=description,
                    category=category,
                    confidence=cast(float, entry.get("confidence", 0.3)),
                    evidence=cast(list[dict[str, Any]] | None, entry.get("evidence")),
                    origin=_entry_origin(entry),
                    memory_dir=memory_dir,
                ),
            )
        )
    return _batch_success_payload(results)


@mcp.tool(annotations=_READONLY)
def memory_values_search(
    query: str | None = None,
    category: str | None = None,
    min_confidence: float = 0.0,
    top: int = 5,
    no_cjk_expand: bool = False,
    include_full_content: bool = False,
    memory_dir: str | None = None,
) -> str:
    """Search Values entries by query and/or category.

    At least one of `query` or `category` is required.
    `category` is normalized to kebab-case (e.g. `"coding_style"` → `"coding-style"`).
    CJK query expansion is enabled by default; set `no_cjk_expand=true` to suppress
    n-gram expansion for Japanese/Chinese/Korean search terms.
    Results include score, confidence, evidence count, and promotion state.
    Set `include_full_content=true` to also return evidence, origin, and timestamps.
    """
    resolved = _resolve_dir(memory_dir)
    try:
        results = _values_service.search(
            resolved,
            query=query,
            category=category,
            min_confidence=min_confidence,
            top=top,
            no_cjk_expand=no_cjk_expand,
        )
    except ValueError as exc:
        return _validation_error_payload(
            str(exc),
            default_hint="Pass 'query', 'category', or both, and verify filter values.",
        )

    return _success_payload(
        {
            "entries": [
                _values_entry_payload(
                    entry,
                    score=score,
                    include_full_content=include_full_content,
                )
                for score, entry in results
            ]
        }
    )


def _memory_values_update_single(
    id: str,
    confidence: float | None = None,
    add_evidence: list[dict[str, Any]] | None = None,
    description: str | None = None,
    memory_dir: str | None = None,
) -> str:
    """Update one Values entry.

    At least one of `confidence`, `add_evidence`, or `description` must be provided.
    Promotion eligibility requires `confidence >= PromotionManager.CONFIDENCE_THRESHOLD (0.8)` and
    `evidence_count >= PromotionManager.EVIDENCE_THRESHOLD (5)`.
    `add_evidence` accepts a list of evidence objects, each with shape
    `{ref: str, summary: str, date: "YYYY-MM-DD"}`.
    Returns the updated ID plus `updated_fields`. Includes `promotion_candidate: true`
    when the entry becomes eligible for promotion, or `demotion_candidate: true` when
    a promoted entry's confidence drops. Includes `warnings` for secret detection.
    """
    resolved = _resolve_dir(memory_dir)
    updated_fields = [
        name
        for name, value in [
            ("confidence", confidence),
            ("evidence", add_evidence),
            ("description", description),
        ]
        if value is not None
    ]
    try:
        entry, notifications = _values_service.update(
            resolved,
            id=id,
            confidence=confidence,
            add_evidence=add_evidence,
            description=description,
        )
    except KeyError:
        return _error_payload(
            error_type="validation_error",
            message="Invalid `add_evidence` entry: required fields are missing or malformed.",
            hint=_required_schema_hint(
                "add_evidence",
                ("ref", "summary", "date"),
                add_evidence,
                schema_repr='{ref, summary, date: "YYYY-MM-DD"}',
            ),
        )
    except TypeError as exc:
        if str(exc) == "`add_evidence` must be a list of evidence objects.":
            return _values_error_payload(str(exc))
        return _error_payload(
            error_type="validation_error",
            message="Invalid `add_evidence` entry: required fields are missing or malformed.",
            hint=_required_schema_hint(
                "add_evidence",
                ("ref", "summary", "date"),
                add_evidence,
                schema_repr='{ref, summary, date: "YYYY-MM-DD"}',
            ),
        )
    except FileNotFoundError as exc:
        return _values_error_payload(str(exc))
    except ValueError as exc:
        if add_evidence is not None and "isoformat" in str(exc).lower():
            return _error_payload(
                error_type="validation_error",
                message=(
                    "Invalid `add_evidence[].date`: value must be an ISO 8601 date (YYYY-MM-DD)."
                ),
                hint="Format each evidence `date` as YYYY-MM-DD (e.g. '2026-04-12') and retry.",
            )
        return _values_error_payload(str(exc))

    payload: dict[str, Any] = {"id": str(entry.id), "updated_fields": updated_fields}
    secret_warnings = notifications.pop("secret_warnings", [])
    if secret_warnings:
        payload["warnings"] = secret_warnings
    payload.update(notifications)
    return _success_payload(payload)


@mcp.tool(annotations=_IDEMPOTENT)
def memory_values_update(
    updates: list[dict[str, Any]],
    memory_dir: str | None = None,
) -> str:
    """Update one or more Values entries.

    `updates` must be a non-empty list. Each item requires `id` and may include
    `confidence`, `add_evidence`, and/or `description`.
    Each call validates batch size against `AGENTIC_MEMORY_MAX_BATCH_SIZE` (default 50).
    `add_evidence` still accepts a list of evidence objects with shape
    `{ref: str, summary: str, date: "YYYY-MM-DD"}`.
    Returns `{ok, success_count, error_count, results}`. Each result includes `index`,
    `id`, per-item `ok`, and either update notifications or `{error_type, message, hint}`.
    """
    validation_error = _validate_batch_input(updates, field_name="updates")
    if validation_error is not None:
        return validation_error

    results: list[dict[str, Any]] = []
    for item_index, item in enumerate(updates):
        update, item_error = _require_mapping_item(
            item,
            index=item_index,
            field_name="updates",
            schema_fields=("id",),
        )
        if item_error is not None:
            results.append(item_error)
            continue
        assert update is not None

        item_id, id_error = _require_batch_id(
            update["id"],
            index=item_index,
            field_name="updates[].id",
        )
        if id_error is not None:
            results.append(id_error)
            continue
        assert item_id is not None

        results.append(
            _batch_item_result_from_payload(
                item_index,
                _memory_values_update_single(
                    id=item_id,
                    confidence=cast(float | None, update.get("confidence")),
                    add_evidence=cast(list[dict[str, Any]] | None, update.get("add_evidence")),
                    description=cast(str | None, update.get("description")),
                    memory_dir=memory_dir,
                ),
                item_id=item_id,
            )
        )
    return _batch_success_payload(results)


@mcp.tool(annotations=_READONLY)
def memory_values_list(
    min_confidence: float = 0.0,
    category: str | None = None,
    promoted_only: bool = False,
    top: int = 20,
    memory_dir: str | None = None,
) -> str:
    """List Values entries with optional filters.

    `min_confidence` defaults to 0.0.
    `category` is normalized to kebab-case (e.g. `"coding_style"` → `"coding-style"`).
    Results are sorted by confidence descending, with `updated_at` as the tiebreaker.
    """
    resolved = _resolve_dir(memory_dir)
    try:
        entries = _values_service.list_values(
            resolved,
            min_confidence=min_confidence,
            category=category,
            promoted_only=promoted_only,
            top=top,
        )
    except ValueError as exc:
        return _values_error_payload(str(exc))

    return _success_payload({"entries": [_values_entry_payload(entry) for entry in entries]})


@mcp.tool(annotations=_READONLY)
def memory_distill_prepare(
    type: Literal["knowledge", "values"],
    date_from: str | None = None,
    date_to: str | None = None,
    domain: str | None = None,
    category: str | None = None,
    memory_dir: str | None = None,
) -> str:
    """Prepare distillation materials for the calling agent.

    Returns notes, existing items, extraction instructions, and the candidate
    schema.  The calling agent (LLM) performs the actual extraction, then
    submits candidates via `memory_distill_commit`.

    `type` selects knowledge or values distillation.
    `date_from` / `date_to` accept `YYYY-MM-DD` (inclusive).
    `domain` (knowledge) or `category` (values) narrows the scope.
    """
    resolved = _resolve_dir(memory_dir)
    try:
        if type == "knowledge":
            result = _distillation_preparer.prepare_knowledge(
                resolved, date_from=date_from, date_to=date_to, domain=domain
            )
        else:
            result = _distillation_preparer.prepare_values(
                resolved, date_from=date_from, date_to=date_to, category=category
            )
    except (FileNotFoundError, ValueError) as exc:
        return _distillation_error_payload(str(exc))
    except OSError as exc:
        return _error_payload(
            error_type="io_error",
            message=str(exc),
            hint="Check filesystem permissions and retry.",
        )

    payload: dict[str, Any] = {
        "notes": result.notes,
        "existing_items": result.existing_items,
        "instructions": result.instructions,
        "candidate_schema": result.candidate_schema,
    }
    if result.decisions is not None:
        payload["decisions"] = result.decisions
    return _success_payload(payload)


@mcp.tool(annotations=_ADDITIVE)
def memory_distill_commit(
    type: Literal["knowledge", "values"],
    candidates: list[dict[str, Any]],
    dry_run: bool = False,
    memory_dir: str | None = None,
) -> str:
    """Commit distillation candidates extracted by the calling agent.

    Validates, deduplicates, and persists knowledge or values entries.
    `origin` is automatically set to `memory_distillation`.

    `type` selects knowledge or values.
    `candidates` is an array matching the schema from `memory_distill_prepare`.
    `dry_run=true` validates without persisting.
    """
    resolved = _resolve_dir(memory_dir)
    try:
        if type == "knowledge":
            return _commit_knowledge(resolved, candidates, dry_run=dry_run)
        return _commit_values(resolved, candidates, dry_run=dry_run)
    except (FileNotFoundError, ValueError) as exc:
        return _distillation_error_payload(str(exc))
    except OSError as exc:
        return _error_payload(
            error_type="io_error",
            message=str(exc),
            hint="Check filesystem permissions and retry.",
        )


def _commit_knowledge(
    memory_dir: Path,
    candidates: list[dict[str, Any]],
    *,
    dry_run: bool,
) -> str:
    from agentic_memory.core.knowledge.model import (
        KnowledgeEntry,
        UserUnderstanding,
    )
    from agentic_memory.core.knowledge.repository import KnowledgeRepository

    knowledge_service = KnowledgeService()
    created: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    warnings: list[str] = []

    for i, candidate in enumerate(candidates):
        title = str(candidate.get("title", "")).strip()
        content = str(candidate.get("content", "")).strip()
        domain = str(candidate.get("domain", "")).strip()
        if not title or not content or not domain:
            skipped.append(
                {
                    "index": i,
                    "reason": "Missing required field(s): title, content, domain",
                }
            )
            continue

        # Coerce optional fields up-front so dry_run and live share validation
        try:
            accuracy = Accuracy(candidate.get("accuracy", "uncertain"))
        except ValueError as exc:
            skipped.append({"index": i, "title": title, "reason": str(exc)})
            continue
        try:
            user_understanding = UserUnderstanding(candidate.get("user_understanding", "unknown"))
        except ValueError as exc:
            skipped.append({"index": i, "title": title, "reason": str(exc)})
            continue

        sources_raw: list[Source | dict[str, Any]] = candidate.get("sources") or []
        related_raw: list[str] | None = candidate.get("related")

        if SecretScanPolicy.contains_secret(content):
            warnings.append(
                f"Candidate {i} ({title}): content may contain secrets. Review before sharing."
            )

        if dry_run:
            # Validate without persisting or mutating existing data.
            # Replicate the same checks KnowledgeService.add performs:
            # 1. Build entry object (field validation)
            # 2. Normalize/validate related IDs
            # 3. Check duplicates against existing entries
            try:
                coerced_sources = KnowledgeService._coerce_sources(sources_raw or None)
                related_ids = KnowledgeService._normalize_related(related_raw)
                # Verify referenced entries exist
                repository = KnowledgeRepository(memory_dir)
                for rid in related_ids:
                    if repository.find_by_id(rid) is None:
                        raise FileNotFoundError(f"Knowledge entry not found: {rid}")
                entry_obj = KnowledgeEntry(
                    title=title,
                    content=content,
                    domain=domain,
                    tags=candidate.get("tags") or [],
                    accuracy=accuracy,
                    sources=coerced_sources,
                    origin=SourceType.MEMORY_DISTILLATION,
                    user_understanding=user_understanding,
                    related=[str(r) for r in related_ids],
                )
                knowledge_service._ensure_no_duplicate(repository.list_all(), candidate=entry_obj)
            except DuplicateKnowledgeError:
                skipped.append({"index": i, "title": title, "reason": "duplicate"})
                continue
            except (ValueError, FileNotFoundError) as exc:
                skipped.append({"index": i, "title": title, "reason": str(exc)})
                continue
            warnings.extend(knowledge_service._secret_warnings(content))
            created.append({"index": i, "title": title, "dry_run": True})
            continue

        try:
            entry = knowledge_service.add(
                memory_dir,
                title=title,
                content=content,
                domain=domain,
                tags=candidate.get("tags") or [],
                accuracy=accuracy,
                sources=sources_raw or None,
                origin=SourceType.MEMORY_DISTILLATION,
                user_understanding=user_understanding,
                related=related_raw,
            )
        except DuplicateKnowledgeError:
            skipped.append({"index": i, "title": title, "reason": "duplicate"})
            continue
        except (ValueError, FileNotFoundError) as exc:
            skipped.append({"index": i, "title": title, "reason": str(exc)})
            continue

        warnings.extend(knowledge_service.last_warnings)
        created.append({"index": i, "id": str(entry.id), "title": title})

    if not dry_run:
        now_str = _dt.datetime.now().replace(microsecond=0).isoformat(timespec="seconds")
        updates: dict[str, str] = {"last_knowledge_evaluated_at": now_str}
        if created:
            updates["last_knowledge_distilled_at"] = now_str
        state.update_distillation_frontmatter(memory_dir / "_state.md", **updates)

    payload: dict[str, Any] = {
        "created": created,
        "skipped": skipped,
    }
    if warnings:
        payload["warnings"] = warnings
    return _success_payload(payload)


def _commit_values(
    memory_dir: Path,
    candidates: list[dict[str, Any]],
    *,
    dry_run: bool,
) -> str:
    from agentic_memory.core.values.model import Evidence as EvidenceModel

    values_service = ValuesService()
    created: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    warnings: list[str] = []

    for i, candidate in enumerate(candidates):
        description = str(candidate.get("description", "")).strip()
        category_raw = str(candidate.get("category", "")).strip()
        if not description or not category_raw:
            skipped.append(
                {
                    "index": i,
                    "reason": "Missing required field(s): description, category",
                }
            )
            continue

        if SecretScanPolicy.contains_secret(description):
            warnings.append(
                f"Candidate {i} ({description[:60]}): description may contain secrets. "
                "Review before sharing."
            )

        confidence = float(candidate.get("confidence", 0.3))
        evidence_raw = candidate.get("evidence") or []
        evidence_items: list[EvidenceModel] = []
        for j, ev in enumerate(evidence_raw):
            try:
                evidence_items.append(EvidenceModel.from_dict(ev))
            except (KeyError, TypeError, ValueError) as exc:
                skipped.append(
                    {
                        "index": i,
                        "description": description[:80],
                        "reason": f"Malformed evidence[{j}]: {exc}",
                    }
                )
                break
        else:
            # Evidence parsing succeeded — proceed to add
            pass
        if any(s.get("index") == i for s in skipped):
            continue

        if dry_run:
            # Validate without persisting: replicate ValuesService.add checks
            # without calling save.
            try:
                normalized_description = ValuesService._normalize_description(description)
                from agentic_memory.core.values.model import Category

                normalized_category = Category.normalize(category_raw)
                from agentic_memory.core.values.repository import ValuesRepository

                existing = ValuesRepository(memory_dir).list_all()
                values_service._ensure_not_duplicate(
                    existing,
                    description=normalized_description,
                    category=normalized_category,
                )
                # Construct entry to validate confidence/evidence fields
                from agentic_memory.core.values.model import ValuesEntry, ValuesId

                ValuesEntry(
                    id=ValuesId.generate(),
                    description=normalized_description,
                    category=normalized_category,
                    confidence=confidence,
                    evidence=evidence_items[:10],
                    total_evidence_count=len(evidence_items),
                    origin=SourceType.MEMORY_DISTILLATION,
                )
            except ValueError as exc:
                exc_msg = str(exc)
                reason = "duplicate" if "Duplicate value exists" in exc_msg else exc_msg
                skipped.append({"index": i, "description": description[:80], "reason": reason})
                continue
            created.append({"index": i, "description": description[:80], "dry_run": True})
            continue

        try:
            entry, entry_warnings = values_service.add(
                memory_dir,
                description=description,
                category=category_raw,
                confidence=confidence,
                evidence=evidence_items or None,
                origin=SourceType.MEMORY_DISTILLATION,
            )
        except ValueError as exc:
            exc_msg = str(exc)
            reason = "duplicate" if "Duplicate value exists" in exc_msg else exc_msg
            skipped.append({"index": i, "description": description[:80], "reason": reason})
            continue

        warnings.extend(entry_warnings)
        created.append(
            {
                "index": i,
                "id": str(entry.id),
                "description": description[:80],
            }
        )

    if not dry_run:
        now_str = _dt.datetime.now().replace(microsecond=0).isoformat(timespec="seconds")
        updates: dict[str, str] = {"last_values_evaluated_at": now_str}
        if created:
            updates["last_values_distilled_at"] = now_str
        state.update_distillation_frontmatter(memory_dir / "_state.md", **updates)

    payload: dict[str, Any] = {
        "created": created,
        "skipped": skipped,
    }
    if warnings:
        payload["warnings"] = warnings
    return _success_payload(payload)


def _memory_values_promote_single(
    id: str,
    confirm: bool = False,
    memory_dir: str | None = None,
) -> str:
    """Promote one Values entry into AGENTS.md.

    Promotion eligibility requires `confidence >= PromotionManager.CONFIDENCE_THRESHOLD (0.8)` and
    `evidence_count >= PromotionManager.EVIDENCE_THRESHOLD (5)`.
    `confirm=true` is required for the actual promotion.
    `confirm=false` returns a preview without making changes.
    """
    resolved = _resolve_dir(memory_dir)
    try:
        payload = _promotion_service.promote(
            resolved,
            id=id,
            confirm=confirm,
        )
    except (FileNotFoundError, ValueError) as exc:
        return _values_error_payload(str(exc))
    return _success_payload(payload)


@mcp.tool(annotations=_DESTRUCTIVE)
def memory_values_promote(
    ids: list[str],
    confirm: bool = False,
    memory_dir: str | None = None,
) -> str:
    """Promote one or more Values entries into AGENTS.md.

    `ids` must be a non-empty list. `confirm` is shared across the whole batch:
    `confirm=false` returns per-item previews without side effects, and `confirm=true`
    performs the promotion. Each call validates batch size against
    `AGENTIC_MEMORY_MAX_BATCH_SIZE` (default 50).
    Returns `{ok, success_count, error_count, results}`. Each result includes `index`,
    `id`, per-item `ok`, and either promotion metadata / `would_promote`, or
    `{error_type, message, hint}`.
    """
    validation_error = _validate_batch_input(ids, field_name="ids")
    if validation_error is not None:
        return validation_error

    results: list[dict[str, Any]] = []
    for item_index, item in enumerate(ids):
        item_id, id_error = _require_batch_id(item, index=item_index)
        if id_error is not None:
            results.append(id_error)
            continue
        assert item_id is not None

        results.append(
            _batch_item_result_from_payload(
                item_index,
                _memory_values_promote_single(
                    id=item_id,
                    confirm=confirm,
                    memory_dir=memory_dir,
                ),
                item_id=item_id,
            )
        )
    return _batch_success_payload(results)


def _memory_values_demote_single(
    id: str,
    reason: str,
    confirm: bool = False,
    memory_dir: str | None = None,
) -> str:
    """Demote one promoted Values entry from AGENTS.md.

    `confirm=true` is required for the actual demotion.
    `confirm=false` returns a preview without making changes.
    """
    resolved = _resolve_dir(memory_dir)
    try:
        payload = _promotion_service.demote(
            resolved,
            id=id,
            reason=reason,
            confirm=confirm,
        )
    except (FileNotFoundError, ValueError) as exc:
        return _values_error_payload(str(exc))
    return _success_payload(payload)


@mcp.tool(annotations=_DESTRUCTIVE)
def memory_values_demote(
    ids: list[str],
    reason: str,
    confirm: bool = False,
    memory_dir: str | None = None,
) -> str:
    """Demote one or more promoted Values entries from AGENTS.md.

    `ids` must be a non-empty list. `reason` and `confirm` are shared across the batch.
    `confirm=false` returns per-item previews without side effects, and `confirm=true`
    performs the demotion. Each call validates batch size against
    `AGENTIC_MEMORY_MAX_BATCH_SIZE` (default 50).
    Returns `{ok, success_count, error_count, results}`. Each result includes `index`,
    `id`, per-item `ok`, and either demotion metadata / `would_demote`, or
    `{error_type, message, hint}`.
    """
    validation_error = _validate_batch_input(ids, field_name="ids")
    if validation_error is not None:
        return validation_error

    results: list[dict[str, Any]] = []
    for item_index, item in enumerate(ids):
        item_id, id_error = _require_batch_id(item, index=item_index)
        if id_error is not None:
            results.append(id_error)
            continue
        assert item_id is not None

        results.append(
            _batch_item_result_from_payload(
                item_index,
                _memory_values_demote_single(
                    id=item_id,
                    reason=reason,
                    confirm=confirm,
                    memory_dir=memory_dir,
                ),
                item_id=item_id,
            )
        )
    return _batch_success_payload(results)


def _memory_values_delete_single(
    id: str,
    confirm: bool = False,
    reason: str | None = None,
    memory_dir: str | None = None,
) -> str:
    """Delete one Values entry.

    `confirm=false` always returns a preview. `confirm=true` performs the actual
    deletion, including AGENTS.md cleanup for promoted entries.
    """
    resolved = _resolve_dir(memory_dir)
    try:
        payload = _values_service.delete(
            resolved,
            id=id,
            confirm=confirm,
            reason=reason,
        )
    except FileNotFoundError as exc:
        return _values_error_payload(str(exc))
    except ValueError as exc:
        message = str(exc)
        if (
            message == "AGENTS.md is missing promoted values markers. "
            "Run memory_init to recreate them."
        ):
            return _error_payload(
                error_type="validation_error",
                message=message,
                hint="Run `memory_init` to recreate AGENTS.md markers, then retry deletion.",
            )
        return _values_error_payload(message)
    return _success_payload(payload)


@mcp.tool(annotations=_DESTRUCTIVE)
def memory_values_delete(
    ids: list[str],
    confirm: bool = False,
    reason: str | None = None,
    memory_dir: str | None = None,
) -> str:
    """Delete one or more Values entries.

    `ids` must be a non-empty list. `confirm` and optional `reason` are shared across
    the batch. `confirm=false` returns per-item previews without deleting anything, and
    `confirm=true` performs deletion plus AGENTS.md cleanup for promoted entries.
    Each call validates batch size against `AGENTIC_MEMORY_MAX_BATCH_SIZE` (default 50).
    Returns `{ok, success_count, error_count, results}`. Each result includes `index`,
    `id`, per-item `ok`, and either deletion metadata / `would_delete`, or
    `{error_type, message, hint}`.
    """
    validation_error = _validate_batch_input(ids, field_name="ids")
    if validation_error is not None:
        return validation_error

    results: list[dict[str, Any]] = []
    for item_index, item in enumerate(ids):
        item_id, id_error = _require_batch_id(item, index=item_index)
        if id_error is not None:
            results.append(id_error)
            continue
        assert item_id is not None

        results.append(
            _batch_item_result_from_payload(
                item_index,
                _memory_values_delete_single(
                    id=item_id,
                    confirm=confirm,
                    reason=reason,
                    memory_dir=memory_dir,
                ),
                item_id=item_id,
            )
        )
    return _batch_success_payload(results)


@mcp.tool(annotations=_IDEMPOTENT)
def memory_init(
    memory_dir: str | None = None,
    enable_dense: bool = False,
) -> str:
    """Initialize memory directory files.

    Creates `_state.md`, `_index.jsonl`, and `_rag_config.json` when missing.
    Use this before any other memory tool when starting with a new memory directory.
    Already-initialized directories are left unchanged (idempotent).
    `enable_dense` configures dense (semantic) retrieval in `_rag_config.json`.
    `memory_dir` selects the target root directory.
    Returns initialization status and generated paths as JSON.
    """
    resolved = _resolve_dir(memory_dir)
    result = config.init_memory_dir(resolved, enable_dense=enable_dense)
    return _success_payload(result)


@mcp.tool(annotations=_ADDITIVE)
def memory_note_new(
    title: str,
    context: str | None = None,
    tags: str | None = None,
    keywords: str | None = None,
    task_id: str | None = None,
    agent_id: str | None = None,
    relay_session_id: str | None = None,
    lang: Literal["ja", "en"] = "ja",
    memory_dir: str | None = None,
) -> str:
    """Create a new session note from template.

    Use this at the start of a work session to create a note for logging.
    Do not use for updating existing notes — edit the note file directly instead.
    `title` is required. Optional `context`, `tags`, and `keywords` fill metadata fields.
    `task_id`, `agent_id`, and `relay_session_id` are stored in index metadata.
    `task_id` accepts `TASK-123` / `GOAL-123` or a relay task UUID.
    The created note is indexed immediately after it is written.
    If indexing fails, the created note is rolled back before returning an error.
    `lang` selects the template language.
    Returns JSON with the created note path and metadata.
    """
    resolved = _resolve_dir(memory_dir)
    if task_id is not None and _normalize_task_id(task_id) is None:
        return _index_upsert_error_payload(invalid_task_id_message(task_id))
    created = note.create_note(
        memory_dir=resolved,
        title=title,
        context=context,
        tags=tags,
        keywords=keywords,
        auto_index=False,
        lang=lang,
    )
    try:
        index.index_note(
            note_path=created,
            index_path=_index_path(resolved),
            dailynote_dir=resolved,
            task_id=task_id,
            agent_id=agent_id,
            relay_session_id=relay_session_id,
            no_dense=True,
        )
    except ValueError as exc:
        message = str(exc)
        return _rollback_indexing_failure(
            created,
            resolved,
            payload_factory=lambda: _index_upsert_error_payload(message),
            original_message=message,
        )
    except OSError as exc:
        message = str(exc)
        return _rollback_indexing_failure(
            created,
            resolved,
            payload_factory=lambda: _error_payload(
                error_type="io_error",
                message=message,
                hint="Check filesystem permissions and retry.",
            ),
            original_message=message,
        )
    return _success_payload(
        {"path": str(created), "title": title, "date": str(created.parent.name)}
    )


@mcp.tool(annotations=_READONLY)
def memory_state_show(
    section: str | None = None,
    stale_days: int = 0,
    as_json: bool = True,
    memory_dir: str | None = None,
) -> str:
    """Show rolling state sections.

    Use this to check current focus, open actions, decisions, and pitfalls.
    `section` filters one state section, `stale_days` marks stale items.
    `as_json` defaults to True (structured sections only). Set to False
    to return rendered markdown under `output` instead of structured `sections`.
    `memory_dir` selects the state file location.
    Returns JSON.
    """
    resolved = _resolve_dir(memory_dir)
    structured_output = _capture_state_cmd(
        state.cmd_show,
        _state_path(resolved),
        section=section,
        stale_days=stale_days,
        as_json=True,
    )
    try:
        parsed = json.loads(structured_output)
    except json.JSONDecodeError:
        return structured_output
    if isinstance(parsed, dict) and parsed.get("ok") is False:
        return _serialize_json(parsed)

    payload: dict[str, Any] = {
        "ok": True,
        "section": section,
        "stale_days": stale_days,
        "sections": parsed.get("sections", {}) if isinstance(parsed, dict) else parsed,
        "frontmatter": (
            parsed.get("frontmatter", state.load_state_frontmatter(_state_path(resolved)))
            if isinstance(parsed, dict)
            else state.load_state_frontmatter(_state_path(resolved))
        ),
    }
    if isinstance(parsed, dict) and "warnings" in parsed:
        payload["warnings"] = parsed["warnings"]
    if not as_json:
        sections_payload = cast(dict[str, Any], payload.pop("sections", {}))
        frontmatter_payload = cast(dict[str, Any], payload.pop("frontmatter", {}))
        payload["output"] = _render_state_show_output(
            sections_payload,
            frontmatter=frontmatter_payload,
        )
    return _success_payload(payload)


@mcp.tool(annotations=_ADDITIVE)
def memory_state_add(
    section: str,
    items: list[str],
    replace: list[str] | str | None = None,
    memory_dir: str | None = None,
) -> str:
    """Add items to a state section with optional pattern-based replacement.

    Use this for incremental state updates. For full section replacement, use memory_state_set.
    `section` is the target state section key/name. Common aliases like `open_actions`
    and `current_focus` are also accepted.
    `items` is a list of new bullet items to prepend and de-duplicate.
    `replace` is an optional list of substring patterns (e.g., `["old item", "pattern"]`);
    existing items matching any pattern are removed before adding new items
    (upsert semantics: remove old + add new in one step).
    A single string is also accepted and treated as a one-item list.
    The response always includes `dropped_by_cap` (int) and `dropped_items` (list[str]);
    they are `0` / `[]` when the section cap is not exceeded. When the cap is exceeded,
    `enforce_cap` trims from the tail (oldest existing entries) after new items are
    prepended, so `after` is the authoritative count of items actually persisted and
    `dropped_items` reveals which existing entries were evicted. `added` remains the
    count of items the user attempted to insert and is not reduced by cap trimming.
    Returns command output including updated state path.
    """
    resolved = _resolve_dir(memory_dir)
    return _capture_state_cmd(
        state.cmd_add,
        _state_path(resolved),
        section=section,
        items=items,
        replace=replace,
    )


@mcp.tool(annotations=_IDEMPOTENT)
def memory_state_set(
    section: str,
    items: list[str],
    memory_dir: str | None = None,
) -> str:
    """Low-level: replace a state section directly.

    Prefer memory_state_from_note for note-driven updates.
    `section` is the target state section key/name.
    `items` fully replace existing entries in that section.
    Returns command output including updated state path.
    """
    resolved = _resolve_dir(memory_dir)
    return _capture_state_cmd(
        state.cmd_set,
        _state_path(resolved),
        section=section,
        items=items,
    )


@mcp.tool(annotations=_DESTRUCTIVE)
def memory_state_remove(
    section: str,
    pattern: str,
    regex: bool = False,
    memory_dir: str | None = None,
) -> str:
    """Low-level: remove items from a state section directly.

    Prefer memory_state_from_note for note-driven updates.
    `section` is the target section.
    `pattern` is a substring by default, or regular expression when `regex=True`.
    Returns command output including number of removed items.
    """
    resolved = _resolve_dir(memory_dir)
    return _capture_state_cmd(
        state.cmd_remove,
        _state_path(resolved),
        section=section,
        pattern=pattern,
        regex=regex,
    )


@mcp.tool(annotations=_DESTRUCTIVE)
def memory_state_from_note(
    note_path: str,
    auto_improve_mode: Literal["detect", "add", "skip"] = "detect",
    max_entries: int = 20,
    memory_dir: str | None = None,
) -> str:
    """Update rolling state using a note file.

    `note_path` points to the source note.
    After merging note sections into rolling state, SIGFB signals in the note are
    analyzed to detect improvement candidates for the backlog.
    `auto_improve_mode`: `detect` reports candidates only, `add` appends them
    to the improvement backlog, and `skip` disables analysis entirely.
    When legacy `_improvement_backlog_resolved.json` entries are present, this path also
    migrates them into the 0.7.x sidecars and reports a migration summary in the response.
    `max_entries` limits section lengths after merge.
    Returns JSON with `updated_sections`, `section_counts`, `stale_count`,
    `auto_improve`, and optional structured `cap_exceeded` / `auto_pruned` details.
    """
    resolved = _resolve_dir(memory_dir)
    resolved_note = _resolve_note_path(note_path, resolved)
    return _capture_state_cmd(
        state.cmd_from_note,
        _state_path(resolved),
        note_path=resolved_note,
        auto_improve_mode=auto_improve_mode,
        max_entries=max_entries,
    )


@mcp.tool(annotations=_READONLY)
def memory_auto_restore(
    agent_id: str | None = None,
    relay_session_id: str | None = None,
    max_evidence_notes: int = 3,
    max_lines: int = 6,
    max_total_lines: int = 200,
    include_project_state: bool = True,
    include_agent_state: bool = True,
    memory_dir: str | None = None,
) -> str:
    """Restore active context by combining state_show + related note evidence in one call.

    `max_total_lines` caps total response size.
    Priority: project_state > agent_state > evidence.
    When truncated, `truncated` and `truncated_reason` are included in the response.
    Convenience wrapper for session recovery.
    Returns JSON with fields: `agent_id`, `relay_session_id`, `project_state`
    (dict with focus/open/decisions/pitfalls/skills/improvements lists),
    `agent_state` (same structure, or null), `agent_state_path`, `active_tasks`
    (list of {task_id, related_notes, evidence_pack}), `restored_task_count`,
    `total_notes_referenced`, `warnings`, `restored_at`.
    """
    resolved = _resolve_dir(memory_dir)
    payload = state.auto_restore(
        memory_dir=resolved,
        agent_id=agent_id,
        relay_session_id=relay_session_id,
        max_evidence_notes=max_evidence_notes,
        max_lines=max_lines,
        max_total_lines=max_total_lines,
        include_project_state=include_project_state,
        include_agent_state=include_agent_state,
    )
    return _success_payload(payload)


@mcp.tool(annotations=_READONLY_OPEN_WORLD)
def memory_search(
    query: str,
    mode: Literal["quick", "detailed", "debug"] = "quick",
    task_id: str | None = None,
    agent_id: str | None = None,
    relay_session_id: str | None = None,
    top: int | None = None,
    snippets: int | None = None,
    engine: Literal["auto", "index", "hybrid", "rg", "python"] = "auto",
    prefer_recent: bool = False,
    half_life_days: float | None = None,
    suggest: bool = False,
    no_expand: bool = False,
    no_fuzzy: bool = False,
    no_cjk_expand: bool = False,
    no_rerank: bool = False,
    sync_stale_index: bool = False,
    default_date_range: int | None = None,
    memory_dir: str | None = None,
) -> str:
    """Search session notes by query.

    Use this to find past session notes by keywords, tags, or metadata.
    Do not use for full-text reading of a specific note — use memory_evidence instead.
    Supports quoted phrases, +must, -exclude, field:term (with aliases like tag:),
    and date-range filters.
    `task_id`, `agent_id`, and `relay_session_id` can be passed either as explicit
    parameters or as query filters such as `task_id:TASK-123`.
    `task_id` accepts `TASK-123` / `GOAL-123` or a relay task UUID.
    `mode` controls output verbosity and sets search defaults:
      - `quick` (default): compact output, strips verbose fields and settings echo-back.
        Sets: compact=True, no_feedback_expand=True.
      - `detailed`: full metadata except auto_keywords and work_log_keywords.
        Sets: compact=False, no_feedback_expand=False.
      - `debug`: all fields + scoring explanation (explain_summary, expanded QueryTerm objects).
        Sets: compact=False, no_feedback_expand=False, explain=True.
    `no_expand`, `no_cjk_expand`, `no_fuzzy`, `no_rerank` override individual features
    regardless of mode — use these only when mode presets are insufficient.
    When rerank auto-enables, lazy-loading the rerank model may trigger a model
    download via `sentence_transformers`.
    Returns ranked results, warnings, and match metadata as JSON.
    """
    # Derive compact/explain/no_feedback_expand from mode
    compact = mode == "quick"
    explain = mode == "debug"
    no_feedback_expand = mode == "quick"

    resolved = _resolve_dir(memory_dir)
    result = search.search(
        query=query,
        memory_dir=resolved,
        task_id=task_id,
        agent_id=agent_id,
        relay_session_id=relay_session_id,
        engine=engine,
        top=top,
        snippets=snippets,
        prefer_recent=prefer_recent,
        half_life_days=half_life_days,
        explain=explain,
        suggest=suggest,
        no_expand=no_expand,
        no_feedback_expand=no_feedback_expand,
        no_fuzzy=no_fuzzy,
        no_cjk_expand=no_cjk_expand,
        sync_stale_index=sync_stale_index,
        use_rerank=False,
        no_use_rerank=no_rerank,
        prf=False,
        no_prf=False,
        default_date_range=default_date_range,
        compact=compact,
    )
    if compact:
        result = _strip_compact_fields(result)
    elif mode == "detailed":
        result = _strip_detailed_fields(result)
    else:
        result = _strip_debug_fields(result)
    # Strip verbose expanded QueryTerm objects unless debug mode
    if mode != "debug":
        result = dict(result)
        result.pop("expanded", None)
    return _success_payload(result)


@mcp.tool(annotations=_IDEMPOTENT)
def memory_index_upsert(
    note_path: str,
    task_id: str | None = None,
    agent_id: str | None = None,
    relay_session_id: str | None = None,
    max_summary_chars: int = 280,
    no_dense: bool = False,
    compact: bool = False,
    memory_dir: str | None = None,
) -> str:
    """Upsert one note into the index.

    Use this to add or refresh one note in the index. It is also useful after
    schema changes or upgrades when an older index entry needs to be rebuilt.
    `note_path` targets the note to index.
    `max_summary_chars` truncates summary extraction, and `no_dense` skips dense upsert.
    `compact` omits verbose fields (auto_keywords, work_log_keywords, etc.) from the response.
    Returns the indexed entry as JSON.
    """
    resolved = _resolve_dir(memory_dir)
    resolved_note = _resolve_note_path(note_path, resolved)
    try:
        result = index.index_note(
            note_path=resolved_note,
            index_path=_index_path(resolved),
            dailynote_dir=resolved,
            task_id=task_id,
            agent_id=agent_id,
            relay_session_id=relay_session_id,
            max_summary_chars=max_summary_chars,
            no_dense=no_dense,
        )
    except FileNotFoundError as exc:
        return _error_payload(
            error_type="not_found",
            message=str(exc),
            hint="Verify `note_path` exists. Use `memory_note_new` to create a note first.",
        )
    except ValueError as exc:
        return _index_upsert_error_payload(str(exc))
    except OSError as exc:
        return _error_payload(
            error_type="io_error",
            message=str(exc),
            hint="Check filesystem permissions and retry.",
        )
    if compact:
        exclude = search.COMPACT_EXCLUDE_FIELDS
        result = {key: value for key, value in result.items() if key not in exclude}
    return _success_payload(result)


@mcp.tool(annotations=_READONLY)
def memory_evidence(
    query: str,
    paths: list[str] | str | None = None,
    task_id: str | None = None,
    max_lines: int = 12,
    memory_dir: str | None = None,
) -> str:
    """Generate a compact evidence pack from note paths.

    Use this to read relevant sections from specific notes. For searching notes
    by keyword, use memory_search instead.
    `query` filters relevant lines from the selected notes.
    Either `paths` (note file paths; list or single string) or `task_id` must be
    provided — omitting both raises an error, and specifying both raises a
    validation error. If only `task_id` is given, paths are auto-resolved from
    the index. `task_id` accepts `TASK-123` / `GOAL-123` or a relay task UUID.
    A valid `task_id` with no indexed notes raises `ValueError` with recovery
    guidance.
    `max_lines` limits lines per section (default 12).
    Returns JSON with the generated markdown under `markdown`.
    """
    resolved = _resolve_dir(memory_dir)
    try:
        if paths is not None and task_id is not None:
            raise ValueError(
                "Cannot specify both 'paths' and 'task_id'. "
                "Use 'paths' for explicit note file paths, "
                "or 'task_id' to auto-resolve paths from the index."
            )
        if paths is not None:
            resolved_paths = _resolve_paths(paths, resolved)
        elif task_id is not None:
            resolved_paths = _resolve_paths_from_task_id(task_id, resolved)
        else:
            raise ValueError(
                "Either 'paths' or 'task_id' must be provided. "
                "Use 'paths' to specify note file paths directly, "
                "or 'task_id' to auto-resolve paths from the index."
            )
        pack = evidence.generate_evidence_pack(
            query=query,
            paths=resolved_paths,
            max_lines=max_lines,
        )
        return _success_payload({"markdown": pack})
    except ValueError as exc:
        return _validation_error_payload(
            str(exc),
            default_hint="Pass explicit note paths or a valid task_id and retry.",
        )


@mcp.tool(annotations=_READONLY)
def memory_stats(memory_dir: str | None = None) -> str:
    """Get storage statistics for the memory directory.

    Use this to check memory usage, note counts, and SIGFB signal distribution.
    Returns note counts (total and by date), index entry count, storage size in bytes,
    date range, SIGFB signal summary by skill/type, and state item counts per section.
    """
    resolved = _resolve_dir(memory_dir)
    result = stats.get_stats(resolved)
    return _success_payload(result)


@mcp.tool(annotations=_IDEMPOTENT)
def memory_health_check(
    fix: bool = False,
    force_reindex: bool = False,
    memory_dir: str | None = None,
) -> str:
    """Check index integrity and consistency of the memory directory.

    Use this to diagnose index issues or verify memory directory health.
    Detects orphan index entries (no matching note file), unindexed notes (no index entry),
    stale entries (note newer than index), and validates state/config file parsability.
    When `fix` is True, automatically repairs detected issues: re-indexes stale and
    unindexed notes, removes orphan entries from the index.
    When `force_reindex` is True (implies `fix`), rebuilds the entire index from
    scratch. Use after breaking schema changes that require all entries to be
    regenerated (e.g. after a major version upgrade).
    Returns a structured report with a human-readable summary.
    """
    resolved = _resolve_dir(memory_dir)
    if force_reindex:
        result = health.fix_issues(resolved, force_reindex=True)
    elif fix:
        result = health.fix_issues(resolved)
    else:
        result = health.health_check(resolved)
    return _success_payload(result)


@mcp.tool(annotations=_IDEMPOTENT)
def memory_export(
    output_path: str,
    fmt: Literal["json", "zip"] = "json",
    memory_dir: str | None = None,
) -> str:
    """Export the entire memory directory to a backup file.

    `output_path` is the destination file path.
    `fmt` selects the export format: `json` (single file) or `zip` (directory preserved).
    Returns export metadata including note count and file size.
    """
    resolved = _resolve_dir(memory_dir)
    result = export.export_memory(resolved, Path(output_path), fmt=fmt)
    return _success_payload(result)


@mcp.tool(annotations=_READONLY)
def memory_list_stale_notes(
    days: int = 90,
    memory_dir: str | None = None,
) -> str:
    """List notes older than a given number of days.

    Returns a list of note metadata (path, date, title, size) for notes created more than
    `days` days ago. Does not delete anything — use `memory_cleanup_notes` to remove.
    """
    resolved = _resolve_dir(memory_dir)
    result = cleanup.list_stale_notes(resolved, days=days)
    return _success_payload(result)


@mcp.tool(annotations=_DESTRUCTIVE)
def memory_cleanup_notes(
    paths: list[str],
    dry_run: bool = True,
    memory_dir: str | None = None,
) -> str:
    """Remove specified notes and their index entries.

    `paths` is a list of note file paths (relative to memory_dir or absolute).
    `dry_run` (default true) lists what would be removed without actually deleting.
    Set `dry_run` to false to perform the actual deletion.
    """
    resolved = _resolve_dir(memory_dir)
    result = cleanup.cleanup_notes(resolved, paths=paths, dry_run=dry_run)
    return _success_payload(result)


@mcp.tool(annotations=_READONLY_OPEN_WORLD)
def memory_search_global(
    query: str,
    memory_dirs: list[str] | str | None = None,
    mode: Literal["quick", "detailed", "debug"] = "quick",
    top: int | None = None,
    prefer_recent: bool = False,
    no_expand: bool = False,
    no_cjk_expand: bool = False,
    no_fuzzy: bool = False,
    no_rerank: bool = False,
    memory_dir: str | None = None,
) -> str:
    """Search across multiple memory directories.

    Use this to find notes across different projects or workspaces.
    For searching within a single memory directory, use memory_search instead.
    `memory_dirs` is an optional list of memory directory paths to search. A single
    string is also accepted for convenience.
    `memory_dir`, if provided, is appended to `memory_dirs` for convenience.
    At least one of `memory_dirs` or `memory_dir` must be provided.
    Results are merged, scored, and sorted; each result includes `source_dir`.
    `mode` controls output verbosity: `quick` (default), `detailed`, `debug`.
    `no_expand`, `no_cjk_expand`, `no_fuzzy`, `no_rerank` override individual features
    regardless of mode — use these only when mode presets are insufficient.
    When rerank auto-enables, lazy-loading the rerank model may trigger a model
    download via `sentence_transformers`.
    Accepts the same query syntax as `memory_search`.
    """
    compact = mode == "quick"
    explain = mode == "debug"
    no_feedback_expand = mode == "quick"

    try:
        dirs = [Path(d) for d in _normalize_paths_arg(memory_dirs or []) if d]
        if memory_dir:
            additional = Path(memory_dir)
            if additional not in dirs:
                dirs.append(additional)
        if not dirs:
            raise ValueError("At least one of 'memory_dirs' or 'memory_dir' must be provided.")
        result = search.search_global(
            query=query,
            memory_dirs=dirs,
            compact=compact,
            top=top,
            explain=explain,
            prefer_recent=prefer_recent,
            no_expand=no_expand,
            no_cjk_expand=no_cjk_expand,
            no_fuzzy=no_fuzzy,
            no_use_rerank=no_rerank,
            no_feedback_expand=no_feedback_expand,
        )
    except ValueError as exc:
        return _validation_error_payload(
            str(exc),
            default_hint="Pass one or more memory directories and retry.",
        )
    if compact:
        result = _strip_global_compact_fields(result)
    elif mode == "detailed":
        result = _strip_detailed_fields(result)
    else:
        result = _strip_debug_fields(result)
    if mode != "debug":
        result = dict(result)
        result.pop("expanded", None)
    return _success_payload(result)


@mcp.tool(annotations=_ADDITIVE)
def memory_expire_stale(
    stale_days: int = 30,
    archive: bool = False,
    memory_dir: str | None = None,
) -> str:
    """Detect and optionally archive stale state items.

    Items in rolling state older than `stale_days` (default 30, minimum 1) are listed.
    The 'focus' section is always preserved (never expired).
    Set `archive` to true to move expired items to `_state_archive.md`.
    Without `archive`, this is a dry-run that only lists what would expire.
    """
    resolved = _resolve_dir(memory_dir)
    archive_path = (resolved / "_state_archive.md") if archive else None
    result = state.expire_stale_items(
        state_path=_state_path(resolved),
        stale_days=stale_days,
        archive_path=archive_path,
    )
    return _success_payload(result)


@mcp.tool(annotations=_IDEMPOTENT)
def memory_update_weights(
    updates: dict[str, float],
    memory_dir: str | None = None,
) -> str:
    """Dynamically adjust field weights for search scoring.

    `updates` is a dict of field names to new weight values (e.g. {"title": 8.0, "tags": 3.0}).
    Only existing field names are updated; unknown keys are ignored.
    Returns ``{"weights": {...}, "warnings": [...]}``.
    ``warnings`` is present only when unknown keys were given.
    """
    resolved = _resolve_dir(memory_dir)
    result = config.update_weights(resolved, updates=updates)
    return _success_payload(result)


def _memory_knowledge_add_single(
    title: str,
    content: str,
    domain: str,
    tags: list[str] | None = None,
    accuracy: Literal["verified", "likely", "uncertain"] | None = None,
    sources: list[dict[str, Any]] | None = None,
    origin: Literal["memory_distillation", "autonomous_research", "user_taught"] | None = None,
    user_understanding: Literal["unknown", "novice", "familiar", "proficient", "expert"]
    | None = None,
    related: list[str] | None = None,
    memory_dir: str | None = None,
) -> str:
    """Create one Knowledge entry.

    Registers a knowledge record under `knowledge/{id}.md` and updates `_knowledge.jsonl`.
    `title`, `content`, and `domain` are required. Optional metadata includes `tags`,
    `accuracy`, `sources`, `origin`, `user_understanding`, and `related`.
    When omitted, `accuracy` defaults to `"uncertain"` and
    `user_understanding` defaults to `"unknown"`.
    `domain` is normalized to kebab-case (e.g. `"coding_style"` → `"coding-style"`).
    `origin` is the entry-level provenance classification and accepts
    `"memory_distillation"`, `"autonomous_research"`, or `"user_taught"`
    (default: `"user_taught"`).
    `sources[].type` is the per-reference kind and accepts
    `"memory_note"`, `"web"`, `"user_direct"`, `"document"`, `"code"`, or `"other"`.
    Secret detection blocks the call with `error_type="validation_error"`.
    Returns `{ok: true, id, path}`. Duplicate content (`title` + `domain` + `content`)
    returns an error.
    """
    resolved = _resolve_dir(memory_dir)
    service = KnowledgeService()
    typed_sources: list[Source | dict[str, Any]] | None = cast(Any, sources)
    secret_check = _secret_validation_error_payload(content)
    if secret_check is not None:
        return secret_check
    try:
        entry = service.add(
            memory_dir=resolved,
            title=title,
            content=content,
            domain=domain,
            tags=tags,
            accuracy=accuracy or "uncertain",
            sources=typed_sources,
            origin=origin or "user_taught",
            user_understanding=user_understanding or "unknown",
            related=related,
        )
    except DuplicateKnowledgeError as exc:
        return _error_payload(
            error_type="validation_error",
            message=str(exc),
            hint="Search existing knowledge or update the existing entry instead.",
        )
    except FileNotFoundError as exc:
        return _error_payload(
            error_type="not_found",
            message=str(exc),
            hint="Verify all `related` knowledge ids exist before retrying.",
        )
    except (KeyError, TypeError):
        return _error_payload(
            error_type="validation_error",
            message="Invalid `sources` entry: required fields are missing or malformed.",
            hint=_required_schema_hint("sources", ("type", "ref", "summary"), sources),
        )
    except ValueError as exc:
        return _validation_error_payload(
            str(exc),
            default_hint="Adjust the knowledge fields and retry.",
        )

    payload: dict[str, Any] = {
        "id": str(entry.id),
        "path": f"knowledge/{entry.id}.md",
        "domain": str(entry.domain),
    }
    return _success_payload(payload)


@mcp.tool(annotations=_ADDITIVE)
def memory_knowledge_add(
    entries: list[dict[str, Any]],
    memory_dir: str | None = None,
) -> str:
    """Create one or more Knowledge entries.

    `entries` must be a non-empty list. Each item requires `title`, `content`, and
    `domain`; optional metadata includes `tags`, `accuracy`, `sources`, `origin`,
    `user_understanding`, and `related`. When omitted, `accuracy` defaults to
    `"uncertain"` and `user_understanding` defaults to `"unknown"`.
    Each call validates batch size against `AGENTIC_MEMORY_MAX_BATCH_SIZE` (default 50).
    Each item's `domain` is normalized to kebab-case (e.g. `"coding_style"` → `"coding-style"`).
    `origin` is the entry-level provenance classification and accepts
    `"memory_distillation"`, `"autonomous_research"`, or `"user_taught"`.
    `sources[].type` is the per-reference kind and accepts
    `"memory_note"`, `"web"`, `"user_direct"`, `"document"`, `"code"`, or `"other"`.
    For backward compatibility, each batch item may also pass `source_type` as an
    alias of `origin`; if both are present, `origin` takes precedence.
    Secret detection rejects only the affected item with `validation_error`.
    Returns `{ok, success_count, error_count, results}`. Top-level `ok` indicates the
    batch was processed, not that every item succeeded. Each result includes `index`,
    per-item `ok`, and either `{id, path, domain}` or `{error_type, message, hint}`.
    """
    validation_error = _validate_batch_input(entries, field_name="entries")
    if validation_error is not None:
        return validation_error

    results: list[dict[str, Any]] = []
    for item_index, item in enumerate(entries):
        entry, item_error = _require_mapping_item(
            item,
            index=item_index,
            field_name="entries",
            schema_fields=("title", "content", "domain"),
        )
        if item_error is not None:
            results.append(item_error)
            continue
        assert entry is not None

        title, title_error = _require_non_empty_string_field(
            entry["title"],
            index=item_index,
            field_name="entries[].title",
        )
        if title_error is not None:
            results.append(title_error)
            continue
        assert title is not None

        content, content_error = _require_non_empty_string_field(
            entry["content"],
            index=item_index,
            field_name="entries[].content",
        )
        if content_error is not None:
            results.append(content_error)
            continue
        assert content is not None

        domain, domain_error = _require_non_empty_string_field(
            entry["domain"],
            index=item_index,
            field_name="entries[].domain",
        )
        if domain_error is not None:
            results.append(domain_error)
            continue
        assert domain is not None

        results.append(
            _batch_item_result_from_payload(
                item_index,
                _memory_knowledge_add_single(
                    title=title,
                    content=content,
                    domain=domain,
                    tags=cast(list[str] | None, entry.get("tags")),
                    accuracy=cast(
                        Literal["verified", "likely", "uncertain"] | None,
                        entry.get("accuracy"),
                    ),
                    sources=cast(list[dict[str, Any]] | None, entry.get("sources")),
                    origin=_entry_origin(entry),
                    user_understanding=cast(
                        Literal["unknown", "novice", "familiar", "proficient", "expert"] | None,
                        entry.get("user_understanding"),
                    ),
                    related=cast(list[str] | None, entry.get("related")),
                    memory_dir=memory_dir,
                ),
            )
        )
    return _batch_success_payload(results)


@mcp.tool(annotations=_READONLY)
def memory_knowledge_search(
    query: str | None = None,
    domain: str | None = None,
    accuracy: Literal["verified", "likely", "uncertain"] | None = None,
    user_understanding: Literal["unknown", "novice", "familiar", "proficient", "expert"]
    | None = None,
    top: int = 10,
    no_cjk_expand: bool = False,
    include_full_content: bool = False,
    memory_dir: str | None = None,
) -> str:
    """Search Knowledge entries by text query and/or domain.

    At least one of `query` or `domain` is required. Query searches use BM25+ scoring
    over title/content/domain/tags. Domain-only searches return the filtered entries in
    `updated_at` descending order. The `domain` filter is normalized to kebab-case
    (e.g. `"coding_style"` → `"coding-style"`). Optional `accuracy` and
    `user_understanding` filters are applied to the result set. CJK query expansion is
    enabled by default; set `no_cjk_expand=true` to suppress n-gram expansion for
    Japanese/Chinese/Korean search terms. Set `include_full_content=true` to also
    return the full content and metadata fields, including `origin`.
    Returns `{ok: true, entries: [...]}` with each entry
    containing `id`, `title`, `domain`, `accuracy`, `user_understanding`,
    `content_snippet`, and `score`.
    """
    resolved = _resolve_dir(memory_dir)
    service = KnowledgeService()
    try:
        results = service.search(
            memory_dir=resolved,
            query=query,
            domain=domain,
            accuracy=accuracy,
            user_understanding=user_understanding,
            top=top,
            no_cjk_expand=no_cjk_expand,
        )
    except ValueError as exc:
        return _validation_error_payload(
            str(exc),
            default_hint="Pass `query`, `domain`, or both, and verify filter values.",
        )

    payload = {
        "entries": [
            _knowledge_entry_payload(
                entry,
                score=score,
                include_full_content=include_full_content,
            )
            for score, entry in results
        ]
    }
    return _success_payload(payload)


def _memory_knowledge_update_single(
    id: str,
    content: str | None = None,
    accuracy: Literal["verified", "likely", "uncertain"] | None = None,
    sources: list[dict[str, Any]] | None = None,
    user_understanding: Literal["unknown", "novice", "familiar", "proficient", "expert"]
    | None = None,
    related: list[str] | None = None,
    tags: list[str] | None = None,
    memory_dir: str | None = None,
) -> str:
    """Update selected fields on an existing Knowledge entry.

    `id` identifies the knowledge entry. At least one of `content`, `accuracy`,
    `sources`, `user_understanding`, `related`, or `tags` must be provided.
    `sources` and `related` are appended/merged instead of replaced, and `related`
    links are maintained bidirectionally. Returns `{ok: true, id, updated_fields}` on
    success and includes `warnings` when updated content may contain secrets.
    """
    resolved = _resolve_dir(memory_dir)
    service = KnowledgeService()
    typed_sources: list[Source | dict[str, Any]] | None = cast(Any, sources)
    updated_fields = [
        name
        for name, value in [
            ("content", content),
            ("accuracy", accuracy),
            ("sources", sources),
            ("user_understanding", user_understanding),
            ("related", related),
            ("tags", tags),
        ]
        if value is not None
    ]
    try:
        entry = service.update(
            memory_dir=resolved,
            id=id,
            content=content,
            accuracy=accuracy,
            sources=typed_sources,
            user_understanding=user_understanding,
            related=related,
            tags=tags,
        )
    except DuplicateKnowledgeError as exc:
        return _error_payload(
            error_type="validation_error",
            message=str(exc),
            hint="Change the updated content or target a different knowledge entry.",
        )
    except FileNotFoundError as exc:
        return _error_payload(
            error_type="not_found",
            message=str(exc),
            hint="Verify the knowledge id and any `related` ids exist before retrying.",
        )
    except (KeyError, TypeError):
        return _error_payload(
            error_type="validation_error",
            message="Invalid `sources` entry: required fields are missing or malformed.",
            hint=_required_schema_hint("sources", ("type", "ref", "summary"), sources),
        )
    except ValueError as exc:
        return _validation_error_payload(
            str(exc),
            default_hint="Provide at least one update field and valid metadata values.",
        )
    payload: dict[str, Any] = {"id": str(entry.id), "updated_fields": updated_fields}
    if service.last_warnings:
        payload["warnings"] = service.last_warnings
    return _success_payload(payload)


@mcp.tool(annotations=_IDEMPOTENT)
def memory_knowledge_update(
    updates: list[dict[str, Any]],
    memory_dir: str | None = None,
) -> str:
    """Update selected fields on one or more Knowledge entries.

    `updates` must be a non-empty list. Each item requires `id` and may include
    `content`, `accuracy`, `sources`, `user_understanding`, `related`, and/or `tags`.
    Each call validates batch size against `AGENTIC_MEMORY_MAX_BATCH_SIZE` (default 50).
    `sources` and `related` remain append/merge operations, and related links stay
    bidirectional. Returns `{ok, success_count, error_count, results}` with per-item
    `index`, `id`, `ok`, and either update metadata or `{error_type, message, hint}`.
    """
    validation_error = _validate_batch_input(updates, field_name="updates")
    if validation_error is not None:
        return validation_error

    results: list[dict[str, Any]] = []
    for item_index, item in enumerate(updates):
        update, item_error = _require_mapping_item(
            item,
            index=item_index,
            field_name="updates",
            schema_fields=("id",),
        )
        if item_error is not None:
            results.append(item_error)
            continue
        assert update is not None

        item_id, id_error = _require_batch_id(
            update["id"],
            index=item_index,
            field_name="updates[].id",
        )
        if id_error is not None:
            results.append(id_error)
            continue
        assert item_id is not None

        results.append(
            _batch_item_result_from_payload(
                item_index,
                _memory_knowledge_update_single(
                    id=item_id,
                    content=cast(str | None, update.get("content")),
                    accuracy=cast(
                        Literal["verified", "likely", "uncertain"] | None,
                        update.get("accuracy"),
                    ),
                    sources=cast(list[dict[str, Any]] | None, update.get("sources")),
                    user_understanding=cast(
                        Literal["unknown", "novice", "familiar", "proficient", "expert"] | None,
                        update.get("user_understanding"),
                    ),
                    related=cast(list[str] | None, update.get("related")),
                    tags=cast(list[str] | None, update.get("tags")),
                    memory_dir=memory_dir,
                ),
                item_id=item_id,
            )
        )
    return _batch_success_payload(results)


def _memory_knowledge_delete_single(
    id: str,
    confirm: bool = False,
    reason: str | None = None,
    memory_dir: str | None = None,
) -> str:
    """Delete one Knowledge entry and clean related back-links.

    `confirm=false` returns a preview without deleting.
    `confirm=true` performs the deletion and backlink cleanup.
    """
    resolved = _resolve_dir(memory_dir)
    service = KnowledgeService()
    try:
        payload = service.delete(
            memory_dir=resolved,
            id=id,
            confirm=confirm,
            reason=reason,
        )
    except FileNotFoundError as exc:
        return _error_payload(
            error_type="not_found",
            message=str(exc),
            hint="Verify the knowledge `id` exists before retrying.",
        )
    except ValueError as exc:
        return _validation_error_payload(
            str(exc),
            default_hint="Provide a valid knowledge `id` and retry.",
        )
    return _success_payload(payload)


@mcp.tool(annotations=_DESTRUCTIVE)
def memory_knowledge_delete(
    ids: list[str],
    confirm: bool = False,
    reason: str | None = None,
    memory_dir: str | None = None,
) -> str:
    """Delete one or more Knowledge entries and clean related back-links.

    `ids` must be a non-empty list. `confirm` and optional `reason` are shared across
    the batch. `confirm=false` returns per-item previews without deleting anything, and
    `confirm=true` performs deletion plus related back-link cleanup.
    Each call validates batch size against `AGENTIC_MEMORY_MAX_BATCH_SIZE` (default 50).
    Returns `{ok, success_count, error_count, results}`. Each result includes `index`,
    `id`, per-item `ok`, and either deletion metadata / `would_delete`, or
    `{error_type, message, hint}`.
    """
    validation_error = _validate_batch_input(ids, field_name="ids")
    if validation_error is not None:
        return validation_error

    results: list[dict[str, Any]] = []
    for item_index, item in enumerate(ids):
        item_id, id_error = _require_batch_id(item, index=item_index)
        if id_error is not None:
            results.append(id_error)
            continue
        assert item_id is not None

        results.append(
            _batch_item_result_from_payload(
                item_index,
                _memory_knowledge_delete_single(
                    id=item_id,
                    confirm=confirm,
                    reason=reason,
                    memory_dir=memory_dir,
                ),
                item_id=item_id,
            )
        )
    return _batch_success_payload(results)


def run_server(
    memory_dir: str | Path | None = None,
    transport: str = "stdio",
) -> None:
    """Run the MCP server."""
    if memory_dir:
        os.environ["MEMORY_DIR"] = str(memory_dir)
    transport_value = cast(Literal["stdio", "sse", "streamable-http"], transport)
    mcp.run(transport=transport_value)
