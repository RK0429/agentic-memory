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

from agentic_memory.core import config, evidence, index, note, search, state
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


def _agent_state_path(
    memory_dir: Path,
    agent_id: str,
    relay_session_id: str | None = None,
    *,
    for_write: bool = False,
) -> Path:
    return state.resolve_agent_state_path(
        memory_dir=memory_dir,
        agent_id=agent_id,
        relay_session_id=relay_session_id,
        for_write=for_write,
    )


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
    if isinstance(value, (list, tuple)):
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
def memory_init(memory_dir: str | None = None) -> str:
    """Initialize memory directory files.

    Creates `_state.md`, `_index.jsonl`, and `_rag_config.json` when missing.
    `memory_dir` selects the target root directory.
    Returns initialization status and generated paths as JSON.
    """
    resolved = _resolve_dir(memory_dir)
    result = config.init_memory_dir(resolved)
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
    memory_dir: str | None = None,
) -> str:
    """Create a new session note from template.

    `title` is required. Optional `context`, `tags`, and `keywords` fill metadata fields.
    `task_id`, `agent_id`, and `relay_session_id` are stored in index metadata.
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
    memory_dir: str | None = None,
) -> str:
    """Add one or more items to a rolling state section.

    `section` is the target state section key/name.
    `items` is a list of new bullet items to prepend and de-duplicate.
    Returns command output including updated state path.
    """
    resolved = _resolve_dir(memory_dir)
    return _capture_state_cmd(
        state.cmd_add,
        _state_path(resolved),
        section=section,
        items=items,
    )


@mcp.tool()
def memory_state_set(
    section: str,
    items: list[str],
    memory_dir: str | None = None,
) -> str:
    """Replace a rolling state section with provided items.

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
    """Remove items matching a pattern from a state section.

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
def memory_state_prune(
    stale_days: int = 7,
    section: str | None = None,
    dry_run: bool = False,
    memory_dir: str | None = None,
) -> str:
    """Prune stale items from state sections.

    `stale_days` defines the staleness threshold.
    `section` can limit pruning to one section, and `dry_run` reports only.
    Returns command output including number of pruned items.
    """
    resolved = _resolve_dir(memory_dir)
    return _capture_state_cmd(
        state.cmd_prune,
        _state_path(resolved),
        stale_days=stale_days,
        section=section,
        dry_run=dry_run,
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
def memory_agent_state_show(
    agent_id: str,
    relay_session_id: str | None = None,
    section: str | None = None,
    stale_days: int = 0,
    as_json: bool = False,
    memory_dir: str | None = None,
) -> str:
    """Show agent-specific rolling state.

    Creates `_state.{agent_id}[.{relay_session_id}].md` when missing.
    Returns formatted state text, or JSON when `as_json=True`.
    """
    resolved = _resolve_dir(memory_dir)
    target_path = _agent_state_path(
        resolved,
        agent_id=agent_id,
        relay_session_id=relay_session_id,
        for_write=False,
    )
    state.ensure_state_file(target_path)
    output = _capture_state_cmd(
        state.cmd_show,
        target_path,
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


def _sync_agent_state_to_project(
    *,
    action: Callable[..., int],
    memory_dir: Path,
    section: str,
    items: list[str] | None = None,
    pattern: str | None = None,
    regex: bool = False,
) -> tuple[bool, str]:
    kwargs: dict[str, Any] = {
        "state_path": _state_path(memory_dir),
        "section": section,
    }
    if items is not None:
        kwargs["items"] = items
    if pattern is not None:
        kwargs["pattern"] = pattern
        kwargs["regex"] = regex

    result = _capture_state_cmd(action, **kwargs)
    return ("exit_code=" not in result, result)


@mcp.tool()
def memory_agent_state_set(
    agent_id: str,
    section: str,
    items: list[str],
    relay_session_id: str | None = None,
    sync_to_project: bool = False,
    memory_dir: str | None = None,
) -> str:
    """Set agent-specific state section items."""
    resolved = _resolve_dir(memory_dir)
    target_path = _agent_state_path(
        resolved,
        agent_id=agent_id,
        relay_session_id=relay_session_id,
        for_write=True,
    )
    state.ensure_state_file(target_path)
    output = _capture_state_cmd(
        state.cmd_set,
        target_path,
        section=section,
        items=items,
    )

    warnings: list[str] = []
    synced = False
    if "exit_code=" in output:
        warnings.append(output)
    elif sync_to_project:
        ok, sync_output = _sync_agent_state_to_project(
            action=state.cmd_set,
            memory_dir=resolved,
            section=section,
            items=items,
        )
        synced = ok
        if not ok:
            warnings.append(sync_output)

    return _serialize_json(
        {
            "updated_path": str(target_path),
            "synced": synced,
            "warnings": warnings,
        }
    )


@mcp.tool()
def memory_agent_state_add(
    agent_id: str,
    section: str,
    items: list[str],
    relay_session_id: str | None = None,
    sync_to_project: bool = False,
    memory_dir: str | None = None,
) -> str:
    """Add items to an agent-specific state section."""
    resolved = _resolve_dir(memory_dir)
    target_path = _agent_state_path(
        resolved,
        agent_id=agent_id,
        relay_session_id=relay_session_id,
        for_write=True,
    )
    state.ensure_state_file(target_path)
    output = _capture_state_cmd(
        state.cmd_add,
        target_path,
        section=section,
        items=items,
    )

    warnings: list[str] = []
    synced = False
    if "exit_code=" in output:
        warnings.append(output)
    elif sync_to_project:
        ok, sync_output = _sync_agent_state_to_project(
            action=state.cmd_add,
            memory_dir=resolved,
            section=section,
            items=items,
        )
        synced = ok
        if not ok:
            warnings.append(sync_output)

    return _serialize_json(
        {
            "updated_path": str(target_path),
            "synced": synced,
            "warnings": warnings,
        }
    )


@mcp.tool()
def memory_agent_state_remove(
    agent_id: str,
    section: str,
    pattern: str,
    relay_session_id: str | None = None,
    regex: bool = False,
    sync_to_project: bool = False,
    memory_dir: str | None = None,
) -> str:
    """Remove matching items from an agent-specific state section."""
    resolved = _resolve_dir(memory_dir)
    target_path = _agent_state_path(
        resolved,
        agent_id=agent_id,
        relay_session_id=relay_session_id,
        for_write=True,
    )
    state.ensure_state_file(target_path)
    output = _capture_state_cmd(
        state.cmd_remove,
        target_path,
        section=section,
        pattern=pattern,
        regex=regex,
    )

    warnings: list[str] = []
    synced = False
    removed = 0
    if "exit_code=" in output:
        warnings.append(output)
    else:
        first = output.splitlines()[0] if output.splitlines() else "0"
        try:
            removed = int(first.strip())
        except ValueError:
            removed = 0

        if sync_to_project:
            ok, sync_output = _sync_agent_state_to_project(
                action=state.cmd_remove,
                memory_dir=resolved,
                section=section,
                pattern=pattern,
                regex=regex,
            )
            synced = ok
            if not ok:
                warnings.append(sync_output)

    return _serialize_json(
        {
            "updated_path": str(target_path),
            "removed": removed,
            "synced": synced,
            "warnings": warnings,
        }
    )


@mcp.tool()
def memory_cleanup(
    state_ttl_days: int = 7,
    state_max_generations: int = 20,
    dry_run: bool = False,
    memory_dir: str | None = None,
) -> str:
    """Clean up expired or excess agent-specific state files.

    Targets files matching `_state.{agent_id}[.{relay_session_id}].md`.
    `state_ttl_days` removes stale files by mtime, and `state_max_generations`
    keeps latest N files per `agent_id`.
    Returns command output including number of affected files.
    """
    resolved = _resolve_dir(memory_dir)
    return _capture_state_cmd(
        state.cmd_cleanup,
        resolved,
        state_ttl_days=state_ttl_days,
        state_max_generations=state_max_generations,
        dry_run=dry_run,
    )


@mcp.tool()
def memory_auto_restore(
    agent_id: str | None = None,
    relay_session_id: str | None = None,
    max_evidence_notes: int = 3,
    max_lines: int = 6,
    include_project_state: bool = True,
    include_agent_state: bool = True,
    memory_dir: str | None = None,
) -> str:
    """Restore active task context from rolling state and evidence."""
    resolved = _resolve_dir(memory_dir)
    payload = state.auto_restore(
        memory_dir=resolved,
        agent_id=agent_id,
        relay_session_id=relay_session_id,
        max_evidence_notes=max_evidence_notes,
        max_lines=max_lines,
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
    sync_stale_index: bool = False,
    rerank: bool = False,
    no_rerank: bool = False,
    prf: bool = False,
    no_prf: bool = False,
    default_date_range: int | None = None,
    memory_dir: str | None = None,
) -> str:
    """Search session notes by query.

    Supports quoted phrases, +must, -exclude, field:term, and date-range filters.
    `engine` options include `auto`, `index`, `hybrid`, `rg`, `python`.
    Returns ranked results, warnings, expansions, and snippets settings as JSON.
    """
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
        sync_stale_index=sync_stale_index,
        use_rerank=rerank,
        no_use_rerank=no_rerank,
        prf=prf,
        no_prf=no_prf,
        default_date_range=default_date_range,
    )
    return _serialize_json(result)


@mcp.tool()
def memory_index_build(
    max_summary_chars: int = 280,
    no_dense: bool = False,
    since: str | None = None,
    dry_run: bool = False,
    memory_dir: str | None = None,
) -> str:
    """Rebuild memory index from all notes.

    `max_summary_chars` truncates extracted summary text.
    `no_dense` skips dense embedding index build, and `since` filters by date (YYYY-MM-DD).
    `dry_run` returns paths that would be indexed, without mutating `_index.jsonl`.
    Returns full rebuilt index entries as JSON.
    """
    resolved = _resolve_dir(memory_dir)
    if dry_run:
        notes = index.list_notes(resolved)
        filtered = _filter_notes_by_since(notes, since)
        return _serialize_json([str(path) for path in filtered])

    result = index.rebuild_index(
        index_path=_index_path(resolved),
        dailynote_dir=resolved,
        max_summary_chars=max_summary_chars,
        no_dense=no_dense,
        since=since,
    )
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
    If `paths` is omitted and `task_id` is provided, note paths are auto-resolved from `_index.jsonl`.
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


def run_server(
    memory_dir: str | Path | None = None,
    transport: str = "stdio",
) -> None:
    """Run the MCP server."""
    if memory_dir:
        os.environ["MEMORY_DIR"] = str(memory_dir)
    transport_value = cast(Literal["stdio", "sse", "streamable-http"], transport)
    mcp.run(transport=transport_value)
