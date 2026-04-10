"""Integrity checks for agentic-memory data."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agentic_memory.core import index as index_module
from agentic_memory.core import signals, state
from agentic_memory.core.index_timestamps import (
    INDEXED_AT_TOLERANCE_SECONDS,
    parse_indexed_at,
)
from agentic_memory.core.knowledge import KnowledgeEntry, KnowledgeRepository
from agentic_memory.core.stats import _iter_note_paths, _normalize_note_path
from agentic_memory.core.values import AgentsMdAdapter, ValuesRepository


def _resolve_note_path(path_text: str, memory_dir: Path) -> Path:
    candidate = Path(path_text)
    if candidate.is_absolute():
        return candidate.resolve()

    parent_dir = memory_dir.resolve().parent
    if candidate.parts and candidate.parts[0] == memory_dir.name:
        primary = parent_dir / candidate
        secondary = memory_dir / candidate
    else:
        primary = memory_dir / candidate
        secondary = parent_dir / candidate

    for option in (primary, secondary):
        resolved = option.resolve()
        if resolved.exists():
            return resolved
    return primary.resolve()


def _is_within_memory_dir(path: Path, memory_dir: Path) -> bool:
    try:
        path.resolve().relative_to(memory_dir.resolve())
        return True
    except ValueError:
        return False


def _load_index_entries(index_path: Path) -> tuple[list[dict[str, Any]], str | None]:
    if not index_path.exists():
        return [], None
    try:
        return signals.load_index(index_path), None
    except (FileNotFoundError, ValueError) as exc:
        return [], str(exc)


def _state_is_valid(state_path: Path) -> bool:
    if not state_path.exists() or not state_path.is_file():
        return False
    try:
        loaded = state.load_state(state_path)
    except OSError:
        return False
    return set(state.SECTION_ORDER).issubset(loaded)


def _config_is_valid(config_path: Path) -> tuple[bool, str | None]:
    """Check config file validity and return (is_valid, reason_if_invalid)."""
    if not config_path.exists():
        return False, "config file not found"
    if not config_path.is_file():
        return False, "config path is not a file"
    try:
        loaded = json.loads(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        return False, f"cannot read config file: {exc}"
    except json.JSONDecodeError as exc:
        return False, f"invalid JSON: {exc}"
    if not isinstance(loaded, dict):
        return False, f"expected JSON object, got {type(loaded).__name__}"
    return True, None


def _resolve_entry_path(path_text: str, memory_dir: Path, entries_dir: Path) -> Path:
    candidate = Path(path_text)
    if candidate.is_absolute():
        return candidate.resolve()
    if candidate.parts and candidate.parts[0] == memory_dir.name:
        return (memory_dir.parent / candidate).resolve()
    if candidate.parts and candidate.parts[0] == entries_dir.name:
        return (memory_dir / candidate).resolve()
    return (entries_dir / candidate.name).resolve()


def _relative_to_memory_dir(path: Path, memory_dir: Path) -> str:
    try:
        return str(path.resolve().relative_to(memory_dir.resolve()))
    except ValueError:
        return str(path)


def _entry_id_from_path(path: Path) -> str | None:
    if path.suffix != ".md":
        return None
    return path.stem or None


def _kv_index_health_check(
    memory_dir: Path,
    *,
    index_path: Path,
    entries_dir: Path,
) -> dict[str, Any]:
    files = sorted(
        path
        for path in entries_dir.glob("*.md")
        if entries_dir.exists() and path.is_file() and not path.name.startswith("_")
    )
    if not index_path.exists():
        orphan_files = [_relative_to_memory_dir(path, memory_dir) for path in files]
        status = "正常" if not orphan_files else "要確認"
        return {
            "index_exists": False,
            "orphan_entries": [],
            "orphan_files": orphan_files,
            "summary": (f"{status}: orphan_entries 0 件, orphan_files {len(orphan_files)} 件。"),
        }

    rows = index_module._read_index_rows(index_path)
    indexed_paths: set[Path] = set()
    orphan_entries: list[dict[str, str]] = []
    for row in rows:
        path_value = str(row.get("path", "")).strip()
        entry_id = str(row.get("id", "")).strip() or None
        if path_value:
            resolved = _resolve_entry_path(path_value, memory_dir, entries_dir)
        elif entry_id is not None:
            resolved = (entries_dir / f"{entry_id}.md").resolve()
        else:
            orphan_entries.append({"id": "", "path": ""})
            continue

        if not _is_within_memory_dir(resolved, memory_dir) or not resolved.exists():
            orphan_entries.append(
                {
                    "id": entry_id or (_entry_id_from_path(resolved) or ""),
                    "path": _relative_to_memory_dir(resolved, memory_dir),
                }
            )
            continue
        indexed_paths.add(resolved.resolve())

    orphan_files = [
        _relative_to_memory_dir(path, memory_dir)
        for path in files
        if path.resolve() not in indexed_paths
    ]
    orphan_entries = sorted(orphan_entries, key=lambda item: (item["id"], item["path"]))
    orphan_files = sorted(set(orphan_files))
    status = "正常" if not orphan_entries and not orphan_files else "要確認"
    return {
        "index_exists": True,
        "orphan_entries": orphan_entries,
        "orphan_files": orphan_files,
        "summary": (
            f"{status}: orphan_entries {len(orphan_entries)} 件, "
            f"orphan_files {len(orphan_files)} 件。"
        ),
    }


def _knowledge_related_health_check(memory_dir: Path) -> dict[str, Any]:
    entries = KnowledgeRepository(memory_dir).list_all()
    entries_by_id = {str(entry.id): entry for entry in entries}
    orphan_links: list[dict[str, str]] = []
    unidirectional_links: list[dict[str, str]] = []

    for entry in entries:
        source_id = str(entry.id)
        for related_id in [str(related_id) for related_id in entry.related]:
            target = entries_by_id.get(related_id)
            if target is None:
                orphan_links.append({"source_id": source_id, "target_id": related_id})
                continue
            target_related = {str(candidate) for candidate in target.related}
            if source_id not in target_related:
                unidirectional_links.append({"source_id": source_id, "target_id": related_id})

    orphan_links = sorted(orphan_links, key=lambda item: (item["source_id"], item["target_id"]))
    unidirectional_links = sorted(
        unidirectional_links,
        key=lambda item: (item["source_id"], item["target_id"]),
    )
    status = "正常" if not orphan_links and not unidirectional_links else "要確認"
    return {
        "orphan_links": orphan_links,
        "unidirectional_links": unidirectional_links,
        "summary": (
            f"{status}: orphan_links {len(orphan_links)} 件, "
            f"unidirectional_links {len(unidirectional_links)} 件。"
        ),
    }


def _promoted_values_sync_health_check(memory_dir: Path) -> dict[str, Any]:
    repository = ValuesRepository(memory_dir)
    promoted_entries = [entry for entry in repository.list_all() if entry.promoted]
    adapter = AgentsMdAdapter()
    agents_md_path = adapter.resolve_agents_md_path(memory_dir)

    if agents_md_path is None:
        missing = sorted(str(entry.id) for entry in promoted_entries)
        status = "正常" if not missing else "要確認"
        return {
            "agents_md_path": None,
            "orphan_in_agents_md": [],
            "missing_in_agents_md": missing,
            "description_mismatches": [],
            "summary": (
                f"{status}: orphan_in_agents_md 0 件, "
                f"missing_in_agents_md {len(missing)} 件, "
                "description_mismatches 0 件。"
            ),
        }

    try:
        sync = adapter.sync_check(agents_md_path, promoted_entries)
    except ValueError as exc:
        return {
            "agents_md_path": str(agents_md_path),
            "orphan_in_agents_md": [],
            "missing_in_agents_md": [],
            "description_mismatches": [],
            "error": str(exc),
            "summary": f"要確認: promoted values sync check に失敗しました ({exc})。",
        }

    status = (
        "正常"
        if (
            not sync["orphan_in_agents_md"]
            and not sync["missing_in_agents_md"]
            and not sync["description_mismatches"]
        )
        else "要確認"
    )
    return {
        "agents_md_path": str(agents_md_path),
        "orphan_in_agents_md": sync["orphan_in_agents_md"],
        "missing_in_agents_md": sync["missing_in_agents_md"],
        "description_mismatches": sync["description_mismatches"],
        "summary": (
            f"{status}: orphan_in_agents_md {len(sync['orphan_in_agents_md'])} 件, "
            f"missing_in_agents_md {len(sync['missing_in_agents_md'])} 件, "
            f"description_mismatches {len(sync['description_mismatches'])} 件。"
        ),
    }


def _update_knowledge_related_links(memory_dir: Path) -> dict[str, int]:
    repository = KnowledgeRepository(memory_dir)
    entries = repository.list_all()
    payloads = {str(entry.id): entry.to_dict() for entry in entries}
    original_related = {
        entry_id: list(payload["related"]) for entry_id, payload in payloads.items()
    }
    orphan_removed = 0
    bidirectional_restored = 0

    for payload in payloads.values():
        cleaned_related: list[str] = []
        for related_id in payload["related"]:
            if related_id not in payloads:
                orphan_removed += 1
                continue
            if related_id not in cleaned_related:
                cleaned_related.append(related_id)
        payload["related"] = cleaned_related

    for source_id, payload in payloads.items():
        for related_id in payload["related"]:
            target_related = payloads[related_id]["related"]
            if source_id not in target_related:
                target_related.append(source_id)
                bidirectional_restored += 1

    changed_ids = {
        entry_id
        for entry_id, payload in payloads.items()
        if payload["related"] != original_related[entry_id]
    }
    for entry_id in changed_ids:
        payload = dict(payloads[entry_id])
        payload["updated_at"] = index_module.now_iso()
        repository.save(KnowledgeEntry.from_dict(payload))

    return {
        "orphan_links_removed": orphan_removed,
        "bidirectional_links_restored": bidirectional_restored,
    }


def _reindex_knowledge_orphan_files(memory_dir: Path, orphan_files: list[str]) -> dict[str, Any]:
    repository = KnowledgeRepository(memory_dir)
    reindexed: list[str] = []
    failed: list[dict[str, str]] = []
    for path_text in orphan_files:
        path = memory_dir / path_text
        entry_id = _entry_id_from_path(path)
        if entry_id is None:
            failed.append({"path": path_text, "error": "invalid knowledge filename"})
            continue
        try:
            repository.save(repository.load(entry_id))
            reindexed.append(path_text)
        except Exception as exc:
            failed.append({"path": path_text, "error": str(exc)})
    return {"reindexed": reindexed, "failed": failed}


def _reindex_values_orphan_files(memory_dir: Path, orphan_files: list[str]) -> dict[str, Any]:
    repository = ValuesRepository(memory_dir)
    reindexed: list[str] = []
    failed: list[dict[str, str]] = []
    for path_text in orphan_files:
        path = memory_dir / path_text
        entry_id = _entry_id_from_path(path)
        if entry_id is None:
            failed.append({"path": path_text, "error": "invalid values filename"})
            continue
        try:
            repository.save(repository.load(entry_id))
            reindexed.append(path_text)
        except Exception as exc:
            failed.append({"path": path_text, "error": str(exc)})
    return {"reindexed": reindexed, "failed": failed}


def _remove_orphan_index_rows(
    index_path: Path,
    orphan_entries: list[dict[str, str]],
) -> int:
    if not orphan_entries or not index_path.exists():
        return 0
    orphan_ids = {item["id"] for item in orphan_entries if item["id"]}
    orphan_paths = {item["path"] for item in orphan_entries if item["path"]}
    rows = index_module._read_index_rows(index_path)
    kept = [
        row
        for row in rows
        if str(row.get("id", "")).strip() not in orphan_ids
        and str(row.get("path", "")).strip() not in orphan_paths
    ]
    removed = len(rows) - len(kept)
    if removed > 0:
        index_module._replace_all(index_path, kept)
    return removed


def _repair_promoted_values_sync(memory_dir: Path) -> dict[str, int]:
    report = _promoted_values_sync_health_check(memory_dir)
    agents_md_path_text = report.get("agents_md_path")
    if not agents_md_path_text or report.get("error") is not None:
        return {
            "orphans_removed_from_agents_md": 0,
            "missing_added_to_agents_md": 0,
            "descriptions_updated_in_agents_md": 0,
        }

    repository = ValuesRepository(memory_dir)
    promoted_entries = {str(entry.id): entry for entry in repository.list_all() if entry.promoted}
    adapter = AgentsMdAdapter()
    agents_md_path = Path(str(agents_md_path_text))
    removed = 0
    added = 0
    updated = 0

    for orphan_id in report["orphan_in_agents_md"]:
        if adapter.remove_entry(agents_md_path, orphan_id):
            removed += 1

    for missing_id in report["missing_in_agents_md"]:
        entry = promoted_entries.get(missing_id)
        if entry is None:
            continue
        adapter.append_entry(
            agents_md_path,
            description=entry.description,
            entry_id=str(entry.id),
        )
        added += 1

    for mismatch in report["description_mismatches"]:
        entry = promoted_entries.get(mismatch["id"])
        if entry is None:
            continue
        if adapter.update_entry(
            agents_md_path,
            description=entry.description,
            entry_id=str(entry.id),
        ):
            updated += 1

    return {
        "orphans_removed_from_agents_md": removed,
        "missing_added_to_agents_md": added,
        "descriptions_updated_in_agents_md": updated,
    }


def health_check(memory_dir: Path) -> dict[str, Any]:
    """Check index/state/config consistency for a memory directory."""
    index_path = memory_dir / "_index.jsonl"
    state_path = memory_dir / "_state.md"
    config_path = memory_dir / "_rag_config.json"

    entries, index_error = _load_index_entries(index_path)
    orphan_entries: list[str] = []
    stale_entries: list[str] = []
    indexed_resolved_paths: set[Path] = set()

    for entry in entries:
        path_text = str(entry.get("path", "")).strip()
        if not path_text:
            continue

        resolved_note_path = _resolve_note_path(path_text, memory_dir)
        if (
            not _is_within_memory_dir(resolved_note_path, memory_dir)
            or not resolved_note_path.exists()
        ):
            orphan_entries.append(path_text)
            continue

        indexed_resolved_paths.add(resolved_note_path.resolve())
        indexed_at = parse_indexed_at(entry.get("indexed_at"))
        try:
            note_mtime = resolved_note_path.stat().st_mtime
        except OSError:
            orphan_entries.append(path_text)
            continue

        if (
            indexed_at is None
            or (note_mtime - indexed_at.timestamp()) > INDEXED_AT_TOLERANCE_SECONDS
        ):
            stale_entries.append(path_text)

    unindexed_notes = [
        _normalize_note_path(note_path, memory_dir)
        for note_path in _iter_note_paths(memory_dir)
        if note_path.resolve() not in indexed_resolved_paths
    ]
    orphan_entries = sorted(set(orphan_entries))
    stale_entries = sorted(set(stale_entries))
    unindexed_notes = sorted(set(unindexed_notes))
    state_valid = _state_is_valid(state_path)
    config_valid, config_reason = _config_is_valid(config_path)
    knowledge_index = _kv_index_health_check(
        memory_dir,
        index_path=memory_dir / "_knowledge.jsonl",
        entries_dir=memory_dir / "knowledge",
    )
    values_index = _kv_index_health_check(
        memory_dir,
        index_path=memory_dir / "_values.jsonl",
        entries_dir=memory_dir / "values",
    )
    knowledge_related = _knowledge_related_health_check(memory_dir)
    promoted_values_sync = _promoted_values_sync_health_check(memory_dir)

    if index_error:
        summary = (
            "要確認: "
            f"インデックスの読み込みに失敗しました ({index_error})。"
            f" 未索引ノート {len(unindexed_notes)} 件。"
        )
    else:
        status = (
            "正常"
            if (
                not orphan_entries
                and not unindexed_notes
                and not stale_entries
                and state_valid
                and config_valid
                and not knowledge_index["orphan_entries"]
                and not knowledge_index["orphan_files"]
                and not values_index["orphan_entries"]
                and not values_index["orphan_files"]
                and not knowledge_related["orphan_links"]
                and not knowledge_related["unidirectional_links"]
                and not promoted_values_sync["orphan_in_agents_md"]
                and not promoted_values_sync["missing_in_agents_md"]
                and not promoted_values_sync["description_mismatches"]
                and promoted_values_sync.get("error") is None
            )
            else "要確認"
        )
        summary = (
            f"{status}: orphan_entries {len(orphan_entries)} 件, "
            f"unindexed_notes {len(unindexed_notes)} 件, "
            f"stale_entries {len(stale_entries)} 件, "
            f"state {'有効' if state_valid else '無効'}, "
            f"config {'有効' if config_valid else '無効'}, "
            "knowledge_orphans "
            f"{len(knowledge_index['orphan_entries'])}/"
            f"{len(knowledge_index['orphan_files'])} 件, "
            "values_orphans "
            f"{len(values_index['orphan_entries'])}/"
            f"{len(values_index['orphan_files'])} 件, "
            "related "
            f"{len(knowledge_related['orphan_links'])}/"
            f"{len(knowledge_related['unidirectional_links'])} 件, "
            "promoted_sync "
            f"{len(promoted_values_sync['orphan_in_agents_md'])}/"
            f"{len(promoted_values_sync['missing_in_agents_md'])}/"
            f"{len(promoted_values_sync['description_mismatches'])} 件。"
        )

    result: dict[str, Any] = {
        "orphan_entries": orphan_entries,
        "unindexed_notes": unindexed_notes,
        "stale_entries": stale_entries,
        "state_valid": state_valid,
        "config_valid": config_valid,
        "knowledge_index": knowledge_index,
        "values_index": values_index,
        "knowledge_related": knowledge_related,
        "promoted_values_sync": promoted_values_sync,
        "summary": summary,
    }
    if config_reason is not None:
        result["config_invalid_reason"] = config_reason
    return result


def fix_issues(
    memory_dir: Path,
    *,
    force_reindex: bool = False,
) -> dict[str, Any]:
    """Re-index stale/unindexed notes and remove orphan index entries.

    When ``force_reindex`` is True, rebuilds the entire index from scratch
    instead of incrementally fixing stale/unindexed entries.  Use this after
    breaking schema changes (e.g. new index fields) that require all entries
    to be regenerated.

    Returns a report with counts of fixed issues.
    """
    index_path = memory_dir / "_index.jsonl"

    if force_reindex:
        notes = index_module.list_notes(memory_dir)
        entries = index_module.rebuild_index(
            index_path=index_path,
            dailynote_dir=memory_dir,
            no_dense=True,
        )
        knowledge_report = _kv_index_health_check(
            memory_dir,
            index_path=memory_dir / "_knowledge.jsonl",
            entries_dir=memory_dir / "knowledge",
        )
        values_report = _kv_index_health_check(
            memory_dir,
            index_path=memory_dir / "_values.jsonl",
            entries_dir=memory_dir / "values",
        )
        knowledge_reindex = _reindex_knowledge_orphan_files(
            memory_dir,
            knowledge_report["orphan_files"],
        )
        values_reindex = _reindex_values_orphan_files(
            memory_dir,
            values_report["orphan_files"],
        )
        knowledge_orphans_removed = _remove_orphan_index_rows(
            memory_dir / "_knowledge.jsonl",
            knowledge_report["orphan_entries"],
        )
        values_orphans_removed = _remove_orphan_index_rows(
            memory_dir / "_values.jsonl",
            values_report["orphan_entries"],
        )
        related_fixes = _update_knowledge_related_links(memory_dir)
        promoted_sync_fixes = _repair_promoted_values_sync(memory_dir)
        post_check = health_check(memory_dir)
        return {
            "reindexed": [_normalize_note_path(p, memory_dir) for p in notes],
            "failed": [],
            "orphans_removed": 0,
            "knowledge_reindexed": knowledge_reindex["reindexed"],
            "knowledge_failed": knowledge_reindex["failed"],
            "knowledge_orphans_removed": knowledge_orphans_removed,
            "values_reindexed": values_reindex["reindexed"],
            "values_failed": values_reindex["failed"],
            "values_orphans_removed": values_orphans_removed,
            **related_fixes,
            **promoted_sync_fixes,
            "force_reindex": True,
            "total_entries": len(entries),
            "post_fix_summary": post_check["summary"],
        }

    report = health_check(memory_dir)
    fixed: dict[str, Any] = {
        "reindexed": [],
        "failed": [],
        "orphans_removed": 0,
        "knowledge_reindexed": [],
        "knowledge_failed": [],
        "knowledge_orphans_removed": 0,
        "values_reindexed": [],
        "values_failed": [],
        "values_orphans_removed": 0,
        "orphan_links_removed": 0,
        "bidirectional_links_restored": 0,
        "orphans_removed_from_agents_md": 0,
        "missing_added_to_agents_md": 0,
        "descriptions_updated_in_agents_md": 0,
    }

    # Re-index stale entries
    paths_to_reindex: list[str] = list(report["stale_entries"]) + list(report["unindexed_notes"])
    for path_text in paths_to_reindex:
        resolved = _resolve_note_path(path_text, memory_dir)
        if not resolved.exists():
            fixed["failed"].append({"path": path_text, "error": "file not found"})
            continue
        try:
            index_module.index_note(
                note_path=resolved,
                index_path=index_path,
                dailynote_dir=memory_dir,
                no_dense=True,
            )
            fixed["reindexed"].append(path_text)
        except Exception as exc:
            fixed["failed"].append({"path": path_text, "error": str(exc)})

    # Remove orphan entries using the index module's lock mechanism
    orphans = set(report["orphan_entries"])
    if orphans:
        entries, _ = _load_index_entries(index_path)
        kept: list[dict[str, Any]] = [
            entry for entry in entries if str(entry.get("path", "")).strip() not in orphans
        ]
        removed = len(entries) - len(kept)
        if removed > 0:
            index_module._replace_all(index_path, kept)
            fixed["orphans_removed"] = removed

    knowledge_reindex = _reindex_knowledge_orphan_files(
        memory_dir,
        report["knowledge_index"]["orphan_files"],
    )
    fixed["knowledge_reindexed"] = knowledge_reindex["reindexed"]
    fixed["knowledge_failed"] = knowledge_reindex["failed"]
    fixed["knowledge_orphans_removed"] = _remove_orphan_index_rows(
        memory_dir / "_knowledge.jsonl",
        report["knowledge_index"]["orphan_entries"],
    )

    values_reindex = _reindex_values_orphan_files(
        memory_dir,
        report["values_index"]["orphan_files"],
    )
    fixed["values_reindexed"] = values_reindex["reindexed"]
    fixed["values_failed"] = values_reindex["failed"]
    fixed["values_orphans_removed"] = _remove_orphan_index_rows(
        memory_dir / "_values.jsonl",
        report["values_index"]["orphan_entries"],
    )

    fixed.update(_update_knowledge_related_links(memory_dir))
    fixed.update(_repair_promoted_values_sync(memory_dir))

    # Re-run health check to get updated summary
    post_check = health_check(memory_dir)
    fixed["post_fix_summary"] = post_check["summary"]
    return fixed
