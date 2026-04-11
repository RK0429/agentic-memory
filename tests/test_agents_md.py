from __future__ import annotations

from pathlib import Path

import pytest

from agentic_memory.core.config import PROMOTED_VALUES_BEGIN, PROMOTED_VALUES_END
from agentic_memory.core.values import AgentsMdAdapter, SourceType, ValuesEntry


def _agents_content(*entries: str) -> str:
    body = "\n".join(entries)
    middle = f"{body}\n" if body else ""
    return f"# Agent Rules\n\n{PROMOTED_VALUES_BEGIN}\n{middle}{PROMOTED_VALUES_END}\n"


def _promoted_entry(description: str, *, promoted: bool = True) -> ValuesEntry:
    return ValuesEntry(
        description=description,
        category="workflow",
        confidence=0.9,
        evidence=[],
        total_evidence_count=6,
        source_type=SourceType.USER_TAUGHT,
        promoted=promoted,
        promoted_confidence=0.9,
    )


def test_resolve_agents_md_path_uses_env_then_symlink(
    tmp_path: Path,
    tmp_memory_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = AgentsMdAdapter()
    explicit = tmp_path / "explicit-agents.md"
    explicit.write_text(_agents_content(), encoding="utf-8")
    monkeypatch.setenv("AGENTS_MD_PATH", str(explicit))

    assert adapter.resolve_agents_md_path(tmp_memory_dir) == explicit

    monkeypatch.delenv("AGENTS_MD_PATH")
    target = tmp_memory_dir.parent / "AGENTS.md"
    target.write_text(_agents_content(), encoding="utf-8")
    claude_path = tmp_memory_dir.parent / "CLAUDE.md"
    claude_path.unlink(missing_ok=True)
    target.unlink()
    external_target = tmp_path / "repo-agents.md"
    external_target.write_text(_agents_content(), encoding="utf-8")
    claude_path.symlink_to(external_target)

    assert adapter.resolve_agents_md_path(tmp_memory_dir) == external_target


_ANNOTATED_BEGIN = "<!-- BEGIN:PROMOTED_VALUES (agentic-memory managed — do not edit manually) -->"
_ANNOTATED_END = "<!-- END:PROMOTED_VALUES (agentic-memory managed) -->"


@pytest.mark.parametrize(
    ("begin_marker", "end_marker"),
    [
        pytest.param(PROMOTED_VALUES_BEGIN, PROMOTED_VALUES_END, id="bare"),
        pytest.param(_ANNOTATED_BEGIN, PROMOTED_VALUES_END, id="annotated-begin"),
        pytest.param(PROMOTED_VALUES_BEGIN, _ANNOTATED_END, id="annotated-end"),
        pytest.param(_ANNOTATED_BEGIN, _ANNOTATED_END, id="fully-annotated"),
    ],
)
def test_list_append_and_remove_entries(tmp_path: Path, begin_marker: str, end_marker: str) -> None:
    """CRUD operations must work for both bare and hand-annotated marker lines.

    Some workspaces hand-annotate the begin/end markers with hints such as
    ``(agentic-memory managed — do not edit manually)`` to discourage manual
    edits. The adapter must recognize these as the existing block instead of
    raising "missing promoted values markers", and must leave the annotation
    text untouched.
    """

    adapter = AgentsMdAdapter()
    agents_path = tmp_path / "AGENTS.md"
    agents_path.write_text(
        f"# Agent Rules\n\n{begin_marker}\n- [v-1] existing\n{end_marker}\n",
        encoding="utf-8",
    )

    assert adapter.list_entries(agents_path) == ["- [v-1] existing"]

    adapter.append_entry(agents_path, "new value", "v-2")
    assert adapter.list_entries(agents_path) == [
        "- [v-1] existing",
        "- [v-2] new value",
    ]

    # The original marker lines themselves must remain untouched, and there
    # must be exactly one BEGIN/END pair regardless of annotation form.
    content = agents_path.read_text(encoding="utf-8")
    assert begin_marker in content
    assert end_marker in content
    assert content.count("BEGIN:PROMOTED_VALUES") == 1
    assert content.count("END:PROMOTED_VALUES") == 1

    assert adapter.remove_entry(agents_path, "v-1") is True
    assert adapter.remove_entry(agents_path, "v-missing") is False
    assert adapter.list_entries(agents_path) == ["- [v-2] new value"]


def test_lock_dir_places_lock_outside_agents_md_directory(tmp_path: Path) -> None:
    """When callers pass `lock_dir`, the AGENTS.md.lock file must not appear
    next to AGENTS.md. Production callers (promote/demote/delete/health) rely
    on this to keep the workspace root clean."""
    adapter = AgentsMdAdapter()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    agents_path = workspace / "AGENTS.md"
    agents_path.write_text(_agents_content(), encoding="utf-8")

    memory_dir = workspace / "memory"
    memory_dir.mkdir()

    adapter.append_entry(agents_path, "new value", "v-1", lock_dir=memory_dir)
    adapter.update_entry(agents_path, "updated value", "v-1", lock_dir=memory_dir)
    adapter.remove_entry(agents_path, "v-1", lock_dir=memory_dir)

    # The workspace directory containing AGENTS.md must not be polluted with
    # the implementation-detail lock file.
    assert not (workspace / "AGENTS.md.lock").exists()

    # The lock file lives inside memory_dir, which is already gitignored by
    # typical agentic-workspace setups.
    assert (memory_dir / "_agents_md.lock").exists()

    # Only AGENTS.md itself (and memory/) remain at the workspace level.
    assert sorted(p.name for p in workspace.iterdir()) == ["AGENTS.md", "memory"]


def test_adapter_requires_valid_markers(tmp_path: Path) -> None:
    adapter = AgentsMdAdapter()
    agents_path = tmp_path / "AGENTS.md"
    agents_path.write_text("# Agent Rules\n", encoding="utf-8")

    with pytest.raises(ValueError, match="missing promoted values markers"):
        adapter.list_entries(agents_path)

    malformed = tmp_path / "malformed.md"
    malformed.write_text(
        f"# Agent Rules\n{PROMOTED_VALUES_END}\n{PROMOTED_VALUES_BEGIN}\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="markers are malformed"):
        adapter.append_entry(malformed, "bad order", "v-1")


def test_sync_check_reports_orphans_and_missing(tmp_path: Path) -> None:
    adapter = AgentsMdAdapter()
    agents_path = tmp_path / "AGENTS.md"
    in_sync = _promoted_entry("in sync")
    missing = _promoted_entry("missing")
    agents_path.write_text(
        _agents_content(
            f"- [{in_sync.id}] in sync",
            "- [v-orphan] orphan entry",
        ),
        encoding="utf-8",
    )

    result = adapter.sync_check(agents_path, [in_sync, missing])

    assert result == {
        "orphan_in_agents_md": ["v-orphan"],
        "missing_in_agents_md": [str(missing.id)],
        "description_mismatches": [],
    }


def test_sync_check_compares_projected_descriptions(tmp_path: Path) -> None:
    adapter = AgentsMdAdapter()
    agents_path = tmp_path / "AGENTS.md"
    long_description = "Line one\nLine two <!-- comment --> " + ("x" * 220)
    projected = adapter.project_description(long_description)
    entry = _promoted_entry(long_description)
    mismatched = _promoted_entry("Prefer simpler descriptions")
    agents_path.write_text(
        _agents_content(
            f"- [{entry.id}] {projected}",
            f"- [{mismatched.id}] stale description",
        ),
        encoding="utf-8",
    )

    result = adapter.sync_check(agents_path, [entry, mismatched])

    assert result["orphan_in_agents_md"] == []
    assert result["missing_in_agents_md"] == []
    assert result["description_mismatches"] == [
        {
            "id": str(mismatched.id),
            "agents_md_description": "stale description",
            "projected_description": "Prefer simpler descriptions",
        }
    ]
