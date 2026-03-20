"""MCP server for agentic-memory tools."""

from __future__ import annotations

import dataclasses
import datetime as _dt
import io
import json
import os
from collections.abc import Callable
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
from agentic_memory.core.scorer import load_index
from agentic_memory.core.task_ids import (
    invalid_task_id_message,
)
from agentic_memory.core.task_ids import (
    normalize_task_id as _normalize_task_id,
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
    return _error_payload(
        error_type="validation_error",
        message=text,
        hint=default_hint,
    )


def _render_state_show_output(sections_payload: dict[str, Any]) -> str:
    lines: list[str] = []
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
    }
    if isinstance(parsed, dict) and "warnings" in parsed:
        payload["warnings"] = parsed["warnings"]
    if not as_json:
        sections_payload = cast(dict[str, Any], payload.pop("sections", {}))
        payload["output"] = _render_state_show_output(sections_payload)
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
    no_cjk_expand: bool = False,
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
    `no_cjk_expand` suppresses CJK n-gram expansion to reduce context consumption.
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
            no_cjk_expand=no_cjk_expand,
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


def run_server(
    memory_dir: str | Path | None = None,
    transport: str = "stdio",
) -> None:
    """Run the MCP server."""
    if memory_dir:
        os.environ["MEMORY_DIR"] = str(memory_dir)
    transport_value = cast(Literal["stdio", "sse", "streamable-http"], transport)
    mcp.run(transport=transport_value)
