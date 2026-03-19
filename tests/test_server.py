from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentic_memory.core.search import COMPACT_EXCLUDE_FIELDS
from agentic_memory.server import (
    _resolve_dir,
    memory_auto_restore,
    memory_evidence,
    memory_index_upsert,
    memory_init,
    memory_note_new,
    memory_search,
    memory_search_global,
    memory_state_add,
    memory_state_from_note,
    memory_state_remove,
    memory_state_set,
    memory_state_show,
)


def _note_path(raw: str) -> Path:
    """Extract path from memory_note_new JSON response."""
    return Path(json.loads(raw)["path"])


def _write_note(memory_dir: Path, name: str = "source.md") -> Path:
    note_path = memory_dir / name
    note_path.write_text(
        (
            "# Server Source\n\n"
            "- Date: 2026-03-02\n"
            "- Time: 10:00 - 11:00\n"
            "- Context: test\n\n"
            "## 目標\n- validate server tools\n\n"
            "## 判断\n- call functions directly\n\n"
            "## 次のアクション\n- write assertions\n\n"
            "## 注意点・残課題\n- ensure stable output\n\n"
            "## スキル候補\n- pytest\n"
        ),
        encoding="utf-8",
    )
    return note_path


def test_resolve_dir_explicit(tmp_path: Path, monkeypatch) -> None:
    explicit = tmp_path / "explicit-memory"
    env_path = tmp_path / "env-memory"
    monkeypatch.setenv("MEMORY_DIR", str(env_path))

    resolved = _resolve_dir(str(explicit))
    assert resolved == explicit


def test_resolve_dir_env(tmp_path: Path, monkeypatch) -> None:
    memory_dir = tmp_path / "env-memory"
    monkeypatch.setenv("MEMORY_DIR", str(memory_dir))

    resolved = _resolve_dir()
    assert resolved == memory_dir


def test_memory_init(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    memory_dir = tmp_path / "memory"

    payload = json.loads(memory_init(str(memory_dir)))
    assert payload["status"] == "created"
    assert (memory_dir / "_state.md").exists()


def test_memory_note_new(tmp_memory_dir: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    memory_dir = tmp_memory_dir

    raw = memory_note_new(title="Server Note", memory_dir=str(memory_dir))
    payload = json.loads(raw)
    assert "path" in payload
    assert payload["title"] == "Server Note"
    assert "date" in payload
    created_path = Path(payload["path"])
    assert created_path.exists()
    assert created_path.suffix == ".md"


def test_memory_state_show(tmp_memory_dir: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    memory_dir = tmp_memory_dir

    output = memory_state_show(memory_dir=str(memory_dir))
    assert "現在のフォーカス" in output
    assert "- (empty)" in output


def test_memory_state_add(tmp_memory_dir: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    memory_dir = tmp_memory_dir

    result = memory_state_add(
        section="focus", items=["Task A", "Task B"], memory_dir=str(memory_dir)
    )
    result_data = json.loads(result)
    assert result_data["path"].endswith("_state.md")
    assert result_data["added"] == 2
    assert result_data["after"] == 2

    output = memory_state_show(section="focus", memory_dir=str(memory_dir))
    assert "Task A" in output
    assert "Task B" in output


def test_memory_state_add_accepts_section_alias_and_string_replace(
    tmp_memory_dir: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    memory_dir = tmp_memory_dir

    memory_state_add(section="open", items=["Old task"], memory_dir=str(memory_dir))
    result = memory_state_add(
        section="open_actions",
        items=["New task"],
        replace="Old task",
        memory_dir=str(memory_dir),
    )

    payload = json.loads(result)
    assert payload["removed"] == 1

    output = memory_state_show(section="open", memory_dir=str(memory_dir))
    assert "New task" in output
    assert "Old task" not in output


def test_memory_state_set(tmp_memory_dir: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    memory_dir = tmp_memory_dir

    memory_state_add(section="focus", items=["Old"], memory_dir=str(memory_dir))
    result = memory_state_set(section="focus", items=["New"], memory_dir=str(memory_dir))
    parsed = json.loads(result)
    assert "_state.md" in parsed["path"]
    assert parsed["set"] == 1
    assert parsed["before"] == 1
    assert parsed["after"] == 1

    output = memory_state_show(section="focus", memory_dir=str(memory_dir))
    assert "New" in output
    assert "Old" not in output


def test_memory_state_remove(tmp_memory_dir: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    memory_dir = tmp_memory_dir

    memory_state_add(section="focus", items=["Keep", "Drop"], memory_dir=str(memory_dir))
    removed = memory_state_remove(section="focus", pattern="Drop", memory_dir=str(memory_dir))
    removed_data = json.loads(removed)
    assert removed_data["removed"] == 1

    output = memory_state_show(section="focus", memory_dir=str(memory_dir))
    assert "Keep" in output
    assert "Drop" not in output


def test_memory_state_from_note(tmp_memory_dir: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    memory_dir = tmp_memory_dir

    note_path = _write_note(memory_dir, name="from_note.md")
    result = memory_state_from_note(
        note_path=str(note_path),
        no_auto_improve=True,
        memory_dir=str(memory_dir),
    )
    result_data = json.loads(result)
    assert result_data["path"].endswith("_state.md")
    assert isinstance(result_data["updated_sections"], list)
    assert isinstance(result_data["section_counts"], dict)

    output = memory_state_show(section="open", memory_dir=str(memory_dir))
    assert "write assertions" in output


def test_memory_search(tmp_memory_dir: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    memory_dir = tmp_memory_dir

    raw = memory_search(query="__no_result_expected__", engine="python", memory_dir=str(memory_dir))
    payload = json.loads(raw)
    assert payload["query"] == "__no_result_expected__"
    assert isinstance(payload["results"], list)


def test_memory_search_defaults_to_quick_mode(tmp_memory_dir: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    memory_dir = tmp_memory_dir

    raw = memory_search(query="__no_result_expected__", engine="python", memory_dir=str(memory_dir))
    payload = json.loads(raw)
    # Settings echo-back fields are stripped in compact (quick) mode
    assert "compact" not in payload
    assert "feedback_expand" not in payload


def test_memory_search_global_defaults_to_quick_mode(tmp_memory_dir: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    memory_dir = tmp_memory_dir

    raw = memory_search_global(query="__no_result_expected__", memory_dirs=[str(memory_dir)])
    payload = json.loads(raw)
    # Settings echo-back fields are stripped in compact (quick) mode
    assert "compact" not in payload
    assert "feedback_expand" not in payload


def test_memory_index_upsert(tmp_memory_dir: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    memory_dir = tmp_memory_dir

    created_path = _note_path(memory_note_new(title="Upsert One", memory_dir=str(memory_dir)))
    raw = memory_index_upsert(
        note_path=str(created_path), no_dense=True, memory_dir=str(memory_dir)
    )

    payload = json.loads(raw)
    assert isinstance(payload, dict)
    assert payload["path"].endswith(".md")


def test_index_upsert_compact(tmp_memory_dir: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    memory_dir = tmp_memory_dir

    note_path = _write_note(memory_dir, name="compact-source.md")
    full_payload = json.loads(
        memory_index_upsert(note_path=str(note_path), no_dense=True, memory_dir=str(memory_dir))
    )
    compact_payload = json.loads(
        memory_index_upsert(
            note_path=str(note_path),
            no_dense=True,
            compact=True,
            memory_dir=str(memory_dir),
        )
    )

    assert "auto_keywords" in full_payload
    assert compact_payload["path"].endswith(".md")
    assert compact_payload["title"] == full_payload["title"]
    for field in COMPACT_EXCLUDE_FIELDS:
        assert field in full_payload
        assert field not in compact_payload


def test_memory_evidence(tmp_memory_dir: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    memory_dir = tmp_memory_dir

    note_path = _write_note(memory_dir, name="evidence.md")
    output = memory_evidence(query="validate", paths=[str(note_path)], memory_dir=str(memory_dir))
    assert "# DailyNote Evidence Pack" in output
    assert str(note_path) in output


def test_memory_evidence_accepts_single_string_path(tmp_memory_dir: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    memory_dir = tmp_memory_dir

    note_path = _write_note(memory_dir, name="single-evidence.md")
    output = memory_evidence(query="validate", paths=str(note_path), memory_dir=str(memory_dir))
    assert "# DailyNote Evidence Pack" in output
    assert str(note_path) in output


def test_memory_evidence_resolves_paths_by_task_id(tmp_memory_dir: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    memory_dir = tmp_memory_dir

    note_path = _note_path(
        memory_note_new(title="Evidence by Task", task_id="TASK-401", memory_dir=str(memory_dir))
    )
    output = memory_evidence(query="Evidence", task_id="TASK-401", memory_dir=str(memory_dir))
    assert "# DailyNote Evidence Pack" in output
    assert note_path.name in output


def test_memory_evidence_resolves_paths_by_relay_task_uuid(
    tmp_memory_dir: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    memory_dir = tmp_memory_dir
    task_id = "6f9619ff-8b86-d011-b42d-00c04fc964ff"

    note_path = _note_path(
        memory_note_new(title="Evidence by Relay Task", task_id=task_id, memory_dir=str(memory_dir))
    )
    output = memory_evidence(
        query="Relay Task",
        task_id=task_id.upper(),
        memory_dir=str(memory_dir),
    )
    assert "# DailyNote Evidence Pack" in output
    assert note_path.name in output


def test_memory_evidence_prefers_paths_over_task_id(tmp_memory_dir: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    memory_dir = tmp_memory_dir

    _ = _note_path(
        memory_note_new(title="Ignored Task Note", task_id="TASK-501", memory_dir=str(memory_dir))
    )
    explicit_path = _write_note(memory_dir, name="explicit-evidence.md")
    output = memory_evidence(
        query="validate",
        paths=[str(explicit_path)],
        task_id="TASK-501",
        memory_dir=str(memory_dir),
    )
    assert str(explicit_path) in output
    assert "Ignored Task Note" not in output


def test_memory_note_new_with_agent_metadata(tmp_memory_dir: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    memory_dir = tmp_memory_dir

    created_path = _note_path(
        memory_note_new(
            title="Metadata Note",
            task_id="TASK-111",
            agent_id="coder",
            relay_session_id="relay-a",
            memory_dir=str(memory_dir),
        )
    )
    assert created_path.exists()

    raw = memory_search(
        query="Metadata",
        engine="index",
        task_id="TASK-111",
        agent_id="coder",
        relay_session_id="relay-a",
        memory_dir=str(memory_dir),
    )
    payload = json.loads(raw)
    assert payload["results"]


def test_memory_note_new_accepts_relay_task_uuid(tmp_memory_dir: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    memory_dir = tmp_memory_dir
    task_id = "6f9619ff-8b86-d011-b42d-00c04fc964ff"

    created_path = _note_path(
        memory_note_new(
            title="Relay Metadata Note",
            task_id=task_id.upper(),
            agent_id="coder",
            relay_session_id="relay-a",
            memory_dir=str(memory_dir),
        )
    )
    assert created_path.exists()

    raw = memory_search(
        query="Relay Metadata",
        engine="index",
        task_id=task_id,
        agent_id="coder",
        relay_session_id="relay-a",
        memory_dir=str(memory_dir),
    )
    payload = json.loads(raw)
    assert payload["results"]


@pytest.mark.parametrize(
    ("task_id", "query_task_id", "expected_task_id"),
    [
        ("TASK-222", "TASK-222", "TASK-222"),
        (
            "6f9619ff-8b86-d011-b42d-00c04fc964ff",
            "6F9619FF-8B86-D011-B42D-00C04FC964FF",
            "6f9619ff-8b86-d011-b42d-00c04fc964ff",
        ),
    ],
)
def test_memory_search_query_only_task_id_filter(
    tmp_memory_dir: Path,
    monkeypatch,
    task_id: str,
    query_task_id: str,
    expected_task_id: str,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    memory_dir = tmp_memory_dir

    _note_path(
        memory_note_new(
            title="Query Filter Note",
            task_id=task_id,
            memory_dir=str(memory_dir),
        )
    )

    raw = memory_search(
        query=f"task_id:{query_task_id}",
        memory_dir=str(memory_dir),
    )
    payload = json.loads(raw)

    assert payload["total_found"] == 1
    assert len(payload["results"]) == 1
    assert payload["results"][0]["task_id"] == expected_task_id
    assert payload["filters"]["task_id"] == expected_task_id


def test_memory_note_new_rejects_unknown_task_id_with_format_hint(
    tmp_memory_dir: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)

    with pytest.raises(ValueError, match="relay task UUID"):
        memory_note_new(
            title="Invalid Task Note",
            task_id="not-a-task-id",
            memory_dir=str(tmp_memory_dir),
        )


def test_memory_auto_restore(tmp_memory_dir: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    memory_dir = tmp_memory_dir

    created = _note_path(
        memory_note_new(
            title="Auto Restore Source",
            task_id="TASK-301",
            agent_id="coder",
            relay_session_id="relay-r1",
            memory_dir=str(memory_dir),
        )
    )
    assert created.exists()

    # Set agent state directly via core module (agent_state tools are not exposed via MCP)
    from agentic_memory.core import state as _state

    agent_state_path = _state.resolve_agent_state_path(
        memory_dir=memory_dir,
        agent_id="coder",
        relay_session_id="relay-r1",
        for_write=True,
    )
    _state.ensure_state_file(agent_state_path)
    _state.cmd_set(agent_state_path, section="focus", items=["TASK-301: continue task"])

    raw = memory_auto_restore(
        agent_id="coder",
        relay_session_id="relay-r1",
        memory_dir=str(memory_dir),
    )
    payload = json.loads(raw)
    assert payload["restored_task_count"] >= 1
    assert payload["active_tasks"][0]["task_id"] == "TASK-301"
