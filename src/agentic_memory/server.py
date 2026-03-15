"""MCP server for agentic-memory tools."""

from __future__ import annotations

import dataclasses
import datetime as _dt
import io
import json
import os
import re
from collections.abc import Callable
from contextlib import redirect_stderr, redirect_stdout
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
    state,
    stats,
)
from agentic_memory.core.scorer import load_index

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


def _capture_state_cmd(func: Callable[..., int], *args: Any, **kwargs: Any) -> str:
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = func(*args, **kwargs)

    stdout_text = out.getvalue().strip()
    stderr_text = err.getvalue().strip()

    lines: list[str] = []
    if stdout_text:
        lines.append(stdout_text)
    if stderr_text:
        lines.append(stderr_text)
    if code != 0:
        lines.append(f"exit_code={code}")
    if not lines:
        lines.append("ok")
    return "\n".join(lines)


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


def _resolve_paths(paths: list[str], memory_dir: Path) -> list[Path]:
    resolved: list[Path] = []
    for raw in paths:
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


TASK_ID_PATTERN = re.compile(r"^(TASK|GOAL)-\d{3,}$")
TASK_ID_EXTRACT_PATTERN = re.compile(r"\b((?:TASK|GOAL)-\d{3,})\b")


def _normalize_task_id(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().upper()
    if not normalized:
        return None
    if TASK_ID_PATTERN.fullmatch(normalized):
        return normalized
    match = TASK_ID_EXTRACT_PATTERN.search(normalized)
    if match:
        return match.group(1)
    return None


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
        raise ValueError(f"Invalid task_id: {task_id!r}")

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
    return _serialize_json(result)


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
    `lang` selects the template language.
    Returns JSON with the created note path and metadata.
    """
    resolved = _resolve_dir(memory_dir)
    created = note.create_note(
        memory_dir=resolved,
        title=title,
        context=context,
        tags=tags,
        keywords=keywords,
        auto_index=False,
        lang=lang,
    )
    index.index_note(
        note_path=created,
        index_path=_index_path(resolved),
        dailynote_dir=resolved,
        task_id=task_id,
        agent_id=agent_id,
        relay_session_id=relay_session_id,
        no_dense=True,
    )
    return _serialize_json({"path": str(created), "title": title, "date": str(created.parent.name)})


@mcp.tool(annotations=_READONLY)
def memory_state_show(
    section: str | None = None,
    stale_days: int = 0,
    as_json: bool = False,
    memory_dir: str | None = None,
) -> str:
    """Show rolling state sections.

    Use this to check current focus, open actions, decisions, and pitfalls.
    `section` filters one state section, `stale_days` marks stale items,
    and `as_json` uses JSON output.
    `memory_dir` selects the state file location.
    Returns formatted state text, or JSON string when `as_json=True`.
    """
    resolved = _resolve_dir(memory_dir)
    output = _capture_state_cmd(
        state.cmd_show,
        _state_path(resolved),
        section=section,
        stale_days=stale_days,
        as_json=as_json,
    )
    if as_json:
        try:
            return _serialize_json(json.loads(output))
        except json.JSONDecodeError:
            return output
    return output


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


@mcp.tool(annotations=_ADDITIVE)
def memory_state_from_note(
    note_path: str,
    no_auto_improve: bool = False,
    auto_improve_add: bool = False,
    max_entries: int = 20,
    memory_dir: str | None = None,
) -> str:
    """Update rolling state using a note file.

    `note_path` points to the source note.
    After merging note sections into rolling state, SIGFB signals in the note are
    analyzed to detect improvement candidates for the backlog:
      - Default (`no_auto_improve=False, auto_improve_add=False`): candidates are
        reported in `warnings` but not added to the backlog.
      - `auto_improve_add=True`: candidates are added to the improvements backlog.
      - `no_auto_improve=True`: skip signal analysis entirely.
    `max_entries` limits section lengths after merge (excess items are auto-pruned
    and reported in `warnings`).
    Returns JSON with `updated_sections`, `section_counts`, `stale_count`,
    and `warnings` (cap-exceeded, auto-prune, auto-improve candidates, stale items).
    """
    resolved = _resolve_dir(memory_dir)
    resolved_note = _resolve_note_path(note_path, resolved)
    return _capture_state_cmd(
        state.cmd_from_note,
        _state_path(resolved),
        note_path=resolved_note,
        no_auto_improve=no_auto_improve,
        auto_improve_add=auto_improve_add,
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
    return _serialize_json(payload)


@mcp.tool(annotations=_READONLY)
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
    `mode` controls output verbosity and sets search defaults:
      - `quick` (default): compact output, strips verbose fields and settings echo-back.
        Sets: compact=True, no_feedback_expand=True.
      - `detailed`: full metadata except auto_keywords and work_log_keywords.
        Sets: compact=False, no_feedback_expand=False.
      - `debug`: all fields + scoring explanation (explain_summary, expanded QueryTerm objects).
        Sets: compact=False, no_feedback_expand=False, explain=True.
    `no_expand`, `no_cjk_expand`, `no_fuzzy`, `no_rerank` override individual features
    regardless of mode — use these only when mode presets are insufficient.
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
    return _serialize_json(result)


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

    `note_path` targets the note to index.
    `max_summary_chars` truncates summary extraction, and `no_dense` skips dense upsert.
    `compact` omits verbose fields (auto_keywords, work_log_keywords, etc.) from the response.
    Returns the indexed entry as JSON.
    """
    resolved = _resolve_dir(memory_dir)
    resolved_note = _resolve_note_path(note_path, resolved)
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
    if compact:
        exclude = search.COMPACT_EXCLUDE_FIELDS
        result = {key: value for key, value in result.items() if key not in exclude}
    return _serialize_json(result)


@mcp.tool(annotations=_READONLY)
def memory_evidence(
    query: str,
    paths: list[str] | None = None,
    task_id: str | None = None,
    max_lines: int = 12,
    memory_dir: str | None = None,
) -> str:
    """Generate a compact evidence pack from note paths.

    Use this to read relevant sections from specific notes. For searching notes
    by keyword, use memory_search instead.
    `query` filters relevant lines from the selected notes.
    Either `paths` (note file paths) or `task_id` must be provided — omitting both
    raises an error. If only `task_id` is given, paths are auto-resolved from the index.
    `max_lines` limits lines per section (default 12).
    Returns markdown evidence text with provenance per note.
    """
    resolved = _resolve_dir(memory_dir)
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

    return evidence.generate_evidence_pack(query=query, paths=resolved_paths, max_lines=max_lines)


@mcp.tool(annotations=_READONLY)
def memory_stats(memory_dir: str | None = None) -> str:
    """Get storage statistics for the memory directory.

    Use this to check memory usage, note counts, and SIGFB signal distribution.
    Returns note counts (total and by date), index entry count, storage size in bytes,
    date range, SIGFB signal summary by skill/type, and state item counts per section.
    """
    resolved = _resolve_dir(memory_dir)
    result = stats.get_stats(resolved)
    return _serialize_json(result)


@mcp.tool(annotations=_IDEMPOTENT)
def memory_health_check(
    fix: bool = False,
    memory_dir: str | None = None,
) -> str:
    """Check index integrity and consistency of the memory directory.

    Use this to diagnose index issues or verify memory directory health.
    Detects orphan index entries (no matching note file), unindexed notes (no index entry),
    stale entries (note newer than index), and validates state/config file parsability.
    When `fix` is True, automatically repairs detected issues: re-indexes stale and
    unindexed notes, removes orphan entries from the index.
    Returns a structured report with a human-readable summary.
    """
    resolved = _resolve_dir(memory_dir)
    result = health.fix_issues(resolved) if fix else health.health_check(resolved)
    return _serialize_json(result)


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
    return _serialize_json(result)


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
    return _serialize_json(result)


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
    return _serialize_json(result)


@mcp.tool(annotations=_READONLY)
def memory_search_global(
    query: str,
    memory_dirs: list[str] | None = None,
    mode: Literal["quick", "detailed", "debug"] = "quick",
    top: int | None = None,
    prefer_recent: bool = False,
    no_cjk_expand: bool = False,
    memory_dir: str | None = None,
) -> str:
    """Search across multiple memory directories.

    Use this to find notes across different projects or workspaces.
    For searching within a single memory directory, use memory_search instead.
    `memory_dirs` is an optional list of memory directory paths to search.
    `memory_dir`, if provided, is appended to `memory_dirs` for convenience.
    At least one of `memory_dirs` or `memory_dir` must be provided.
    Results are merged, scored, and sorted; each result includes `source_dir`.
    `mode` controls output verbosity: `quick` (default), `detailed`, `debug`.
    `no_cjk_expand` suppresses CJK n-gram expansion to reduce context consumption.
    Accepts the same query syntax as `memory_search`.
    """
    compact = mode == "quick"
    explain = mode == "debug"
    no_feedback_expand = mode == "quick"

    dirs = [Path(d) for d in (memory_dirs or []) if d]
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
    if compact:
        result = _strip_compact_fields(result)
    elif mode == "detailed":
        result = _strip_detailed_fields(result)
    else:
        result = _strip_debug_fields(result)
    if mode != "debug":
        result = dict(result)
        result.pop("expanded", None)
    return _serialize_json(result)


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
    return _serialize_json(result)


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
    return _serialize_json(result)


def run_server(
    memory_dir: str | Path | None = None,
    transport: str = "stdio",
) -> None:
    """Run the MCP server."""
    if memory_dir:
        os.environ["MEMORY_DIR"] = str(memory_dir)
    transport_value = cast(Literal["stdio", "sse", "streamable-http"], transport)
    mcp.run(transport=transport_value)
