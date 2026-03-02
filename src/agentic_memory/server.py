"""MCP server for agentic-memory tools."""

from __future__ import annotations

import dataclasses
import io
import json
import os
from collections.abc import Callable
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from agentic_memory.core import config, evidence, index, note, search, state

try:
    mcp = FastMCP(
        "memory",
        description="Persistent memory system for AI agents",
    )
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
    if dataclasses.is_dataclass(value):
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
    if p.is_absolute() or p.exists():
        return p
    return memory_dir / p


def _resolve_paths(paths: list[str], memory_dir: Path) -> list[Path]:
    resolved: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_absolute() or p.exists():
            resolved.append(p)
        else:
            resolved.append(memory_dir / p)
    return resolved


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
    memory_dir: str | None = None,
) -> str:
    """Create a new session note from template.

    `title` is required. Optional `context`, `tags`, and `keywords` fill metadata fields.
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
def memory_search(
    query: str,
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
        rerank=rerank,
        no_rerank=no_rerank,
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
    memory_dir: str | None = None,
) -> str:
    """Rebuild memory index from all notes.

    `max_summary_chars` truncates extracted summary text.
    `no_dense` skips dense embedding index build, and `since` filters by date (YYYY-MM-DD).
    Returns full rebuilt index entries as JSON.
    """
    resolved = _resolve_dir(memory_dir)
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
        max_summary_chars=max_summary_chars,
        no_dense=no_dense,
    )
    return _serialize_json(result)


@mcp.tool()
def memory_evidence(
    query: str,
    paths: list[str],
    max_lines: int = 8,
    memory_dir: str | None = None,
) -> str:
    """Generate a compact evidence pack from note paths.

    `query` is used to filter relevant lines.
    `paths` is a list of note paths (absolute or relative), `max_lines` limits lines per section.
    Returns markdown evidence text with provenance per note.
    """
    resolved = _resolve_dir(memory_dir)
    resolved_paths = _resolve_paths(paths, resolved)
    return evidence.generate_evidence_pack(query=query, paths=resolved_paths, max_lines=max_lines)


def run_server(
    memory_dir: str | Path | None = None,
    transport: str = "stdio",
) -> None:
    """Run the MCP server."""
    if memory_dir:
        os.environ["MEMORY_DIR"] = str(memory_dir)
    mcp.run(transport=transport)
