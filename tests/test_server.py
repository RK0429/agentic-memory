from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

import agentic_memory.server as server_module
from agentic_memory.core import state
from agentic_memory.core.search import COMPACT_EXCLUDE_FIELDS, GLOBAL_COMPACT_EXCLUDE_FIELDS
from agentic_memory.server import (
    _capture_state_cmd,
    _resolve_dir,
    memory_auto_restore,
    memory_evidence,
    memory_health_check,
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


def _state_show_payload(**kwargs: object) -> dict[str, object]:
    return json.loads(memory_state_show(**kwargs))


def _evidence_payload(**kwargs: object) -> dict[str, object]:
    return json.loads(memory_evidence(**kwargs))


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
    assert payload["ok"] is True
    assert payload["status"] == "created"
    assert (memory_dir / "_state.md").exists()


def test_memory_note_new(tmp_memory_dir: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    memory_dir = tmp_memory_dir

    raw = memory_note_new(title="Server Note", memory_dir=str(memory_dir))
    payload = json.loads(raw)
    assert payload["ok"] is True
    assert "path" in payload
    assert payload["title"] == "Server Note"
    assert "date" in payload
    created_path = Path(payload["path"])
    assert created_path.exists()
    assert created_path.suffix == ".md"


def test_memory_note_new_keeps_blank_header_fields_empty(tmp_memory_dir: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)

    payload = json.loads(
        memory_note_new(title="Blank Header Fields", memory_dir=str(tmp_memory_dir))
    )
    created_path = Path(payload["path"])
    index_path = tmp_memory_dir / "_index.jsonl"
    entries = [
        json.loads(line)
        for line in index_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    entry = next(item for item in entries if item["title"] == "Blank Header Fields")

    assert entry["path"].endswith(created_path.name)
    assert entry["context"] == ""
    assert entry["tags"] == []
    assert entry["keywords"] == []


def test_memory_state_show(tmp_memory_dir: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    memory_dir = tmp_memory_dir

    payload = _state_show_payload(memory_dir=str(memory_dir))
    assert payload["ok"] is True
    assert "sections" in payload
    assert "frontmatter" in payload
    assert "現在のフォーカス" in payload["sections"]
    assert "output" not in payload


def test_memory_state_show_renders_frontmatter_section(tmp_memory_dir: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    state.update_distillation_frontmatter(
        tmp_memory_dir / "_state.md",
        last_values_evaluated_at="2026-04-10T11:00:00",
    )

    payload = _state_show_payload(memory_dir=str(tmp_memory_dir), as_json=False)

    assert payload["ok"] is True
    assert "## 蒸留メタデータ" in str(payload["output"])
    assert "last_values_evaluated_at: 2026-04-10T11:00:00" in str(payload["output"])


def test_memory_state_show_as_json_false_includes_rendered_output(
    tmp_memory_dir: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)

    payload = _state_show_payload(memory_dir=str(tmp_memory_dir), as_json=False)
    assert payload["ok"] is True
    assert "sections" not in payload
    assert "現在のフォーカス" in str(payload["output"])
    assert "- (empty)" in str(payload["output"])


def test_memory_state_add(tmp_memory_dir: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    memory_dir = tmp_memory_dir

    result = memory_state_add(
        section="focus", items=["Task A", "Task B"], memory_dir=str(memory_dir)
    )
    result_data = json.loads(result)
    assert result_data["ok"] is True
    assert result_data["path"].endswith("_state.md")
    assert result_data["added"] == 2
    assert result_data["after"] == 2

    payload = _state_show_payload(section="focus", as_json=False, memory_dir=str(memory_dir))
    assert "Task A" in str(payload["output"])
    assert "Task B" in str(payload["output"])


def test_memory_state_add_reports_cap_drop(tmp_memory_dir: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)

    result = memory_state_add(
        section="focus",
        items=["Task 1", "Task 2", "Task 3", "Task 4", "Task 5"],
        memory_dir=str(tmp_memory_dir),
    )

    payload = json.loads(result)
    assert payload["ok"] is True
    assert payload["dropped_by_cap"] == 2
    assert set(payload["dropped_items"]) == {"Task 4", "Task 5"}
    assert payload["after"] == 3


def test_memory_state_add_no_drop_when_under_cap(tmp_memory_dir: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)

    result = memory_state_add(
        section="focus",
        items=["Task A", "Task B"],
        memory_dir=str(tmp_memory_dir),
    )

    payload = json.loads(result)
    assert payload["ok"] is True
    assert payload["dropped_by_cap"] == 0
    assert payload["dropped_items"] == []


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
    assert payload["ok"] is True
    assert payload["removed"] == 1

    payload = _state_show_payload(section="open", as_json=False, memory_dir=str(memory_dir))
    assert "New task" in str(payload["output"])
    assert "Old task" not in str(payload["output"])


def test_memory_state_set(tmp_memory_dir: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    memory_dir = tmp_memory_dir

    memory_state_add(section="focus", items=["Old"], memory_dir=str(memory_dir))
    result = memory_state_set(section="focus", items=["New"], memory_dir=str(memory_dir))
    parsed = json.loads(result)
    assert parsed["ok"] is True
    assert "_state.md" in parsed["path"]
    assert parsed["set"] == 1
    assert parsed["before"] == 1
    assert parsed["after"] == 1

    payload = _state_show_payload(section="focus", as_json=False, memory_dir=str(memory_dir))
    assert "New" in str(payload["output"])
    assert "Old" not in str(payload["output"])


def test_memory_state_remove(tmp_memory_dir: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    memory_dir = tmp_memory_dir

    memory_state_add(section="focus", items=["Keep", "Drop"], memory_dir=str(memory_dir))
    removed = memory_state_remove(section="focus", pattern="Drop", memory_dir=str(memory_dir))
    removed_data = json.loads(removed)
    assert removed_data["ok"] is True
    assert removed_data["removed"] == 1

    payload = _state_show_payload(section="focus", as_json=False, memory_dir=str(memory_dir))
    assert "Keep" in str(payload["output"])
    assert "Drop" not in str(payload["output"])


def test_memory_state_from_note(tmp_memory_dir: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    memory_dir = tmp_memory_dir

    note_path = _write_note(memory_dir, name="from_note.md")
    result = memory_state_from_note(
        note_path=str(note_path),
        auto_improve_mode="skip",
        memory_dir=str(memory_dir),
    )
    result_data = json.loads(result)
    assert result_data["ok"] is True
    assert result_data["path"].endswith("_state.md")
    assert isinstance(result_data["updated_sections"], list)
    assert isinstance(result_data["section_counts"], dict)
    assert result_data["auto_improve"]["mode"] == "skip"

    payload = _state_show_payload(section="open", as_json=False, memory_dir=str(memory_dir))
    assert "write assertions" in str(payload["output"])


def test_memory_state_from_note_defaults_to_detect_mode(tmp_memory_dir: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    memory_dir = tmp_memory_dir

    note_path = _write_note(memory_dir, name="from_note_detect.md")
    payload = json.loads(
        memory_state_from_note(note_path=str(note_path), memory_dir=str(memory_dir))
    )

    assert payload["ok"] is True
    assert payload["auto_improve"]["mode"] == "detect"
    assert payload["auto_improve"]["candidate_count"] == 0


def test_memory_state_from_note_reports_legacy_migration_summary(
    tmp_memory_dir: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    memory_dir = tmp_memory_dir

    signal_note = memory_dir / "2026-03-19" / "1100_sigfb-high.md"
    signal_note.parent.mkdir(parents=True, exist_ok=True)
    signal_note.write_text(
        "# High Severity\n\n"
        "- Date: 2026-03-19\n\n"
        "## スキルフィードバック\n\n"
        "- SIGFB: spawn_agents | failure | one\n"
        "- SIGFB: spawn_agents | failure | two\n"
        "- SIGFB: spawn_agents | failure | three\n",
        encoding="utf-8",
    )
    memory_index_upsert(note_path=str(signal_note), no_dense=True, memory_dir=str(memory_dir))

    legacy_path = memory_dir / "_improvement_backlog_resolved.json"
    legacy_path.write_text(
        json.dumps(
            [
                {
                    "key": (
                        "[severity:high] spawn_agents (score=9) — "
                        "friction(0件) + failure(3件) — "
                        "スキル定義またはガイドラインの見直しを推奨"
                    ),
                    "resolved_at": "2026-03-19 12:00",
                    "text": (
                        "[severity:high] spawn_agents (score=9) — "
                        "friction(0件) + failure(3件) — "
                        "スキル定義またはガイドラインの見直しを推奨"
                    ),
                    "severity": "high",
                    "skill": "spawn_agents",
                }
            ],
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    followup = memory_dir / "2026-03-20" / "1200_followup.md"
    followup.parent.mkdir(parents=True, exist_ok=True)
    followup.write_text(
        "# Followup\n\n- Date: 2026-03-20\n\n## 目標\n\n- keep working\n",
        encoding="utf-8",
    )

    payload = json.loads(
        memory_state_from_note(
            note_path=str(followup),
            auto_improve_mode="add",
            memory_dir=str(memory_dir),
        )
    )

    assert payload["ok"] is True
    migration = payload["auto_improve"]["legacy_migration"]
    assert payload["auto_improve"]["mode"] == "add"
    assert payload["auto_improve"]["candidate_count"] == 0
    assert payload["auto_improve"]["added_count"] == 0
    assert migration["legacy_entries_found"] == 1
    assert migration["migrated_entries"] == 1
    assert migration["migrated_signal_ids"] == 3
    assert migration["remaining_legacy_entries"] == 0
    assert not legacy_path.exists()


def test_memory_state_show_returns_json_error_for_invalid_section(
    tmp_memory_dir: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)

    payload = json.loads(memory_state_show(section="bogus_section", memory_dir=str(tmp_memory_dir)))
    assert payload["error_type"] == "validation_error"
    assert payload["exit_code"] == 2


def test_memory_state_show_as_json_returns_structured_sections(
    tmp_memory_dir: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    memory_state_add(section="focus", items=["Task A"], memory_dir=str(tmp_memory_dir))

    payload = _state_show_payload(
        section="focus",
        as_json=True,
        memory_dir=str(tmp_memory_dir),
    )
    assert payload["ok"] is True
    assert "sections" in payload
    assert "output" not in payload
    assert payload["sections"]["現在のフォーカス"][0]["text"] == "Task A"


def test_memory_search_tools_mark_open_world_and_document_rerank_download() -> None:
    for tool_name in ("memory_search", "memory_search_global"):
        tool = server_module.mcp._tool_manager.get_tool(tool_name)
        description = " ".join(tool.description.lower().split())
        assert tool.annotations.readOnlyHint is True
        assert tool.annotations.destructiveHint is False
        assert tool.annotations.openWorldHint is True
        assert "model download" in description


def test_plural_knowledge_tool_descriptions_document_batch_shape() -> None:
    expectations = {
        "memory_knowledge_add": [
            '`accuracy` defaults to `"uncertain"`',
            '`user_understanding` defaults to `"unknown"`',
            "Top-level `ok` indicates the batch was processed",
        ],
        "memory_knowledge_update": ["`updates`", "AGENTIC_MEMORY_MAX_BATCH_SIZE", "results"],
        "memory_knowledge_delete": ["`ids`", "confirm=false", "would_delete"],
    }

    for tool_name, needles in expectations.items():
        tool = server_module.mcp._tool_manager.get_tool(tool_name)
        description = " ".join(tool.description.split())
        for needle in needles:
            assert needle in description


def test_plural_values_tool_descriptions_document_batch_shape() -> None:
    expectations = {
        "memory_values_add": ["`entries`", "AGENTIC_MEMORY_MAX_BATCH_SIZE", "success_count"],
        "memory_values_update": ["`updates`", "AGENTIC_MEMORY_MAX_BATCH_SIZE", "results"],
        "memory_values_delete": ["`ids`", "confirm=false", "would_delete"],
        "memory_values_promote": ["`ids`", "confirm=false", "would_promote"],
        "memory_values_demote": ["`ids`", "confirm=false", "would_demote"],
    }

    for tool_name, needles in expectations.items():
        tool = server_module.mcp._tool_manager.get_tool(tool_name)
        description = " ".join(tool.description.split())
        for needle in needles:
            assert needle in description


def test_memory_state_from_note_returns_json_error_for_missing_note(
    tmp_memory_dir: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)

    payload = json.loads(
        memory_state_from_note(
            note_path=str(tmp_memory_dir / "missing.md"),
            memory_dir=str(tmp_memory_dir),
        )
    )
    assert payload["error_type"] == "not_found"
    assert payload["exit_code"] == 2


def test_memory_state_from_note_returns_structured_candidates(
    tmp_memory_dir: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    signal_note = tmp_memory_dir / "2026-03-19" / "1100_sigfb-high.md"
    signal_note.parent.mkdir(parents=True, exist_ok=True)
    signal_note.write_text(
        "# High Severity\n\n"
        "- Date: 2026-03-19\n\n"
        "## スキルフィードバック\n\n"
        "- SIGFB: spawn_agents | failure | one\n"
        "- SIGFB: spawn_agents | failure | two\n"
        "- SIGFB: spawn_agents | failure | three\n",
        encoding="utf-8",
    )
    memory_index_upsert(note_path=str(signal_note), no_dense=True, memory_dir=str(tmp_memory_dir))

    payload = json.loads(
        memory_state_from_note(
            note_path=str(signal_note),
            auto_improve_mode="detect",
            memory_dir=str(tmp_memory_dir),
        )
    )
    assert payload["ok"] is True
    assert payload["auto_improve"]["candidate_count"] == 1
    assert payload["auto_improve"]["added_count"] == 0
    assert payload["auto_improve"]["candidates"][0]["skill"] == "spawn_agents"
    assert "warnings" not in payload


def test_memory_search(tmp_memory_dir: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    memory_dir = tmp_memory_dir

    raw = memory_search(query="__no_result_expected__", engine="python", memory_dir=str(memory_dir))
    payload = json.loads(raw)
    assert payload["ok"] is True
    assert payload["query"] == "__no_result_expected__"
    assert isinstance(payload["results"], list)


def test_memory_search_defaults_to_quick_mode(tmp_memory_dir: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    memory_dir = tmp_memory_dir

    raw = memory_search(query="__no_result_expected__", engine="python", memory_dir=str(memory_dir))
    payload = json.loads(raw)
    assert payload["ok"] is True
    # Settings echo-back fields are stripped in compact (quick) mode
    assert "compact" not in payload
    assert "feedback_expand" not in payload


def test_memory_search_global_defaults_to_quick_mode(tmp_memory_dir: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    memory_dir = tmp_memory_dir

    raw = memory_search_global(query="__no_result_expected__", memory_dirs=[str(memory_dir)])
    payload = json.loads(raw)
    assert payload["ok"] is True
    # Settings echo-back fields are stripped in compact (quick) mode
    assert "compact" not in payload
    assert "feedback_expand" not in payload


def test_memory_search_global_quick_strips_global_verbose_fields(
    tmp_memory_dir: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    memory_dir = tmp_memory_dir

    note_path = memory_dir / "global-compact.md"
    note_path.write_text(
        (
            "# Global Compact\n\n"
            "- Date: 2026-03-20\n"
            "- Time: 12:00 - 12:30\n"
            "- Context: cross workspace check\n"
            "- Tags: search,compact\n"
            "- Keywords: validate,global\n\n"
            "## 変更点\n"
            "- Files:\n"
            "  - src/agentic_memory/server.py\n\n"
            "## 判断\n"
            "- keep quick payload small\n\n"
            "## 次のアクション\n"
            "- add regression coverage\n\n"
            "## 注意点・残課題\n"
            "- source_engines is too verbose\n"
        ),
        encoding="utf-8",
    )
    memory_index_upsert(note_path=str(note_path), no_dense=True, memory_dir=str(memory_dir))

    payload = json.loads(
        memory_search_global(
            query="Global Compact",
            memory_dirs=[str(memory_dir)],
            mode="quick",
        )
    )

    assert payload["ok"] is True
    assert "source_engines" not in payload
    assert payload["results"]
    result = payload["results"][0]
    for field in GLOBAL_COMPACT_EXCLUDE_FIELDS:
        assert field not in result


def test_memory_search_global_accepts_single_string_dir(tmp_memory_dir: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)

    payload = json.loads(
        memory_search_global(query="__no_result_expected__", memory_dirs=str(tmp_memory_dir))
    )
    assert payload["ok"] is True
    assert isinstance(payload["results"], list)


def test_memory_search_global_returns_json_error_without_dirs() -> None:
    payload = json.loads(memory_search_global(query="__no_result_expected__"))
    assert payload["error_type"] == "validation_error"
    assert payload["exit_code"] == 2


def test_memory_index_upsert(tmp_memory_dir: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    memory_dir = tmp_memory_dir

    created_path = _note_path(memory_note_new(title="Upsert One", memory_dir=str(memory_dir)))
    raw = memory_index_upsert(
        note_path=str(created_path), no_dense=True, memory_dir=str(memory_dir)
    )

    payload = json.loads(raw)
    assert payload["ok"] is True
    assert isinstance(payload, dict)
    assert payload["path"].endswith(".md")


def test_memory_index_upsert_invalid_task_id_returns_specific_hint(
    tmp_memory_dir: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    memory_dir = tmp_memory_dir

    created_path = _note_path(memory_note_new(title="Bad Task Id", memory_dir=str(memory_dir)))
    payload = json.loads(
        memory_index_upsert(
            note_path=str(created_path),
            task_id="bad-task",
            no_dense=True,
            memory_dir=str(memory_dir),
        )
    )
    assert payload["error_type"] == "validation_error"
    assert "TASK-123" in payload["hint"]


def test_memory_index_upsert_returns_json_error_for_missing_note(
    tmp_memory_dir: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)

    payload = json.loads(
        memory_index_upsert(
            note_path=str(tmp_memory_dir / "missing.md"),
            no_dense=True,
            memory_dir=str(tmp_memory_dir),
        )
    )
    assert payload["error_type"] == "not_found"
    assert payload["exit_code"] == 2


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

    assert full_payload["ok"] is True
    assert compact_payload["ok"] is True
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
    payload = _evidence_payload(
        query="validate",
        paths=[str(note_path)],
        memory_dir=str(memory_dir),
    )
    assert payload["ok"] is True
    assert "# DailyNote Evidence Pack" in str(payload["markdown"])
    assert str(note_path) in str(payload["markdown"])


def test_memory_evidence_accepts_single_string_path(tmp_memory_dir: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    memory_dir = tmp_memory_dir

    note_path = _write_note(memory_dir, name="single-evidence.md")
    payload = _evidence_payload(query="validate", paths=str(note_path), memory_dir=str(memory_dir))
    assert payload["ok"] is True
    assert "# DailyNote Evidence Pack" in str(payload["markdown"])
    assert str(note_path) in str(payload["markdown"])


def test_memory_evidence_resolves_paths_by_task_id(tmp_memory_dir: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    memory_dir = tmp_memory_dir

    note_path = _note_path(
        memory_note_new(title="Evidence by Task", task_id="TASK-401", memory_dir=str(memory_dir))
    )
    payload = _evidence_payload(query="Evidence", task_id="TASK-401", memory_dir=str(memory_dir))
    assert payload["ok"] is True
    assert "# DailyNote Evidence Pack" in str(payload["markdown"])
    assert note_path.name in str(payload["markdown"])


def test_memory_state_show_preserves_warnings_from_state_command(
    tmp_memory_dir: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)

    def fake_cmd_show(*_args: object, **_kwargs: object) -> int:
        print(json.dumps({"sections": {"現在のフォーカス": []}}, ensure_ascii=False))
        print("state warning", file=sys.stderr)
        return 0

    monkeypatch.setattr(server_module.state, "cmd_show", fake_cmd_show)

    payload = json.loads(memory_state_show(memory_dir=str(tmp_memory_dir)))
    assert payload["ok"] is True
    assert payload["warnings"] == ["state warning"]


def test_capture_state_cmd_wraps_non_json_success_output() -> None:
    def fake_cmd(*_args: object, **_kwargs: object) -> int:
        print("plain success output")
        return 0

    payload = json.loads(_capture_state_cmd(fake_cmd))
    assert payload["ok"] is True
    assert payload["raw_output"] == "plain success output"


def test_memory_state_from_note_refreshes_stale_index_entry_after_note_edit(
    tmp_memory_dir: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)

    note_path = _note_path(
        memory_note_new(title="Refresh stale index", memory_dir=str(tmp_memory_dir))
    )
    note_path.write_text(
        "# Refresh stale index\n\n"
        "- Date: 2026-03-20\n"
        "- Time: 15:30 - 15:30\n\n"
        "## 目標\n\n"
        "- reproduce stale index\n\n"
        "## スキルフィードバック\n\n"
        "- SIGFB: memory_state_show | friction | f1\n"
        "- SIGFB: memory_state_show | friction | f2\n"
        "- SIGFB: memory_state_show | friction | f3\n"
        "- SIGFB: memory_state_show | workaround | w1\n",
        encoding="utf-8",
    )
    index_path = tmp_memory_dir / "_index.jsonl"
    stale_entry = json.loads(index_path.read_text(encoding="utf-8").splitlines()[0])
    stale_entry["indexed_at"] = "2026-03-20T00:00:00"
    index_path.write_text(json.dumps(stale_entry, ensure_ascii=False) + "\n", encoding="utf-8")

    payload = json.loads(
        memory_state_from_note(
            note_path=str(note_path),
            auto_improve_mode="add",
            memory_dir=str(tmp_memory_dir),
        )
    )
    assert payload["ok"] is True
    assert payload["auto_improve"]["candidate_count"] == 1
    assert payload["auto_improve"]["added_count"] == 1

    health_payload = json.loads(memory_health_check(memory_dir=str(tmp_memory_dir)))
    assert health_payload["ok"] is True
    assert health_payload["stale_entries"] == []


def test_memory_evidence_resolves_paths_by_relay_task_uuid(
    tmp_memory_dir: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    memory_dir = tmp_memory_dir
    task_id = "6f9619ff-8b86-d011-b42d-00c04fc964ff"

    note_path = _note_path(
        memory_note_new(title="Evidence by Relay Task", task_id=task_id, memory_dir=str(memory_dir))
    )
    payload = _evidence_payload(
        query="Relay Task",
        task_id=task_id.upper(),
        memory_dir=str(memory_dir),
    )
    assert payload["ok"] is True
    assert "# DailyNote Evidence Pack" in str(payload["markdown"])
    assert note_path.name in str(payload["markdown"])


def test_memory_evidence_rejects_task_id_without_indexed_notes(
    tmp_memory_dir: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)

    payload = json.loads(
        memory_evidence(query="missing", task_id="TASK-999", memory_dir=str(tmp_memory_dir))
    )
    assert payload["error_type"] == "not_found"
    assert payload["exit_code"] == 2


def test_memory_evidence_rejects_paths_and_task_id_together(
    tmp_memory_dir: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    memory_dir = tmp_memory_dir

    _ = _note_path(
        memory_note_new(title="Ignored Task Note", task_id="TASK-501", memory_dir=str(memory_dir))
    )
    explicit_path = _write_note(memory_dir, name="explicit-evidence.md")
    payload = _evidence_payload(
        query="validate",
        paths=[str(explicit_path)],
        task_id="TASK-501",
        memory_dir=str(memory_dir),
    )
    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert "Cannot specify both 'paths' and 'task_id'." in payload["message"]
    assert "but not both" in payload["hint"]


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

    payload = json.loads(
        memory_note_new(
            title="Invalid Task Note",
            task_id="not-a-task-id",
            memory_dir=str(tmp_memory_dir),
        )
    )
    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert "TASK-123" in payload["hint"]
    assert list(tmp_memory_dir.glob("*/*.md")) == []


def test_memory_note_new_rolls_back_created_note_when_index_write_fails(
    tmp_memory_dir: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)

    def _raise_oserror(**_: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(server_module.index, "index_note", _raise_oserror)

    payload = json.loads(
        memory_note_new(
            title="Rollback On Index Failure",
            memory_dir=str(tmp_memory_dir),
        )
    )

    assert payload["ok"] is False
    assert payload["error_type"] == "io_error"
    assert payload["message"] == "disk full"
    assert list(tmp_memory_dir.glob("*/*.md")) == []
    assert sorted(path.name for path in tmp_memory_dir.iterdir() if path.is_dir()) == [
        "knowledge",
        "values",
    ]


def test_memory_note_new_rolls_back_created_note_when_index_validation_fails(
    tmp_memory_dir: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)

    def _raise_value_error(**_: object) -> None:
        raise ValueError("bad metadata")

    monkeypatch.setattr(server_module.index, "index_note", _raise_value_error)

    payload = json.loads(
        memory_note_new(
            title="Rollback On Validation Failure",
            memory_dir=str(tmp_memory_dir),
        )
    )

    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert payload["message"] == "bad metadata"
    assert list(tmp_memory_dir.glob("*/*.md")) == []
    assert sorted(path.name for path in tmp_memory_dir.iterdir() if path.is_dir()) == [
        "knowledge",
        "values",
    ]


def test_memory_note_new_reports_cleanup_failure_after_index_write_error(
    tmp_memory_dir: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)

    def _raise_oserror(**_: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(server_module.index, "index_note", _raise_oserror)
    monkeypatch.setattr(
        server_module,
        "_rollback_created_note",
        lambda note_path, memory_dir: "permission denied",
    )

    payload = json.loads(
        memory_note_new(
            title="Rollback Failure Reporting",
            memory_dir=str(tmp_memory_dir),
        )
    )

    assert payload["ok"] is False
    assert payload["error_type"] == "io_error"
    assert "disk full" in payload["message"]
    assert "permission denied" in payload["message"]
    assert "inspect and remove it manually" in payload["hint"]
    assert list(tmp_memory_dir.glob("*/*.md")) != []


def test_memory_note_new_reports_cleanup_failure_after_index_validation_error(
    tmp_memory_dir: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)

    def _raise_value_error(**_: object) -> None:
        raise ValueError("bad metadata")

    monkeypatch.setattr(server_module.index, "index_note", _raise_value_error)
    monkeypatch.setattr(
        server_module,
        "_rollback_created_note",
        lambda note_path, memory_dir: "permission denied",
    )

    payload = json.loads(
        memory_note_new(
            title="Rollback Failure Reporting Validation",
            memory_dir=str(tmp_memory_dir),
        )
    )

    assert payload["ok"] is False
    assert payload["error_type"] == "io_error"
    assert "bad metadata" in payload["message"]
    assert "permission denied" in payload["message"]
    assert "inspect and remove it manually" in payload["hint"]
    assert list(tmp_memory_dir.glob("*/*.md")) != []


def test_memory_search_rejects_invalid_query_task_id_with_format_hint(
    tmp_memory_dir: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)

    with pytest.raises(ValueError, match="relay task UUID"):
        memory_search(
            query="task_id:not-a-task-id",
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
