from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path

from agentic_memory.core import health, index


def test_health_check_reports_healthy_memory(sample_note_path: Path, tmp_memory_dir: Path) -> None:
    index.index_note(
        note_path=sample_note_path,
        index_path=tmp_memory_dir / "_index.jsonl",
        dailynote_dir=tmp_memory_dir,
        no_dense=True,
    )

    result = health.health_check(tmp_memory_dir)

    assert result["orphan_entries"] == []
    assert result["unindexed_notes"] == []
    assert result["stale_entries"] == []
    assert result["state_valid"] is True
    assert result["config_valid"] is True
    assert result["summary"].startswith("正常")


def test_health_check_detects_index_and_file_issues(
    sample_note_path: Path,
    tmp_memory_dir: Path,
) -> None:
    stale_dir = tmp_memory_dir / "2026-01-02"
    stale_dir.mkdir(parents=True, exist_ok=True)
    stale_note = stale_dir / "0900_stale.md"
    stale_note.write_text(
        ("# Stale Session\n\n- Date: 2026-01-02\n\n## 目標\n\n- Verify stale detection\n"),
        encoding="utf-8",
    )
    index.rebuild_index(
        index_path=tmp_memory_dir / "_index.jsonl",
        dailynote_dir=tmp_memory_dir,
        no_dense=True,
    )

    sample_note_path.unlink()

    unindexed_dir = tmp_memory_dir / "2026-01-03"
    unindexed_dir.mkdir(parents=True, exist_ok=True)
    unindexed_note = unindexed_dir / "1000_unindexed.md"
    unindexed_note.write_text("# Unindexed Session\n", encoding="utf-8")

    future_timestamp = (datetime.now() + timedelta(minutes=5)).timestamp()
    os.utime(stale_note, (future_timestamp, future_timestamp))

    (tmp_memory_dir / "_state.md").unlink()
    (tmp_memory_dir / "_rag_config.json").write_text("{invalid", encoding="utf-8")

    result = health.health_check(tmp_memory_dir)

    assert "memory/2026-01-01/1015_sample-session.md" in result["orphan_entries"]
    assert "memory/2026-01-02/0900_stale.md" in result["stale_entries"]
    assert "memory/2026-01-03/1000_unindexed.md" in result["unindexed_notes"]
    assert result["state_valid"] is False
    assert result["config_valid"] is False
    assert result["summary"].startswith("要確認")
    assert stale_note.exists()
    assert unindexed_note.exists()


def test_health_check_handles_invalid_index(sample_note_path: Path, tmp_memory_dir: Path) -> None:
    (tmp_memory_dir / "_index.jsonl").write_text("{not-json}\n", encoding="utf-8")

    result = health.health_check(tmp_memory_dir)

    assert result["orphan_entries"] == []
    assert result["stale_entries"] == []
    assert result["unindexed_notes"] == ["memory/2026-01-01/1015_sample-session.md"]
    assert "読み込みに失敗" in result["summary"]
    assert sample_note_path.exists()
