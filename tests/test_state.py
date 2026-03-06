from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

from agentic_memory.core import index, note, state


def _empty_sections() -> dict[str, list[state.StateItem]]:
    return {sec: [] for sec in state.SECTION_ORDER}


def test_state_item_parse_with_date() -> None:
    item = state.StateItem.parse("- [2026-01-01 10:00] fix auth")
    assert item is not None
    assert item.date == "2026-01-01 10:00"
    assert item.text == "fix auth"


def test_state_item_parse_without_date(monkeypatch) -> None:
    monkeypatch.setattr(state, "now_stamp", lambda: "2026-01-05 12:34")
    item = state.StateItem.parse("- follow up")
    assert item is not None
    assert item.date == "2026-01-05 12:34"
    assert item.text == "follow up"


def test_state_item_parse_placeholder() -> None:
    assert state.StateItem.parse("- (empty)") is None


def test_state_item_from_text(monkeypatch) -> None:
    monkeypatch.setattr(state, "now_stamp", lambda: "2026-01-06 00:00")
    item = state.StateItem.from_text("write tests")
    assert item.date == "2026-01-06 00:00"
    assert item.text == "write tests"


def test_load_state_empty(tmp_path: Path) -> None:
    missing = tmp_path / "_state.md"
    loaded = state.load_state(missing)
    assert set(loaded.keys()) == set(state.SECTION_ORDER)
    assert all(not items for items in loaded.values())


def test_load_state_valid(tmp_path: Path) -> None:
    state_path = tmp_path / "_state.md"
    state_path.write_text(
        (
            "# 作業状態（ローリング）\n\n"
            "Last updated: 2026-01-01 10:00\n\n"
            "## 現在のフォーカス\n\n"
            "- [2026-01-01 10:00] Fix auth\n\n"
            "## 未解決・次のアクション\n\n"
            "- [2026-01-01 10:05] Add tests\n\n"
            "## 主要な判断\n\n"
            "- [2026-01-01 10:10] Keep strict validation\n\n"
            "## 注意点\n\n"
            "- [2026-01-01 10:15] Watch 401 spikes\n\n"
            "## スキルバックログ\n\n"
            "- [2026-01-01 10:20] SKILL: software-engineer\n\n"
            "## 改善バックログ\n\n"
            "- [2026-01-01 10:25] Improve checklist\n"
        ),
        encoding="utf-8",
    )

    loaded = state.load_state(state_path)

    assert loaded[state.STATE_SHORT_KEYS["focus"]][0].text == "Fix auth"
    assert loaded[state.STATE_SHORT_KEYS["open"]][0].text == "Add tests"
    assert loaded[state.STATE_SHORT_KEYS["skills"]][0].text == "SKILL: software-engineer"


def test_save_state_roundtrip(tmp_path: Path) -> None:
    state_path = tmp_path / "_state.md"
    original = _empty_sections()
    original[state.STATE_SHORT_KEYS["focus"]] = [
        state.StateItem(date="2026-01-01 09:00", text="Fix auth")
    ]
    original[state.STATE_SHORT_KEYS["open"]] = [
        state.StateItem(date="2026-01-01 09:10", text="Add tests")
    ]

    state.save_state(state_path, original)
    loaded = state.load_state(state_path)

    assert (
        loaded[state.STATE_SHORT_KEYS["focus"]][0].render()
        == original[state.STATE_SHORT_KEYS["focus"]][0].render()
    )
    assert (
        loaded[state.STATE_SHORT_KEYS["open"]][0].render()
        == original[state.STATE_SHORT_KEYS["open"]][0].render()
    )


def test_deduplicate() -> None:
    items = [
        state.StateItem(date="2026-01-01 09:00", text="Fix   Auth"),
        state.StateItem(date="2026-01-02 09:00", text="fix auth"),
        state.StateItem(date="2026-01-03 09:00", text="Add tests"),
    ]
    deduped = state.deduplicate(items)
    assert len(deduped) == 2
    assert deduped[0].date == "2026-01-02 09:00"
    assert deduped[1].text == "Add tests"


def test_enforce_cap() -> None:
    items = [
        state.StateItem(date="2026-01-01 09:00", text="a"),
        state.StateItem(date="2026-01-01 09:01", text="b"),
        state.StateItem(date="2026-01-01 09:02", text="c"),
    ]
    capped = state.enforce_cap(items, 2)
    assert [item.text for item in capped] == ["a", "b"]


def test_is_stale() -> None:
    old_date = (dt.datetime.now() - dt.timedelta(days=10)).strftime("%Y-%m-%d %H:%M")
    new_date = (dt.datetime.now() - dt.timedelta(days=1)).strftime("%Y-%m-%d %H:%M")
    old_item = state.StateItem(date=old_date, text="old")
    new_item = state.StateItem(date=new_date, text="new")

    assert state.is_stale(old_item, stale_days=7) is True
    assert state.is_stale(new_item, stale_days=7) is False


def test_cmd_show(sample_state_path: Path, capsys) -> None:
    sections_data = _empty_sections()
    sections_data[state.STATE_SHORT_KEYS["focus"]] = [
        state.StateItem(date="2026-01-01 10:00", text="Fix auth")
    ]
    state.save_state(sample_state_path, sections_data)

    rc = state.cmd_show(sample_state_path)
    captured = capsys.readouterr()

    assert rc == 0
    assert "## 現在のフォーカス" in captured.out
    assert "Fix auth" in captured.out


def test_cmd_add(sample_state_path: Path) -> None:
    rc = state.cmd_add(sample_state_path, "focus", ["Review logs"])
    loaded = state.load_state(sample_state_path)

    assert rc == 0
    assert loaded[state.STATE_SHORT_KEYS["focus"]][0].text == "Review logs"


def test_cmd_set(sample_state_path: Path) -> None:
    assert state.cmd_set(sample_state_path, "focus", ["first"]) == 0
    assert state.cmd_set(sample_state_path, "focus", ["second"]) == 0

    loaded = state.load_state(sample_state_path)
    assert len(loaded[state.STATE_SHORT_KEYS["focus"]]) == 1
    assert loaded[state.STATE_SHORT_KEYS["focus"]][0].text == "second"


def test_cmd_remove_substring(sample_state_path: Path, capsys) -> None:
    assert state.cmd_set(sample_state_path, "open", ["Token bug", "Refactor parser"]) == 0
    capsys.readouterr()

    rc = state.cmd_remove(sample_state_path, "open", "token")
    captured = capsys.readouterr()
    loaded = state.load_state(sample_state_path)

    assert rc == 0
    assert captured.out.strip() == "1"
    assert [item.text for item in loaded[state.STATE_SHORT_KEYS["open"]]] == ["Refactor parser"]


def test_cmd_remove_regex(sample_state_path: Path, capsys) -> None:
    assert state.cmd_set(sample_state_path, "open", ["bug-123", "feature-task"]) == 0
    capsys.readouterr()

    rc = state.cmd_remove(sample_state_path, "open", r"bug-\d+", regex=True)
    captured = capsys.readouterr()
    loaded = state.load_state(sample_state_path)

    assert rc == 0
    assert captured.out.strip() == "1"
    assert [item.text for item in loaded[state.STATE_SHORT_KEYS["open"]]] == ["feature-task"]


def test_cmd_prune(sample_state_path: Path, capsys) -> None:
    stale = (dt.datetime.now() - dt.timedelta(days=10)).strftime("%Y-%m-%d")
    fresh = (dt.datetime.now() - dt.timedelta(days=1)).strftime("%Y-%m-%d")
    assert state.cmd_set(sample_state_path, "focus", [f"[{stale}] stale", f"[{fresh}] fresh"]) == 0
    capsys.readouterr()

    rc = state.cmd_prune(sample_state_path, stale_days=7, section="focus")
    captured = capsys.readouterr()
    loaded = state.load_state(sample_state_path)

    assert rc == 0
    assert captured.out.strip() == "1"
    assert [item.text for item in loaded[state.STATE_SHORT_KEYS["focus"]]] == ["fresh"]


def test_cmd_cleanup_removes_ttl_and_generation(tmp_memory_dir: Path, capsys) -> None:
    now = dt.datetime.now()
    ttl_target = tmp_memory_dir / "_state.coder.relay-old.md"
    generation_target = tmp_memory_dir / "_state.coder.md"
    keep_latest = tmp_memory_dir / "_state.coder.relay-new.md"
    keep_other_agent = tmp_memory_dir / "_state.researcher.relay-a.md"

    for path, ts in (
        (ttl_target, (now - dt.timedelta(days=9)).timestamp()),
        (generation_target, (now - dt.timedelta(days=2)).timestamp()),
        (keep_latest, (now - dt.timedelta(days=1)).timestamp()),
        (keep_other_agent, (now - dt.timedelta(days=1)).timestamp()),
    ):
        path.write_text("# agent state\n", encoding="utf-8")
        os.utime(path, (ts, ts))

    rc = state.cmd_cleanup(
        tmp_memory_dir,
        state_ttl_days=7,
        state_max_generations=1,
    )
    captured = capsys.readouterr()

    assert rc == 0
    assert captured.out.strip() == "2"
    assert not ttl_target.exists()
    assert not generation_target.exists()
    assert keep_latest.exists()
    assert keep_other_agent.exists()
    assert (tmp_memory_dir / "_state.md").exists()


def test_cmd_cleanup_dry_run_keeps_files(tmp_memory_dir: Path, capsys) -> None:
    stale = tmp_memory_dir / "_state.coder.relay-stale.md"
    stale.write_text("# stale\n", encoding="utf-8")
    ts = (dt.datetime.now() - dt.timedelta(days=10)).timestamp()
    os.utime(stale, (ts, ts))

    rc = state.cmd_cleanup(
        tmp_memory_dir,
        state_ttl_days=7,
        state_max_generations=20,
        dry_run=True,
    )
    captured = capsys.readouterr()

    assert rc == 0
    assert captured.out.strip() == "1"
    assert stale.exists()


def test_cmd_from_note(sample_state_path: Path, sample_note_path: Path) -> None:
    rc = state.cmd_from_note(
        sample_state_path,
        sample_note_path,
        no_auto_improve=True,
        max_entries=20,
    )
    loaded = state.load_state(sample_state_path)

    assert rc == 0
    assert any(
        item.text == "Add integration coverage." for item in loaded[state.STATE_SHORT_KEYS["focus"]]
    )
    assert any(
        item.text == "Use stricter token validation."
        for item in loaded[state.STATE_SHORT_KEYS["decisions"]]
    )
    assert any(
        item.text == "Monitor 401 spikes after deploy."
        for item in loaded[state.STATE_SHORT_KEYS["pitfalls"]]
    )


def test_resolve_agent_state_path_priority(tmp_memory_dir: Path) -> None:
    shared = tmp_memory_dir / "_state.coder.md"
    session_specific = tmp_memory_dir / "_state.coder.relay-x.md"
    state.ensure_state_file(shared)

    resolved_from_shared = state.resolve_agent_state_path(
        tmp_memory_dir,
        agent_id="coder",
        relay_session_id="relay-x",
        for_write=False,
    )
    assert resolved_from_shared == shared

    state.ensure_state_file(session_specific)
    resolved_from_specific = state.resolve_agent_state_path(
        tmp_memory_dir,
        agent_id="coder",
        relay_session_id="relay-x",
        for_write=False,
    )
    assert resolved_from_specific == session_specific


def test_auto_restore_uses_task_id_from_focus(tmp_memory_dir: Path) -> None:
    created = note.create_note(tmp_memory_dir, title="Restore Target")
    index.index_note(
        note_path=created,
        index_path=tmp_memory_dir / "_index.jsonl",
        dailynote_dir=tmp_memory_dir,
        task_id="TASK-456",
        agent_id="coder",
        relay_session_id="relay-r",
        no_dense=True,
    )

    state.cmd_set(
        tmp_memory_dir / "_state.md",
        "focus",
        ["TASK-456: continue"],
    )

    payload = state.auto_restore(
        memory_dir=tmp_memory_dir,
        agent_id="coder",
        relay_session_id="relay-r",
        include_agent_state=False,
    )
    assert payload["restored_task_count"] >= 1
    active_tasks = payload["active_tasks"]
    assert isinstance(active_tasks, list)
    assert active_tasks[0]["task_id"] == "TASK-456"


def test_cmd_add_replace(sample_state_path: Path) -> None:
    """cmd_add with replace removes matching items before adding new ones."""
    assert state.cmd_set(sample_state_path, "focus", ["v2.0.0 の検証完了", "別のタスク"]) == 0

    rc = state.cmd_add(sample_state_path, "focus", ["v2.0.2 の検証完了"], replace=["検証完了"])
    loaded = state.load_state(sample_state_path)
    focus = loaded[state.STATE_SHORT_KEYS["focus"]]

    assert rc == 0
    assert len(focus) == 2
    assert focus[0].text == "v2.0.2 の検証完了"
    assert focus[1].text == "別のタスク"


def test_cmd_add_replace_none_is_noop(sample_state_path: Path) -> None:
    """cmd_add without replace behaves as before (backwards compatible)."""
    assert state.cmd_set(sample_state_path, "focus", ["existing"]) == 0

    rc = state.cmd_add(sample_state_path, "focus", ["new item"])
    loaded = state.load_state(sample_state_path)
    focus = loaded[state.STATE_SHORT_KEYS["focus"]]

    assert rc == 0
    assert len(focus) == 2
    assert focus[0].text == "new item"
    assert focus[1].text == "existing"


def test_cmd_add_replace_multiple_patterns(sample_state_path: Path) -> None:
    """cmd_add with multiple replace patterns removes all matching items."""
    assert state.cmd_set(sample_state_path, "open", ["agentic-relay 修正", "agentic-memory 修正", "ドキュメント更新"]) == 0

    rc = state.cmd_add(sample_state_path, "open", ["両プロジェクト修正完了"], replace=["agentic-relay", "agentic-memory"])
    loaded = state.load_state(sample_state_path)
    items = loaded[state.STATE_SHORT_KEYS["open"]]

    assert rc == 0
    assert len(items) == 2
    assert items[0].text == "両プロジェクト修正完了"
    assert items[1].text == "ドキュメント更新"
