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
    return memory_dir / p


def _resolve_paths(paths: list[str], memory_dir: Path) -> list[Path]:
    resolved: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_absolute() or p.exists():
            resolved.append(p)
        elif (memory_dir.parent / p).exists():
            resolved.append(memory_dir.parent / p)
        else:
            resolved.append(memory_dir / p)
    return resolved


def _strip_compact_fields(result: dict) -> dict:
    """Remove verbose index fields from search results for compact mode."""
    exclude = search.COMPACT_EXCLUDE_FIELDS
    stripped_results = []
    for item in result.get("results", []):
        if isinstance(item, tuple) and len(item) >= 2:
            score, entry, *rest = item
            if dataclasses.is_dataclass(entry) and not isinstance(entry, type):
                entry_dict = dataclasses.asdict(entry)
                entry_dict = {k: v for k, v in entry_dict.items() if k not in exclude}
                detail = rest[0] if rest else {}
                stripped_results.append((score, entry_dict, detail))
            else:
                stripped_results.append(item)
        else:
            stripped_results.append(item)
    result = dict(result)
    result["results"] = stripped_results
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


@mcp.tool()
def memory_init(
    memory_dir: str | None = None,
    enable_dense: bool = False,
) -> str:
    """Initialize memory directory files.

    Creates `_state.md`, `_index.jsonl`, and `_rag_config.json` when missing.
    Set `enable_dense` to true to configure dense (semantic) retrieval in `_rag_config.json`.
    `memory_dir` selects the target root directory.
    Returns initialization status and generated paths as JSON.
    """
    resolved = _resolve_dir(memory_dir)
    result = config.init_memory_dir(resolved, enable_dense=enable_dense)
    return _serialize_json(result)


@mcp.tool()
def memory_note_new(
    title: str,
    context: str | None = None,
    tags: str | None = None,
    keywords: str | None = None,
    task_id: str | None = None,
    agent_id: str | None = None,
    relay_session_id: str | None = None,
    lang: str = "ja",
    memory_dir: str | None = None,
) -> str:
    """Create a new session note from template.

    `title` is required. Optional `context`, `tags`, and `keywords` fill metadata fields.
    `task_id`, `agent_id`, and `relay_session_id` are stored in index metadata.
    `lang` selects the template language (`ja` or `en`).
    `memory_dir` sets the note root directory.
    Returns the created note file path.
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
    return str(created)


@mcp.tool()
def memory_state_show(
    section: str | None = None,
    stale_days: int = 0,
    as_json: bool = False,
    memory_dir: str | None = None,
) -> str:
    """Show rolling state sections.

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


@mcp.tool()
def memory_state_add(
    section: str,
    items: list[str],
    replace: list[str] | None = None,
    memory_dir: str | None = None,
) -> str:
    """Add items to a state section with optional pattern-based replacement.

    `section` is the target state section key/name.
    `items` is a list of new bullet items to prepend and de-duplicate.
    `replace` is an optional list of substring patterns; existing items matching any pattern
    are removed before adding new items (upsert semantics: remove old + add new in one step).
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


@mcp.tool()
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


@mcp.tool()
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


@mcp.tool()
def memory_state_from_note(
    note_path: str,
    no_auto_improve: bool = False,
    auto_improve_add: bool = False,
    max_entries: int = 20,
    memory_dir: str | None = None,
) -> str:
    """Update rolling state using a note file.

    `note_path` points to the source note.
    Auto-improve behavior is controlled by `no_auto_improve` and `auto_improve_add`.
    `max_entries` limits section lengths after merge.
    Returns command output and warnings from merge processing.
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


@mcp.tool()
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


@mcp.tool()
def memory_search(
    query: str,
    task_id: str | None = None,
    agent_id: str | None = None,
    relay_session_id: str | None = None,
    top: int | None = None,
    snippets: int | None = None,
    engine: str = "auto",
    prefer_recent: bool = False,
    half_life_days: float | None = None,
    explain: bool = False,
    suggest: bool = False,
    no_expand: bool = False,
    no_feedback_expand: bool = False,
    no_fuzzy: bool = False,
    no_cjk_expand: bool = False,
    sync_stale_index: bool = False,
    rerank: bool = False,
    no_rerank: bool = False,
    prf: bool = False,
    no_prf: bool = False,
    default_date_range: int | None = None,
    compact: bool = False,
    mode: str | None = None,
    memory_dir: str | None = None,
) -> str:
    """Search session notes by query.

    Supports quoted phrases, +must, -exclude, field:term (with aliases like tag:),
    and date-range filters.
    `engine` options include `auto`, `index`, `hybrid`, `rg`, `python`.
    `compact` omits verbose index fields (auto_keywords, work_log_keywords, etc.)
    from results to reduce response size.
    `no_cjk_expand` suppresses CJK n-gram expansion to reduce context consumption.
    `mode` preset: `quick` (compact, no explain), `detailed` (default),
    `debug` (explain, all fields).
    Returns ranked results, warnings, expansions, and snippets settings as JSON.
    """
    # Apply mode presets
    if mode == "quick":
        compact = True
        explain = False
    elif mode == "debug":
        compact = False
        explain = True

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
        use_rerank=rerank,
        no_use_rerank=no_rerank,
        prf=prf,
        no_prf=no_prf,
        default_date_range=default_date_range,
        compact=compact,
    )
    if compact:
        result = _strip_compact_fields(result)
    return _serialize_json(result)


@mcp.tool()
def memory_index_upsert(
    note_path: str,
    task_id: str | None = None,
    agent_id: str | None = None,
    relay_session_id: str | None = None,
    max_summary_chars: int = 280,
    no_dense: bool = False,
    memory_dir: str | None = None,
) -> str:
    """Upsert one note into the index.

    `note_path` targets the note to index.
    `max_summary_chars` truncates summary extraction, and `no_dense` skips dense upsert.
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
    return _serialize_json(result)


@mcp.tool()
def memory_evidence(
    query: str,
    paths: list[str] | None = None,
    task_id: str | None = None,
    max_lines: int = 8,
    memory_dir: str | None = None,
) -> str:
    """Generate a compact evidence pack from note paths.

    `query` is used to filter relevant lines.
    `paths` is a list of note paths (absolute or relative), `max_lines` limits lines per section.
    If `paths` is omitted and `task_id` is provided, paths are auto-resolved from the index.
    Either `paths` or `task_id` must be provided; omitting both raises an error.
    Returns markdown evidence text with provenance per note.
    """
    resolved = _resolve_dir(memory_dir)
    if paths is not None:
        resolved_paths = _resolve_paths(paths, resolved)
    elif task_id is not None:
        resolved_paths = _resolve_paths_from_task_id(task_id, resolved)
    else:
        raise ValueError("Either paths or task_id must be provided.")

    return evidence.generate_evidence_pack(query=query, paths=resolved_paths, max_lines=max_lines)


@mcp.tool()
def memory_stats(memory_dir: str | None = None) -> str:
    """Get storage statistics for the memory directory.

    Returns note counts (total and by date), index entry count, storage size in bytes,
    date range, SIGFB signal summary by skill/type, and state item counts per section.
    """
    resolved = _resolve_dir(memory_dir)
    result = stats.get_stats(resolved)
    return _serialize_json(result)


@mcp.tool()
def memory_health_check(memory_dir: str | None = None) -> str:
    """Check index integrity and consistency of the memory directory.

    Detects orphan index entries (no matching note file), unindexed notes (no index entry),
    stale entries (note newer than index), and validates state/config file parsability.
    Returns a structured report with a human-readable summary.
    """
    resolved = _resolve_dir(memory_dir)
    result = health.health_check(resolved)
    return _serialize_json(result)


@mcp.tool()
def memory_export(
    output_path: str,
    fmt: str = "json",
    memory_dir: str | None = None,
) -> str:
    """Export the entire memory directory to a backup file.

    `output_path` is the destination file path.
    `fmt` is `json` (single JSON file with all data) or `zip` (directory structure preserved).
    Returns export metadata including note count and file size.
    """
    resolved = _resolve_dir(memory_dir)
    result = export.export_memory(resolved, Path(output_path), fmt=fmt)
    return _serialize_json(result)


@mcp.tool()
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


@mcp.tool()
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


@mcp.tool()
def memory_search_global(
    query: str,
    memory_dirs: list[str],
    top: int | None = None,
    explain: bool = False,
    prefer_recent: bool = False,
    compact: bool = False,
    no_cjk_expand: bool = False,
    memory_dir: str | None = None,
) -> str:
    """Search across multiple memory directories.

    `memory_dirs` is a list of memory directory paths to search.
    Results from all directories are merged, scored, and sorted.
    Each result includes a `source_dir` key identifying its origin.
    `compact` omits verbose index fields from results to reduce response size.
    `no_cjk_expand` suppresses CJK n-gram expansion to reduce context consumption.
    Accepts the same query syntax as `memory_search`.
    """
    dirs = [Path(d) for d in memory_dirs]
    result = search.search_global(
        query=query,
        memory_dirs=dirs,
        compact=compact,
        top=top,
        explain=explain,
        prefer_recent=prefer_recent,
        no_cjk_expand=no_cjk_expand,
    )
    if compact:
        result = _strip_compact_fields(result)
    return _serialize_json(result)


@mcp.tool()
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


@mcp.tool()
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
