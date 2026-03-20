from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

from agentic_memory.core import index, note, state


def _empty_sections() -> dict[str, list[state.StateItem]]:
    return {sec: [] for sec in state.SECTION_ORDER}


def _full_sections(prefix: str, *, task_id: str | None = None) -> dict[str, list[state.StateItem]]:
    sections_data = _empty_sections()
    for short_key, cap in state.STATE_CAPS.items():
        section_name = state.STATE_SHORT_KEYS[short_key]
        items: list[state.StateItem] = []
        for idx in range(cap):
            text = f"{prefix}-{short_key}-{idx}"
            if short_key == "focus" and idx == 0 and task_id is not None:
                text = f"{task_id}: {text}"
            items.append(
                state.StateItem(
                    date=f"2026-01-01 00:{idx:02d}",
                    text=text,
                )
            )
        sections_data[section_name] = items
    return sections_data


def _rendered_line_count(rendered: object) -> int:
    if not isinstance(rendered, dict):
        return 0
    return sum(len(lines) for lines in rendered.values() if isinstance(lines, list))


def _restore_line_count(payload: dict[str, object]) -> int:
    total = _rendered_line_count(payload.get("project_state"))
    total += _rendered_line_count(payload.get("agent_state"))

    active_tasks = payload.get("active_tasks")
    if isinstance(active_tasks, list):
        for task in active_tasks:
            if not isinstance(task, dict):
                continue
            evidence_pack = task.get("evidence_pack")
            if isinstance(evidence_pack, str):
                total += len(evidence_pack.splitlines())
    return total


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


def test_deduplicate_substring_match() -> None:
    items = [
        state.StateItem(
            date="2026-01-01 09:00",
            text="memory_state_remove の戻り値フォーマット",
        ),
        state.StateItem(
            date="2026-01-02 09:00",
            text="memory_state_remove の戻り値フォーマットが他ツールと不整合",
        ),
    ]

    deduped = state.deduplicate(items)

    assert len(deduped) == 1
    assert deduped[0].date == "2026-01-02 09:00"
    assert deduped[0].text == "memory_state_remove の戻り値フォーマットが他ツールと不整合"


def test_enforce_cap() -> None:
    items = [
        state.StateItem(date="2026-01-01 09:00", text="a"),
        state.StateItem(date="2026-01-01 09:01", text="b"),
        state.StateItem(date="2026-01-01 09:02", text="c"),
    ]
    kept, dropped = state.enforce_cap(items, 2)
    assert [item.text for item in kept] == ["a", "b"]
    assert [item.text for item in dropped] == ["c"]


def test_enforce_cap_no_overflow() -> None:
    items = [
        state.StateItem(date="2026-01-01 09:00", text="a"),
    ]
    kept, dropped = state.enforce_cap(items, 3)
    assert [item.text for item in kept] == ["a"]
    assert dropped == []


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
    payload = json.loads(captured.out)

    assert rc == 0
    assert payload["path"] == str(sample_state_path)
    assert payload["section"] == state.STATE_SHORT_KEYS["open"]
    assert payload["removed"] == 1
    assert payload["items"][0].endswith("Token bug")
    assert [item.text for item in loaded[state.STATE_SHORT_KEYS["open"]]] == ["Refactor parser"]


def test_cmd_remove_json_output(sample_state_path: Path, capsys) -> None:
    sections_data = _empty_sections()
    sections_data[state.STATE_SHORT_KEYS["open"]] = [
        state.StateItem(date="2026-01-01 10:00", text="Drop me"),
        state.StateItem(date="2026-01-01 10:01", text="Keep me"),
    ]
    state.save_state(sample_state_path, sections_data)

    rc = state.cmd_remove(sample_state_path, "open", "drop")
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert rc == 0
    assert payload == {
        "path": str(sample_state_path),
        "section": state.STATE_SHORT_KEYS["open"],
        "removed": 1,
        "items": ["[2026-01-01 10:00] Drop me"],
    }


def test_cmd_remove_regex(sample_state_path: Path, capsys) -> None:
    assert state.cmd_set(sample_state_path, "open", ["bug-123", "feature-task"]) == 0
    capsys.readouterr()

    rc = state.cmd_remove(sample_state_path, "open", r"bug-\d+", regex=True)
    captured = capsys.readouterr()
    loaded = state.load_state(sample_state_path)
    payload = json.loads(captured.out)

    assert rc == 0
    assert payload["path"] == str(sample_state_path)
    assert payload["section"] == state.STATE_SHORT_KEYS["open"]
    assert payload["removed"] == 1
    assert payload["items"][0].endswith("bug-123")
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


def test_cmd_from_note(sample_state_path: Path, sample_note_path: Path, capsys) -> None:
    rc = state.cmd_from_note(
        sample_state_path,
        sample_note_path,
        auto_improve_mode="skip",
        max_entries=20,
    )
    loaded = state.load_state(sample_state_path)
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert rc == 0
    assert any(item.text == "Fix login failure" for item in loaded[state.STATE_SHORT_KEYS["focus"]])
    assert any(
        item.text == "Add integration coverage." for item in loaded[state.STATE_SHORT_KEYS["open"]]
    )
    assert any(
        item.text == "Use stricter token validation."
        for item in loaded[state.STATE_SHORT_KEYS["decisions"]]
    )
    assert any(
        item.text == "Monitor 401 spikes after deploy."
        for item in loaded[state.STATE_SHORT_KEYS["pitfalls"]]
    )
    assert payload["auto_improve"]["mode"] == "skip"
    assert "warnings" not in payload
    assert "cap_exceeded" not in payload
    assert "auto_pruned" not in payload


def test_cmd_from_note_rejects_invalid_auto_improve_mode(
    sample_state_path: Path,
    sample_note_path: Path,
    capsys,
) -> None:
    rc = state.cmd_from_note(
        sample_state_path,
        sample_note_path,
        auto_improve_mode="bogus",
    )
    captured = capsys.readouterr()

    assert rc == 2
    assert "Invalid auto_improve_mode:" in captured.err


def test_auto_improve_does_not_readd_resolved_high_severity_item(tmp_memory_dir: Path) -> None:
    """Resolved signals are marked via _sigfb_resolved.json; re-running from_note
    should not regenerate the backlog item because the contributor signals are filtered."""
    note_dir = tmp_memory_dir / "2026-03-19"
    note_dir.mkdir(parents=True, exist_ok=True)
    note_path = note_dir / "1200_sigfb-high.md"
    note_path.write_text(
        "# High Severity\n\n"
        "- Date: 2026-03-19\n\n"
        "## スキルフィードバック\n\n"
        "- SIGFB: spawn_agents | failure | one\n"
        "- SIGFB: spawn_agents | failure | two\n"
        "- SIGFB: spawn_agents | failure | three\n",
        encoding="utf-8",
    )
    # Index the note so skill_feedback entries have IDs
    index.index_note(
        note_path=note_path,
        index_path=tmp_memory_dir / "_index.jsonl",
        dailynote_dir=tmp_memory_dir,
    )
    state_path = tmp_memory_dir / "_state.md"

    rc = state.cmd_from_note(state_path, note_path, auto_improve_mode="add")
    assert rc == 0
    loaded = state.load_state(state_path)
    assert any(
        "spawn_agents" in item.text for item in loaded[state.STATE_SHORT_KEYS["improvements"]]
    )

    rc = state.cmd_remove(state_path, "improvements", "spawn_agents")
    assert rc == 0
    loaded = state.load_state(state_path)
    assert not any(
        "spawn_agents" in item.text for item in loaded[state.STATE_SHORT_KEYS["improvements"]]
    )

    # Verify signals are marked resolved
    resolved = state._load_sigfb_resolved(state_path)
    assert len(resolved) >= 3

    rc = state.cmd_from_note(state_path, note_path, auto_improve_mode="add")
    assert rc == 0
    loaded = state.load_state(state_path)
    assert not any(
        "spawn_agents" in item.text for item in loaded[state.STATE_SHORT_KEYS["improvements"]]
    )


def test_auto_improve_migrates_legacy_resolved_high_severity_item(tmp_memory_dir: Path) -> None:
    legacy_text = (
        "[severity:high] spawn_agents (score=9) — "
        "friction(0件) + failure(3件) — "
        "スキル定義またはガイドラインの見直しを推奨"
    )
    note_dir = tmp_memory_dir / "2026-03-19"
    note_dir.mkdir(parents=True, exist_ok=True)
    note_path = note_dir / "1100_sigfb-high.md"
    note_path.write_text(
        "# High Severity\n\n"
        "- Date: 2026-03-19\n\n"
        "## スキルフィードバック\n\n"
        "- SIGFB: spawn_agents | failure | one\n"
        "- SIGFB: spawn_agents | failure | two\n"
        "- SIGFB: spawn_agents | failure | three\n",
        encoding="utf-8",
    )
    index.index_note(
        note_path=note_path,
        index_path=tmp_memory_dir / "_index.jsonl",
        dailynote_dir=tmp_memory_dir,
    )

    legacy_path = tmp_memory_dir / "_improvement_backlog_resolved.json"
    legacy_path.write_text(
        json.dumps(
            [
                {
                    "key": legacy_text,
                    "resolved_at": "2026-03-19 12:00",
                    "text": legacy_text,
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

    state_path = tmp_memory_dir / "_state.md"
    followup_note = tmp_memory_dir / "2026-03-20" / "1200_followup.md"
    followup_note.parent.mkdir(parents=True, exist_ok=True)
    followup_note.write_text(
        "# Followup\n\n- Date: 2026-03-20\n\n## 目標\n\n- keep working\n",
        encoding="utf-8",
    )

    rc = state.cmd_from_note(state_path, followup_note, auto_improve_mode="add")
    assert rc == 0

    loaded = state.load_state(state_path)
    assert not any(
        "spawn_agents" in item.text for item in loaded[state.STATE_SHORT_KEYS["improvements"]]
    )
    resolved = state._load_sigfb_resolved(state_path)
    assert len(resolved) == 3
    assert not legacy_path.exists()


def test_auto_improve_migrates_legacy_pattern_escalation_resolution(
    tmp_memory_dir: Path,
) -> None:
    legacy_text = (
        "[severity:medium][pattern_escalation] memory_state_add — "
        "friction(4)+workaround(0)の蓄積パターンを検出"
    )
    note_dir = tmp_memory_dir / "2026-03-19"
    note_dir.mkdir(parents=True, exist_ok=True)
    note_path = note_dir / "1100_pattern.md"
    note_path.write_text(
        "# Pattern Escalation\n\n"
        "- Date: 2026-03-19\n\n"
        "## スキルフィードバック\n\n"
        "- SIGFB: memory_state_add | friction | one\n"
        "- SIGFB: memory_state_add | friction | two\n"
        "- SIGFB: memory_state_add | friction | three\n"
        "- SIGFB: memory_state_add | friction | four\n",
        encoding="utf-8",
    )
    index.index_note(
        note_path=note_path,
        index_path=tmp_memory_dir / "_index.jsonl",
        dailynote_dir=tmp_memory_dir,
    )

    legacy_path = tmp_memory_dir / "_improvement_backlog_resolved.json"
    legacy_path.write_text(
        json.dumps(
            [
                {
                    "key": legacy_text,
                    "resolved_at": "2026-03-19 12:00",
                    "text": legacy_text,
                    "severity": "medium",
                    "trigger_type": "pattern_escalation",
                    "skill": "memory_state_add",
                }
            ],
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    state_path = tmp_memory_dir / "_state.md"
    followup_note = tmp_memory_dir / "2026-03-20" / "1200_followup.md"
    followup_note.parent.mkdir(parents=True, exist_ok=True)
    followup_note.write_text(
        "# Followup\n\n- Date: 2026-03-20\n\n## 目標\n\n- keep working\n",
        encoding="utf-8",
    )

    rc = state.cmd_from_note(state_path, followup_note, auto_improve_mode="add")
    assert rc == 0

    loaded = state.load_state(state_path)
    assert not any(
        "memory_state_add" in item.text for item in loaded[state.STATE_SHORT_KEYS["improvements"]]
    )
    resolved = state._load_sigfb_resolved(state_path)
    assert len(resolved) == 4
    assert not legacy_path.exists()


def test_auto_improve_migrates_legacy_gap_expansion_resolution(tmp_memory_dir: Path) -> None:
    legacy_text = "[severity:medium][gap_expansion] _missing_ — gap(4件) — 新モジュール拡張の候補"
    note_dir = tmp_memory_dir / "2026-03-19"
    note_dir.mkdir(parents=True, exist_ok=True)
    note_path = note_dir / "1100_gap.md"
    note_path.write_text(
        "# Gap Expansion\n\n"
        "- Date: 2026-03-19\n\n"
        "## スキルフィードバック\n\n"
        "- SIGFB: _missing_ | gap | one\n"
        "- SIGFB: _missing_ | gap | two\n"
        "- SIGFB: _missing_ | gap | three\n"
        "- SIGFB: _missing_ | gap | four\n",
        encoding="utf-8",
    )
    index.index_note(
        note_path=note_path,
        index_path=tmp_memory_dir / "_index.jsonl",
        dailynote_dir=tmp_memory_dir,
    )

    legacy_path = tmp_memory_dir / "_improvement_backlog_resolved.json"
    legacy_path.write_text(
        json.dumps(
            [
                {
                    "key": legacy_text,
                    "resolved_at": "2026-03-19 12:00",
                    "text": legacy_text,
                    "severity": "medium",
                    "trigger_type": "gap_expansion",
                    "skill": "_missing_",
                }
            ],
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    state_path = tmp_memory_dir / "_state.md"
    followup_note = tmp_memory_dir / "2026-03-20" / "1200_followup.md"
    followup_note.parent.mkdir(parents=True, exist_ok=True)
    followup_note.write_text(
        "# Followup\n\n- Date: 2026-03-20\n\n## 目標\n\n- keep working\n",
        encoding="utf-8",
    )

    rc = state.cmd_from_note(state_path, followup_note, auto_improve_mode="add")
    assert rc == 0

    loaded = state.load_state(state_path)
    assert not any(
        "_missing_" in item.text for item in loaded[state.STATE_SHORT_KEYS["improvements"]]
    )
    resolved = state._load_sigfb_resolved(state_path)
    assert len(resolved) == 4
    assert not legacy_path.exists()


def test_auto_improve_respects_recent_periodic_review_resolution(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    """periodic_review trigger uses _trigger_cooldown.json instead of old resolved mechanism."""
    state_path = tmp_memory_dir / "_state.md"
    index_path = tmp_memory_dir / "_index.jsonl"
    seed_dir = tmp_memory_dir / "2026-03-18"
    seed_dir.mkdir(parents=True, exist_ok=True)
    for idx in range(10):
        np = seed_dir / f"{idx:04d}_seed-{idx}.md"
        np.write_text(
            f"# Seed {idx}\n\n- Date: 2026-03-18\n\n## 目標\n\n- item {idx}\n",
            encoding="utf-8",
        )
        index.index_note(note_path=np, index_path=index_path, dailynote_dir=tmp_memory_dir)

    first_note = tmp_memory_dir / "2026-03-19" / "1200_periodic.md"
    first_note.parent.mkdir(parents=True, exist_ok=True)
    first_note.write_text(
        "# Periodic\n\n- Date: 2026-03-19\n\n## 目標\n\n- trigger periodic review\n",
        encoding="utf-8",
    )
    rc = state.cmd_from_note(state_path, first_note, auto_improve_mode="add")
    assert rc == 0
    loaded = state.load_state(state_path)
    assert any(
        "[periodic_review]" in item.text for item in loaded[state.STATE_SHORT_KEYS["improvements"]]
    )

    monkeypatch.setattr(state, "now_stamp", lambda: "2026-03-19 12:00")
    rc = state.cmd_remove(state_path, "improvements", "[periodic_review]")
    assert rc == 0

    # Verify cooldown was recorded
    cooldown = state._load_trigger_cooldown(state_path)
    assert "periodic_review" in cooldown

    class FrozenDate(dt.date):
        @classmethod
        def today(cls) -> FrozenDate:
            return cls(2026, 3, 19)

    monkeypatch.setattr(state._dt, "date", FrozenDate)

    second_note = tmp_memory_dir / "2026-03-19" / "1201_periodic.md"
    second_note.write_text(
        "# Periodic Again\n\n- Date: 2026-03-19\n\n## 目標\n\n- trigger periodic review again\n",
        encoding="utf-8",
    )
    rc = state.cmd_from_note(state_path, second_note, auto_improve_mode="add")
    assert rc == 0
    loaded = state.load_state(state_path)
    assert not any(
        "[periodic_review]" in item.text for item in loaded[state.STATE_SHORT_KEYS["improvements"]]
    )


def test_auto_improve_migrates_legacy_periodic_review_resolution(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    legacy_text = (
        "[severity:medium][periodic_review] * — "
        "インデックスに10件のエントリ — "
        "全スキル定期レビューを推奨"
    )
    state_path = tmp_memory_dir / "_state.md"
    index_path = tmp_memory_dir / "_index.jsonl"
    seed_dir = tmp_memory_dir / "2026-03-18"
    seed_dir.mkdir(parents=True, exist_ok=True)
    for idx in range(10):
        np = seed_dir / f"{idx:04d}_seed-{idx}.md"
        np.write_text(
            f"# Seed {idx}\n\n- Date: 2026-03-18\n\n## 目標\n\n- item {idx}\n",
            encoding="utf-8",
        )
        index.index_note(note_path=np, index_path=index_path, dailynote_dir=tmp_memory_dir)

    legacy_path = tmp_memory_dir / "_improvement_backlog_resolved.json"
    legacy_path.write_text(
        json.dumps(
            [
                {
                    "key": legacy_text,
                    "resolved_at": "2026-03-19 12:00",
                    "text": legacy_text,
                    "severity": "medium",
                    "trigger_type": "periodic_review",
                    "skill": "*",
                }
            ],
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    class FrozenDate(dt.date):
        @classmethod
        def today(cls) -> FrozenDate:
            return cls(2026, 3, 20)

    monkeypatch.setattr(state._dt, "date", FrozenDate)

    note_path = tmp_memory_dir / "2026-03-20" / "1200_periodic.md"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(
        "# Periodic\n\n- Date: 2026-03-20\n\n## 目標\n\n- trigger periodic review\n",
        encoding="utf-8",
    )
    rc = state.cmd_from_note(state_path, note_path, auto_improve_mode="add")
    assert rc == 0

    loaded = state.load_state(state_path)
    assert not any(
        "[periodic_review]" in item.text for item in loaded[state.STATE_SHORT_KEYS["improvements"]]
    )
    cooldown = state._load_trigger_cooldown(state_path)
    assert cooldown["periodic_review"] == "2026-03-19 12:00"
    assert not legacy_path.exists()


def test_extract_from_note_focus_no_next() -> None:
    note_text = "# Note\n\n## 次のアクション\n- next item\n"

    extracted = state._extract_from_note(note_text)

    assert extracted[state.STATE_SHORT_KEYS["focus"]] == []
    assert extracted[state.STATE_SHORT_KEYS["open"]] == ["next item"]


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


def test_auto_restore_max_total_lines(tmp_memory_dir: Path) -> None:
    created = note.create_note(tmp_memory_dir, title="Restore Budget")
    index.index_note(
        note_path=created,
        index_path=tmp_memory_dir / "_index.jsonl",
        dailynote_dir=tmp_memory_dir,
        task_id="TASK-456",
        agent_id="coder",
        relay_session_id="relay-r",
        no_dense=True,
    )

    state.save_state(
        tmp_memory_dir / "_state.md",
        _full_sections("project", task_id="TASK-456"),
    )
    agent_state_path = state.resolve_agent_state_path(
        tmp_memory_dir,
        agent_id="coder",
        relay_session_id="relay-r",
        for_write=True,
    )
    state.save_state(agent_state_path, _full_sections("agent"))

    payload = state.auto_restore(
        memory_dir=tmp_memory_dir,
        agent_id="coder",
        relay_session_id="relay-r",
        max_total_lines=50,
    )

    assert payload["truncated"] is True
    assert "max_total_lines=50" in payload["truncated_reason"]
    assert _restore_line_count(payload) <= 50
    assert _rendered_line_count(payload["project_state"]) == 43
    assert _rendered_line_count(payload["agent_state"]) == 7
    assert payload["restored_task_count"] >= 1
    active_tasks = payload["active_tasks"]
    assert isinstance(active_tasks, list)
    assert active_tasks[0]["evidence_pack"] == ""


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
    assert (
        state.cmd_set(
            sample_state_path,
            "open",
            ["agentic-relay 修正", "agentic-memory 修正", "ドキュメント更新"],
        )
        == 0
    )

    rc = state.cmd_add(
        sample_state_path,
        "open",
        ["両プロジェクト修正完了"],
        replace=["agentic-relay", "agentic-memory"],
    )
    loaded = state.load_state(sample_state_path)
    items = loaded[state.STATE_SHORT_KEYS["open"]]

    assert rc == 0
    assert len(items) == 2
    assert items[0].text == "両プロジェクト修正完了"
    assert items[1].text == "ドキュメント更新"


def test_cmd_add_accepts_single_replace_string_and_section_alias(sample_state_path: Path) -> None:
    """cmd_add accepts a single replace string and extra section aliases."""
    assert state.cmd_set(sample_state_path, "open", ["legacy item"]) == 0

    rc = state.cmd_add(
        sample_state_path,
        "open_actions",
        ["replacement item"],
        replace="legacy item",
    )
    loaded = state.load_state(sample_state_path)
    items = loaded[state.STATE_SHORT_KEYS["open"]]

    assert rc == 0
    assert len(items) == 1
    assert items[0].text == "replacement item"


def test_expire_stale_items_dry_run(sample_state_path: Path) -> None:
    stale = (dt.datetime.now() - dt.timedelta(days=45)).strftime("%Y-%m-%d %H:%M")
    fresh = (dt.datetime.now() - dt.timedelta(days=5)).strftime("%Y-%m-%d %H:%M")
    sections_data = _empty_sections()
    sections_data[state.STATE_SHORT_KEYS["open"]] = [
        state.StateItem(date=stale, text="stale open item"),
        state.StateItem(date=fresh, text="fresh open item"),
    ]
    state.save_state(sample_state_path, sections_data)

    result = state.expire_stale_items(sample_state_path, stale_days=30, archive_path=None)

    assert result["count"] == 1
    assert result["archived"] is False
    assert result["archive_path"] is None
    assert result["expired_items"] == [
        {
            "section": state.STATE_SHORT_KEYS["open"],
            "text": "stale open item",
            "date": stale,
        }
    ]
    loaded = state.load_state(sample_state_path)
    assert [item.text for item in loaded[state.STATE_SHORT_KEYS["open"]]] == [
        "stale open item",
        "fresh open item",
    ]


def test_expire_stale_items_archive(sample_state_path: Path, tmp_memory_dir: Path) -> None:
    stale = (dt.datetime.now() - dt.timedelta(days=45)).strftime("%Y-%m-%d %H:%M")
    fresh = (dt.datetime.now() - dt.timedelta(days=5)).strftime("%Y-%m-%d %H:%M")
    sections_data = _empty_sections()
    sections_data[state.STATE_SHORT_KEYS["open"]] = [
        state.StateItem(date=stale, text="stale open item"),
        state.StateItem(date=fresh, text="fresh open item"),
    ]
    sections_data[state.STATE_SHORT_KEYS["decisions"]] = [
        state.StateItem(date=stale, text="stale decision item")
    ]
    state.save_state(sample_state_path, sections_data)

    archive_path = tmp_memory_dir / "_state_archive.md"
    archive_sections = _empty_sections()
    archive_sections[state.STATE_SHORT_KEYS["open"]] = [
        state.StateItem(date="2026-01-01 00:00", text="already archived")
    ]
    state.save_state(archive_path, archive_sections)

    result = state.expire_stale_items(
        sample_state_path,
        stale_days=30,
        archive_path=archive_path,
    )

    assert result["count"] == 2
    assert result["archived"] is True
    assert result["archive_path"] == str(archive_path)

    loaded = state.load_state(sample_state_path)
    assert [item.text for item in loaded[state.STATE_SHORT_KEYS["open"]]] == ["fresh open item"]
    assert loaded[state.STATE_SHORT_KEYS["decisions"]] == []

    archived = state.load_state(archive_path)
    assert [item.text for item in archived[state.STATE_SHORT_KEYS["open"]]] == [
        "already archived",
        "stale open item",
    ]
    assert [item.text for item in archived[state.STATE_SHORT_KEYS["decisions"]]] == [
        "stale decision item"
    ]


def test_expire_stale_items_focus_preserved(sample_state_path: Path, tmp_memory_dir: Path) -> None:
    stale = (dt.datetime.now() - dt.timedelta(days=45)).strftime("%Y-%m-%d %H:%M")
    sections_data = _empty_sections()
    sections_data[state.STATE_SHORT_KEYS["focus"]] = [
        state.StateItem(date=stale, text="stale focus item")
    ]
    state.save_state(sample_state_path, sections_data)

    archive_path = tmp_memory_dir / "_focus_archive.md"
    result = state.expire_stale_items(
        sample_state_path,
        stale_days=30,
        archive_path=archive_path,
    )

    assert result["count"] == 0
    assert result["expired_items"] == []
    loaded = state.load_state(sample_state_path)
    assert [item.text for item in loaded[state.STATE_SHORT_KEYS["focus"]]] == ["stale focus item"]
    assert not archive_path.exists()


# ---------- SIGFB signal status management ----------


def test_signal_event_id_deterministic() -> None:
    """Same input produces the same ID."""
    from agentic_memory.core.index import _signal_event_id

    id1 = _signal_event_id("note/a.md", "tool", "friction", "desc", 0)
    id2 = _signal_event_id("note/a.md", "tool", "friction", "desc", 0)
    assert id1 == id2
    assert len(id1) == 12


def test_signal_event_id_unique_across_notes() -> None:
    """Different note paths with same signal text produce different IDs."""
    from agentic_memory.core.index import _signal_event_id

    id1 = _signal_event_id("note/a.md", "tool", "friction", "desc", 0)
    id2 = _signal_event_id("note/b.md", "tool", "friction", "desc", 0)
    assert id1 != id2


def test_build_entry_adds_signal_id(tmp_memory_dir: Path) -> None:
    """build_entry() should add 'id' to each skill_feedback entry."""
    note_dir = tmp_memory_dir / "2026-03-20"
    note_dir.mkdir(parents=True, exist_ok=True)
    note_path = note_dir / "1200_sigfb-id.md"
    note_path.write_text(
        "# ID Test\n\n"
        "- Date: 2026-03-20\n\n"
        "## スキルフィードバック\n\n"
        "- SIGFB: tool_a | friction | desc_a\n"
        "- SIGFB: tool_b | failure | desc_b\n",
        encoding="utf-8",
    )
    entry = index.build_entry(note_path, max_summary_chars=280, dailynote_dir=tmp_memory_dir)
    for fb in entry["skill_feedback"]:
        assert "id" in fb
        assert len(fb["id"]) == 12


def test_aggregate_skips_signals_without_id() -> None:
    """Signals without 'id' should be skipped in aggregation."""
    from agentic_memory.core.signals import aggregate_signals

    entries = [
        {
            "date": "2026-03-20",
            "path": "note/a.md",
            "skill_feedback": [
                {"skill": "tool", "type": "friction", "desc": "no id"},
                {"skill": "tool", "type": "friction", "desc": "has id", "id": "abc123def456"},
            ],
        }
    ]
    result = aggregate_signals(entries)
    skills = result["skills"]
    assert skills["tool"]["total"] == 1
    assert skills["tool"]["entries"][0]["id"] == "abc123def456"


def test_aggregate_filters_resolved_signals() -> None:
    """Resolved signals should not be counted in aggregation."""
    from agentic_memory.core.signals import aggregate_signals

    entries = [
        {
            "date": "2026-03-20",
            "path": "note/a.md",
            "skill_feedback": [
                {"skill": "tool", "type": "failure", "desc": "a", "id": "id_resolved"},
                {"skill": "tool", "type": "failure", "desc": "b", "id": "id_open"},
            ],
        }
    ]
    result = aggregate_signals(entries, resolved_ids={"id_resolved"})
    skills = result["skills"]
    assert skills["tool"]["total"] == 1
    assert skills["tool"]["failure"] == 1
    assert skills["tool"]["entries"][0]["id"] == "id_open"


def test_analyze_includes_contributor_ids() -> None:
    """analyze_signals should include contributor_ids in candidates."""
    from agentic_memory.core.signals import aggregate_signals, analyze_signals

    entries = [
        {
            "date": "2026-03-20",
            "path": "note/a.md",
            "skill_feedback": [
                {"skill": "tool", "type": "failure", "desc": "a", "id": "id1"},
                {"skill": "tool", "type": "failure", "desc": "b", "id": "id2"},
                {"skill": "tool", "type": "failure", "desc": "c", "id": "id3"},
            ],
        }
    ]
    aggregated = aggregate_signals(entries)
    candidates = analyze_signals(aggregated, threshold=3)
    assert len(candidates) == 1
    assert set(candidates[0]["contributor_ids"]) == {"id1", "id2", "id3"}


def test_auto_improve_saves_contributor_snapshot(tmp_memory_dir: Path) -> None:
    """Backlog generation should save contributor snapshot."""
    note_dir = tmp_memory_dir / "2026-03-20"
    note_dir.mkdir(parents=True, exist_ok=True)
    note_path = note_dir / "1200_snapshot.md"
    note_path.write_text(
        "# Snapshot\n\n"
        "- Date: 2026-03-20\n\n"
        "## スキルフィードバック\n\n"
        "- SIGFB: tool_x | failure | one\n"
        "- SIGFB: tool_x | failure | two\n"
        "- SIGFB: tool_x | failure | three\n",
        encoding="utf-8",
    )
    index.index_note(
        note_path=note_path,
        index_path=tmp_memory_dir / "_index.jsonl",
        dailynote_dir=tmp_memory_dir,
    )
    state_path = tmp_memory_dir / "_state.md"
    state.cmd_from_note(state_path, note_path, auto_improve_mode="add")

    snapshot = state._load_contributor_snapshot(state_path)
    assert len(snapshot) >= 1
    # At least one backlog key should have contributor IDs
    all_ids = [sid for ids in snapshot.values() for sid in ids]
    assert len(all_ids) >= 3


def test_cmd_remove_marks_signals_resolved(tmp_memory_dir: Path) -> None:
    """Removing a backlog item should mark contributor signals as resolved."""
    note_dir = tmp_memory_dir / "2026-03-20"
    note_dir.mkdir(parents=True, exist_ok=True)
    note_path = note_dir / "1200_resolve.md"
    note_path.write_text(
        "# Resolve\n\n"
        "- Date: 2026-03-20\n\n"
        "## スキルフィードバック\n\n"
        "- SIGFB: tool_r | failure | one\n"
        "- SIGFB: tool_r | failure | two\n"
        "- SIGFB: tool_r | failure | three\n",
        encoding="utf-8",
    )
    index.index_note(
        note_path=note_path,
        index_path=tmp_memory_dir / "_index.jsonl",
        dailynote_dir=tmp_memory_dir,
    )
    state_path = tmp_memory_dir / "_state.md"
    state.cmd_from_note(state_path, note_path, auto_improve_mode="add")

    # Before removal: no resolved signals
    resolved_before = state._load_sigfb_resolved(state_path)
    assert len(resolved_before) == 0

    state.cmd_remove(state_path, "improvements", "tool_r")

    # After removal: signals should be resolved
    resolved_after = state._load_sigfb_resolved(state_path)
    assert len(resolved_after) >= 3


def test_resolved_signals_not_recounted(tmp_memory_dir: Path) -> None:
    """Core test: resolved signals should not regenerate backlog items."""
    note_dir = tmp_memory_dir / "2026-03-20"
    note_dir.mkdir(parents=True, exist_ok=True)
    note_path = note_dir / "1200_recount.md"
    note_path.write_text(
        "# Recount\n\n"
        "- Date: 2026-03-20\n\n"
        "## スキルフィードバック\n\n"
        "- SIGFB: tool_rc | failure | one\n"
        "- SIGFB: tool_rc | failure | two\n"
        "- SIGFB: tool_rc | failure | three\n",
        encoding="utf-8",
    )
    index.index_note(
        note_path=note_path,
        index_path=tmp_memory_dir / "_index.jsonl",
        dailynote_dir=tmp_memory_dir,
    )
    state_path = tmp_memory_dir / "_state.md"

    # Generate backlog
    state.cmd_from_note(state_path, note_path, auto_improve_mode="add")
    loaded = state.load_state(state_path)
    assert any("tool_rc" in item.text for item in loaded[state.STATE_SHORT_KEYS["improvements"]])

    # Remove (marks signals as resolved)
    state.cmd_remove(state_path, "improvements", "tool_rc")

    # Re-run from_note — should NOT regenerate
    state.cmd_from_note(state_path, note_path, auto_improve_mode="add")
    loaded = state.load_state(state_path)
    assert not any(
        "tool_rc" in item.text for item in loaded[state.STATE_SHORT_KEYS["improvements"]]
    )


def test_new_signals_after_resolve_detected(tmp_memory_dir: Path) -> None:
    """New signals after resolve should correctly generate new backlog items."""
    note_dir = tmp_memory_dir / "2026-03-20"
    note_dir.mkdir(parents=True, exist_ok=True)

    # First note with 3 failures
    note1 = note_dir / "1200_first.md"
    note1.write_text(
        "# First\n\n"
        "- Date: 2026-03-20\n\n"
        "## スキルフィードバック\n\n"
        "- SIGFB: tool_new | failure | old_one\n"
        "- SIGFB: tool_new | failure | old_two\n"
        "- SIGFB: tool_new | failure | old_three\n",
        encoding="utf-8",
    )
    index.index_note(
        note_path=note1,
        index_path=tmp_memory_dir / "_index.jsonl",
        dailynote_dir=tmp_memory_dir,
    )
    state_path = tmp_memory_dir / "_state.md"

    # Generate and resolve
    state.cmd_from_note(state_path, note1, auto_improve_mode="add")
    state.cmd_remove(state_path, "improvements", "tool_new")

    # Second note with 3 NEW failures (different desc -> different IDs)
    note2_dir = tmp_memory_dir / "2026-03-21"
    note2_dir.mkdir(parents=True, exist_ok=True)
    note2 = note2_dir / "1200_second.md"
    note2.write_text(
        "# Second\n\n"
        "- Date: 2026-03-21\n\n"
        "## スキルフィードバック\n\n"
        "- SIGFB: tool_new | failure | new_one\n"
        "- SIGFB: tool_new | failure | new_two\n"
        "- SIGFB: tool_new | failure | new_three\n",
        encoding="utf-8",
    )
    index.index_note(
        note_path=note2,
        index_path=tmp_memory_dir / "_index.jsonl",
        dailynote_dir=tmp_memory_dir,
    )

    state.cmd_from_note(state_path, note2, auto_improve_mode="add")
    loaded = state.load_state(state_path)
    assert any("tool_new" in item.text for item in loaded[state.STATE_SHORT_KEYS["improvements"]])


def test_trigger_cooldown_periodic_review(tmp_memory_dir: Path) -> None:
    """Trigger cooldown should prevent periodic_review from being re-added."""
    state_path = tmp_memory_dir / "_state.md"

    # Record cooldown
    state._record_trigger_cooldown(state_path, "periodic_review")

    # Should be within cooldown
    assert state._has_recent_trigger_cooldown(state_path, "periodic_review", 14) is True

    # Unknown trigger should not be in cooldown
    assert state._has_recent_trigger_cooldown(state_path, "unknown_trigger", 14) is False


def test_trigger_contributor_inheritance(tmp_memory_dir: Path) -> None:
    """pattern_escalation/gap_expansion triggers should inherit contributor_ids from candidates."""
    note_dir = tmp_memory_dir / "2026-03-20"
    note_dir.mkdir(parents=True, exist_ok=True)
    note_path = note_dir / "1200_trigger.md"
    # 3 friction + 1 workaround = pattern_escalation at medium severity
    note_path.write_text(
        "# Trigger\n\n"
        "- Date: 2026-03-20\n\n"
        "## スキルフィードバック\n\n"
        "- SIGFB: tool_t | friction | f1\n"
        "- SIGFB: tool_t | friction | f2\n"
        "- SIGFB: tool_t | friction | f3\n"
        "- SIGFB: tool_t | workaround | w1\n",
        encoding="utf-8",
    )
    index.index_note(
        note_path=note_path,
        index_path=tmp_memory_dir / "_index.jsonl",
        dailynote_dir=tmp_memory_dir,
    )
    state_path = tmp_memory_dir / "_state.md"
    state.cmd_from_note(state_path, note_path, auto_improve_mode="add")

    snapshot = state._load_contributor_snapshot(state_path)
    # Should have at least one entry with contributor_ids inherited from the candidate
    trigger_keys = [k for k in snapshot if "pattern_escalation" in k or "tool_t" in k]
    assert len(trigger_keys) >= 1
    for key in trigger_keys:
        assert len(snapshot[key]) >= 1
