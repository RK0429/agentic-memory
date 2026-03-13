"""Click-based CLI for agentic-memory."""

from __future__ import annotations

import dataclasses
import datetime as _dt
import inspect
import json
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, cast

import click

from agentic_memory import __version__
from agentic_memory.core import config, evidence, index, note, search, state
from agentic_memory.core.query import QueryParseError, QueryTerm
from agentic_memory.core.scorer import IndexEntry


@dataclasses.dataclass(slots=True)
class AppContext:
    memory_dir: Path
    verbose: bool


def _get_ctx(ctx: click.Context) -> AppContext:
    obj = ctx.obj
    if isinstance(obj, AppContext):
        return obj
    raise click.ClickException("CLI context is not initialized.")


def _vlog(app: AppContext, message: str) -> None:
    if app.verbose:
        click.echo(message, err=True)


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


def _dedupe_keep_order(items: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        value = item.strip()
        if not value:
            continue
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def _entry_to_dict(entry: IndexEntry) -> dict[str, Any]:
    payload = dataclasses.asdict(entry)
    return cast(dict[str, Any], payload)


def _normalize_search_results(payload: dict[str, Any], explain: bool) -> list[dict[str, Any]]:
    raw_results = cast(list[tuple[float, IndexEntry, dict[str, Any]]], payload.get("results", []))
    expanded = cast(list[QueryTerm], payload.get("expanded", []))
    snippets_n = int(payload.get("snippets", 3))

    normalized: list[dict[str, Any]] = []
    for score, entry, detail in raw_results:
        row = _entry_to_dict(entry)
        row["score"] = float(score)
        row["snippets"] = search.extract_snippets(Path(entry.path), expanded, snippets_n)
        if explain:
            row["explain"] = detail
        normalized.append(row)
    return normalized


def _filter_notes_by_since(notes: Sequence[Path], since: str | None) -> list[Path]:
    if since is None:
        return list(notes)

    try:
        since_date = _dt.date.fromisoformat(since)
    except ValueError as exc:
        raise click.UsageError(f"Invalid since date: {since}") from exc

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


@click.group()
@click.option(
    "--memory-dir",
    type=click.Path(path_type=Path, file_okay=False, dir_okay=True),
    default=None,
    help="Override memory directory (default: resolve via config.resolve_memory_dir()).",
)
@click.option("--verbose", "-v", is_flag=True, help="Verbose output.")
@click.pass_context
def main(ctx: click.Context, memory_dir: Path | None, verbose: bool) -> None:
    """Memory CLI."""
    resolved_memory_dir = memory_dir if memory_dir is not None else config.resolve_memory_dir()
    ctx.obj = AppContext(memory_dir=resolved_memory_dir, verbose=verbose)


@main.command("init")
@click.pass_context
def cmd_init(ctx: click.Context) -> None:
    """Initialize memory directory."""
    app = _get_ctx(ctx)
    result = config.init_memory_dir(app.memory_dir)
    status = str(result.get("status", ""))

    if status == "already_exists":
        click.echo(f"Already exists: {result.get('memory_dir', str(app.memory_dir))}")
    else:
        click.echo(str(app.memory_dir))

    _vlog(app, f"state: {result.get('state_path', _state_path(app.memory_dir))}")
    _vlog(app, f"index: {result.get('index_path', _index_path(app.memory_dir))}")


@main.group("note")
def note_group() -> None:
    """Note operations."""


@note_group.command("new")
@click.option("--title", required=True, help="Note title.")
@click.option("--tags", default=None, help="Comma-separated tags.")
@click.option("--keywords", default=None, help="Comma-separated keywords.")
@click.option("--context", default=None, help="Context (issue/pr/link).")
@click.option("--task-id", default=None, help="Task identifier (e.g., TASK-001).")
@click.option("--agent-id", default=None, help="Agent identifier.")
@click.option("--relay-session-id", default=None, help="Relay session identifier.")
@click.pass_context
def cmd_note_new(
    ctx: click.Context,
    title: str,
    tags: str | None,
    keywords: str | None,
    context: str | None,
    task_id: str | None,
    agent_id: str | None,
    relay_session_id: str | None,
) -> None:
    """Create a new note."""
    app = _get_ctx(ctx)
    out_path = note.create_note(
        memory_dir=app.memory_dir,
        title=title,
        context=context,
        tags=tags,
        keywords=keywords,
        auto_index=False,
    )
    try:
        index.index_note(
            note_path=out_path,
            index_path=_index_path(app.memory_dir),
            dailynote_dir=app.memory_dir,
            task_id=task_id,
            agent_id=agent_id,
            relay_session_id=relay_session_id,
            no_dense=True,
        )
    except ValueError as exc:
        raise click.UsageError(str(exc)) from exc
    click.echo(str(out_path))


@main.group("state")
def state_group() -> None:
    """Rolling state operations."""


@state_group.command("show")
@click.option("--section", default=None, help="Section key.")
@click.option("--stale-days", type=int, default=0, show_default=True)
@click.option("--json", "as_json", is_flag=True, help="Output JSON.")
@click.pass_context
def cmd_state_show(
    ctx: click.Context,
    section: str | None,
    stale_days: int,
    as_json: bool,
) -> None:
    """Show state."""
    app = _get_ctx(ctx)
    return_code = state.cmd_show(
        state_path=_state_path(app.memory_dir),
        section=section,
        stale_days=stale_days,
        as_json=as_json,
    )
    sys.exit(return_code)


@state_group.command("add")
@click.option("--section", required=True, help="Section key.")
@click.option("--item", "items", multiple=True, required=True, help="Item text.")
@click.pass_context
def cmd_state_add(ctx: click.Context, section: str, items: tuple[str, ...]) -> None:
    """Add items into a section."""
    app = _get_ctx(ctx)
    return_code = state.cmd_add(
        state_path=_state_path(app.memory_dir),
        section=section,
        items=list(items),
    )
    sys.exit(return_code)


@state_group.command("set")
@click.option("--section", required=True, help="Section key.")
@click.option("--item", "items", multiple=True, required=True, help="Item text.")
@click.pass_context
def cmd_state_set(ctx: click.Context, section: str, items: tuple[str, ...]) -> None:
    """Replace a section with items."""
    app = _get_ctx(ctx)
    return_code = state.cmd_set(
        state_path=_state_path(app.memory_dir),
        section=section,
        items=list(items),
    )
    sys.exit(return_code)


@state_group.command("remove")
@click.option("--section", required=True, help="Section key.")
@click.option("--pattern", required=True, help="String or regex pattern.")
@click.option("--regex", is_flag=True, help="Treat pattern as regex.")
@click.pass_context
def cmd_state_remove(ctx: click.Context, section: str, pattern: str, regex: bool) -> None:
    """Remove items from a section."""
    app = _get_ctx(ctx)
    return_code = state.cmd_remove(
        state_path=_state_path(app.memory_dir),
        section=section,
        pattern=pattern,
        regex=regex,
    )
    sys.exit(return_code)


@state_group.command("prune")
@click.option("--stale-days", type=int, default=7, show_default=True)
@click.option("--section", default=None, help="Section key.")
@click.option("--dry-run", is_flag=True, help="Show prune candidates only.")
@click.pass_context
def cmd_state_prune(
    ctx: click.Context,
    stale_days: int,
    section: str | None,
    dry_run: bool,
) -> None:
    """Prune stale items."""
    app = _get_ctx(ctx)
    return_code = state.cmd_prune(
        state_path=_state_path(app.memory_dir),
        stale_days=stale_days,
        section=section,
        dry_run=dry_run,
    )
    sys.exit(return_code)


@state_group.command("from-note")
@click.argument("note_path", type=click.Path(path_type=Path))
@click.option("--no-auto-improve", is_flag=True, help="Skip auto-improve analysis.")
@click.option("--auto-improve-add", is_flag=True, help="Add auto-improve candidates to backlog.")
@click.pass_context
def cmd_state_from_note(
    ctx: click.Context,
    note_path: Path,
    no_auto_improve: bool,
    auto_improve_add: bool,
) -> None:
    """Update state from a note."""
    app = _get_ctx(ctx)
    return_code = state.cmd_from_note(
        state_path=_state_path(app.memory_dir),
        note_path=note_path,
        no_auto_improve=no_auto_improve,
        auto_improve_add=auto_improve_add,
    )
    sys.exit(return_code)


@main.group("agent-state")
def agent_state_group() -> None:
    """Agent-specific rolling state operations."""


@agent_state_group.command("show")
@click.option("--agent-id", required=True, help="Agent identifier.")
@click.option("--relay-session-id", default=None, help="Relay session identifier.")
@click.option("--section", default=None, help="Section key.")
@click.option("--stale-days", type=int, default=0, show_default=True)
@click.option("--json", "as_json", is_flag=True, help="Output JSON.")
@click.pass_context
def cmd_agent_state_show(
    ctx: click.Context,
    agent_id: str,
    relay_session_id: str | None,
    section: str | None,
    stale_days: int,
    as_json: bool,
) -> None:
    """Show agent-specific state."""
    app = _get_ctx(ctx)
    target = _agent_state_path(
        app.memory_dir,
        agent_id=agent_id,
        relay_session_id=relay_session_id,
        for_write=False,
    )
    state.ensure_state_file(target)
    return_code = state.cmd_show(
        state_path=target,
        section=section,
        stale_days=stale_days,
        as_json=as_json,
    )
    sys.exit(return_code)


@agent_state_group.command("set")
@click.option("--agent-id", required=True, help="Agent identifier.")
@click.option("--relay-session-id", default=None, help="Relay session identifier.")
@click.option("--section", required=True, help="Section key.")
@click.option("--item", "items", multiple=True, required=True, help="Item text.")
@click.option("--sync-to-project", is_flag=True, help="Apply the same change to project state.")
@click.pass_context
def cmd_agent_state_set(
    ctx: click.Context,
    agent_id: str,
    relay_session_id: str | None,
    section: str,
    items: tuple[str, ...],
    sync_to_project: bool,
) -> None:
    """Replace a section in agent-specific state."""
    app = _get_ctx(ctx)
    target = _agent_state_path(
        app.memory_dir,
        agent_id=agent_id,
        relay_session_id=relay_session_id,
        for_write=True,
    )
    state.ensure_state_file(target)
    return_code = state.cmd_set(state_path=target, section=section, items=list(items))
    if return_code == 0 and sync_to_project:
        return_code = state.cmd_set(
            state_path=_state_path(app.memory_dir),
            section=section,
            items=list(items),
        )
    sys.exit(return_code)


@agent_state_group.command("add")
@click.option("--agent-id", required=True, help="Agent identifier.")
@click.option("--relay-session-id", default=None, help="Relay session identifier.")
@click.option("--section", required=True, help="Section key.")
@click.option("--item", "items", multiple=True, required=True, help="Item text.")
@click.option("--sync-to-project", is_flag=True, help="Apply the same change to project state.")
@click.pass_context
def cmd_agent_state_add(
    ctx: click.Context,
    agent_id: str,
    relay_session_id: str | None,
    section: str,
    items: tuple[str, ...],
    sync_to_project: bool,
) -> None:
    """Add items to a section in agent-specific state."""
    app = _get_ctx(ctx)
    target = _agent_state_path(
        app.memory_dir,
        agent_id=agent_id,
        relay_session_id=relay_session_id,
        for_write=True,
    )
    state.ensure_state_file(target)
    return_code = state.cmd_add(state_path=target, section=section, items=list(items))
    if return_code == 0 and sync_to_project:
        return_code = state.cmd_add(
            state_path=_state_path(app.memory_dir),
            section=section,
            items=list(items),
        )
    sys.exit(return_code)


@agent_state_group.command("remove")
@click.option("--agent-id", required=True, help="Agent identifier.")
@click.option("--relay-session-id", default=None, help="Relay session identifier.")
@click.option("--section", required=True, help="Section key.")
@click.option("--pattern", required=True, help="String or regex pattern.")
@click.option("--regex", is_flag=True, help="Treat pattern as regex.")
@click.option("--sync-to-project", is_flag=True, help="Apply the same change to project state.")
@click.pass_context
def cmd_agent_state_remove(
    ctx: click.Context,
    agent_id: str,
    relay_session_id: str | None,
    section: str,
    pattern: str,
    regex: bool,
    sync_to_project: bool,
) -> None:
    """Remove items from a section in agent-specific state."""
    app = _get_ctx(ctx)
    target = _agent_state_path(
        app.memory_dir,
        agent_id=agent_id,
        relay_session_id=relay_session_id,
        for_write=True,
    )
    state.ensure_state_file(target)
    return_code = state.cmd_remove(
        state_path=target,
        section=section,
        pattern=pattern,
        regex=regex,
    )
    if return_code == 0 and sync_to_project:
        return_code = state.cmd_remove(
            state_path=_state_path(app.memory_dir),
            section=section,
            pattern=pattern,
            regex=regex,
        )
    sys.exit(return_code)


@main.command("auto-restore")
@click.option("--agent-id", default=None, help="Agent identifier.")
@click.option("--relay-session-id", default=None, help="Relay session identifier.")
@click.option("--max-evidence-notes", type=int, default=3, show_default=True)
@click.option("--max-lines", type=int, default=6, show_default=True)
@click.option(
    "--include-project-state/--no-include-project-state",
    default=True,
    show_default=True,
)
@click.option(
    "--include-agent-state/--no-include-agent-state",
    default=True,
    show_default=True,
)
@click.option("--json", "as_json", is_flag=True, help="Output JSON.")
@click.pass_context
def cmd_auto_restore(
    ctx: click.Context,
    agent_id: str | None,
    relay_session_id: str | None,
    max_evidence_notes: int,
    max_lines: int,
    include_project_state: bool,
    include_agent_state: bool,
    as_json: bool,
) -> None:
    """Restore active context from state and related notes."""
    app = _get_ctx(ctx)
    payload = state.auto_restore(
        memory_dir=app.memory_dir,
        agent_id=agent_id,
        relay_session_id=relay_session_id,
        max_evidence_notes=max_evidence_notes,
        max_lines=max_lines,
        include_project_state=include_project_state,
        include_agent_state=include_agent_state,
    )
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    click.echo(f"restored_task_count: {payload.get('restored_task_count', 0)}")
    click.echo(f"total_notes_referenced: {payload.get('total_notes_referenced', 0)}")
    warnings = payload.get("warnings", [])
    if isinstance(warnings, list):
        for warning in warnings:
            click.echo(f"Warning: {warning}", err=True)


@main.command("search")
@click.option("--query", required=True, help="Search query.")
@click.option("--task-id", default=None, help="Filter by task ID.")
@click.option("--agent-id", default=None, help="Filter by agent ID.")
@click.option("--relay-session-id", default=None, help="Filter by relay session ID.")
@click.option("--top", type=int, default=None, help="Number of results.")
@click.option("--snippets", type=int, default=None, help="Snippets per result.")
@click.option(
    "--engine",
    type=click.Choice(["auto", "index", "hybrid", "rg", "python"]),
    default="auto",
    show_default=True,
)
@click.option("--explain", is_flag=True, help="Show expansion info.")
@click.option("--prefer-recent", is_flag=True, help="Apply recency boost.")
@click.option("--json", "as_json", is_flag=True, help="Output JSON.")
@click.pass_context
def cmd_search(
    ctx: click.Context,
    query: str,
    task_id: str | None,
    agent_id: str | None,
    relay_session_id: str | None,
    top: int | None,
    snippets: int | None,
    engine: str,
    explain: bool,
    prefer_recent: bool,
    as_json: bool,
) -> None:
    """Search notes."""
    app = _get_ctx(ctx)

    try:
        payload = search.search(
            query=query,
            memory_dir=app.memory_dir,
            task_id=task_id,
            agent_id=agent_id,
            relay_session_id=relay_session_id,
            engine=engine,
            top=top,
            snippets=snippets,
            prefer_recent=prefer_recent,
            explain=explain,
        )
    except QueryParseError as exc:
        raise click.UsageError(f"Invalid query syntax: {exc}") from exc

    warnings = cast(list[str], payload.get("warnings", []))
    for warning in warnings:
        click.echo(f"Warning: {warning}", err=True)

    rows = _normalize_search_results(payload, explain=explain)
    expanded_terms = _dedupe_keep_order(cast(list[str], payload.get("expanded_terms", [])))

    if as_json:
        output = {
            "engine": payload.get("engine"),
            "query": query,
            "expanded_terms": expanded_terms,
            "feedback_source_note": payload.get("feedback_source_note"),
            "feedback_terms_used": payload.get("feedback_terms_used", []),
            "warnings": warnings,
            "results": rows,
        }
        click.echo(json.dumps(output, ensure_ascii=False, indent=2))
        return

    if explain:
        if expanded_terms:
            click.echo(f"Expanded terms ({len(expanded_terms)}): {', '.join(expanded_terms)}")
        else:
            click.echo("Expanded terms (0):")

    if not rows:
        click.echo("No matches.")
        return

    for row in rows:
        score = float(row.get("score", 0.0))
        path = str(row.get("path", ""))
        title = str(row.get("title") or "(untitled)")
        date = str(row.get("date") or "-")
        click.echo(f"[{score:.3f}] {path} — {title} ({date})")
        snippets_list = row.get("snippets", [])
        if isinstance(snippets_list, list):
            for snippet in snippets_list:
                click.echo(f"  {snippet}")


@main.group("index")
def index_group() -> None:
    """Index operations."""


@index_group.command("build")
@click.option("--since", default=None, help="Only include notes on/after YYYY-MM-DD.")
@click.option("--no-dense", is_flag=True, help="Skip dense embedding generation.")
@click.option("--dry-run", is_flag=True, help="List notes that would be indexed.")
@click.pass_context
def cmd_index_build(
    ctx: click.Context,
    since: str | None,
    no_dense: bool,
    dry_run: bool,
) -> None:
    """Rebuild index."""
    app = _get_ctx(ctx)

    if dry_run:
        notes = index.list_notes(app.memory_dir)
        filtered = _filter_notes_by_since(notes, since)
        for note_path in filtered:
            click.echo(str(note_path))
        return

    try:
        entries = index.rebuild_index(
            index_path=_index_path(app.memory_dir),
            dailynote_dir=app.memory_dir,
            since=since,
            no_dense=no_dense,
        )
    except ValueError as exc:
        raise click.UsageError(str(exc)) from exc

    _vlog(app, f"Indexed entries: {len(entries)}")
    click.echo(str(_index_path(app.memory_dir)))


@index_group.command("upsert")
@click.option(
    "--note", "note_path", required=True, type=click.Path(path_type=Path), help="Note path."
)
@click.option("--task-id", default=None, help="Task identifier.")
@click.option("--agent-id", default=None, help="Agent identifier.")
@click.option("--relay-session-id", default=None, help="Relay session identifier.")
@click.option("--no-dense", is_flag=True, help="Skip dense embedding generation.")
@click.pass_context
def cmd_index_upsert(
    ctx: click.Context,
    note_path: Path,
    task_id: str | None,
    agent_id: str | None,
    relay_session_id: str | None,
    no_dense: bool,
) -> None:
    """Upsert one note into index."""
    app = _get_ctx(ctx)

    try:
        index.index_note(
            note_path=note_path,
            index_path=_index_path(app.memory_dir),
            dailynote_dir=app.memory_dir,
            task_id=task_id,
            agent_id=agent_id,
            relay_session_id=relay_session_id,
            no_dense=no_dense,
        )
    except FileNotFoundError as exc:
        raise click.UsageError(str(exc)) from exc

    click.echo(str(_index_path(app.memory_dir)))


@main.command("evidence")
@click.option("--query", required=True, help="Search query.")
@click.option(
    "--paths", "paths_opt", type=click.Path(path_type=Path), multiple=True, help="Note path(s)."
)
@click.argument("paths_arg", nargs=-1, type=click.Path(path_type=Path))
@click.option("--max-lines", type=int, default=8, show_default=True)
@click.pass_context
def cmd_evidence(
    ctx: click.Context,
    query: str,
    paths_opt: tuple[Path, ...],
    paths_arg: tuple[Path, ...],
    max_lines: int,
) -> None:
    """Generate evidence pack."""
    _ = _get_ctx(ctx)
    paths = list(paths_opt) + list(paths_arg)
    if not paths:
        raise click.UsageError("At least one path is required via --paths.")

    try:
        pack = evidence.generate_evidence_pack(query=query, paths=paths, max_lines=max_lines)
    except QueryParseError as exc:
        raise click.UsageError(f"Invalid query syntax: {exc}") from exc

    click.echo(pack, nl=False)


def _run_server(
    run_server: Any, memory_dir: Path, transport: str, port: int, verbose: bool
) -> None:
    params: Mapping[str, inspect.Parameter]
    try:
        params = inspect.signature(run_server).parameters
    except (TypeError, ValueError):
        params = {}

    kwargs: dict[str, Any] = {}
    if "memory_dir" in params:
        kwargs["memory_dir"] = memory_dir
    if "transport" in params:
        kwargs["transport"] = transport
    if "port" in params:
        kwargs["port"] = port
    if "verbose" in params:
        kwargs["verbose"] = verbose

    if kwargs:
        run_server(**kwargs)
    else:
        run_server()


@main.command("serve")
@click.option(
    "--transport",
    type=click.Choice(["stdio", "streamable-http"]),
    default="stdio",
    show_default=True,
)
@click.option("--port", type=int, default=8000, show_default=True)
@click.pass_context
def cmd_serve(ctx: click.Context, transport: str, port: int) -> None:
    """Start MCP server."""
    app = _get_ctx(ctx)

    try:
        from agentic_memory.server import run_server
    except Exception as exc:
        raise click.ClickException(
            f"Failed to import agentic_memory.server.run_server: {exc}"
        ) from exc

    _run_server(
        run_server=run_server,
        memory_dir=app.memory_dir,
        transport=transport,
        port=port,
        verbose=app.verbose,
    )


@main.command("version")
def cmd_version() -> None:
    """Show package version."""
    click.echo(__version__)


if __name__ == "__main__":
    main()
