from __future__ import annotations

from pathlib import Path

from agentic_memory.core import index, state, stats
from agentic_memory.core.knowledge import KnowledgeEntry, KnowledgeRepository, SourceType
from agentic_memory.core.values import ValuesEntry, ValuesRepository


def test_get_stats_collects_memory_metrics(sample_note_path: Path, tmp_memory_dir: Path) -> None:
    second_dir = tmp_memory_dir / "2026-01-02"
    second_dir.mkdir(parents=True, exist_ok=True)
    second_note = second_dir / "0900_second.md"
    second_note.write_text(
        (
            "# Second Session\n\n"
            "- Date: 2026-01-02\n"
            "- Tags: backend\n"
            "- Keywords: cache\n\n"
            "## 目標\n\n"
            "- Improve cache reuse\n"
        ),
        encoding="utf-8",
    )
    index.rebuild_index(
        index_path=tmp_memory_dir / "_index.jsonl",
        dailynote_dir=tmp_memory_dir,
        no_dense=True,
    )
    assert state.cmd_set(tmp_memory_dir / "_state.md", "focus", ["Review retention policy"]) == 0
    state.update_distillation_frontmatter(
        tmp_memory_dir / "_state.md",
        last_knowledge_evaluated_at="2026-01-01T12:00:00",
        last_values_evaluated_at="2026-01-02T08:30:00",
    )
    KnowledgeRepository(tmp_memory_dir).save(
        KnowledgeEntry(
            title="Rust ownership",
            content="Ownership summary",
            domain="rust",
            origin=SourceType.USER_TAUGHT,
        )
    )
    ValuesRepository(tmp_memory_dir).save(
        ValuesEntry(
            description="Prefer reversible migrations",
            category="workflow",
            confidence=0.9,
            evidence=[],
            total_evidence_count=6,
            origin=SourceType.USER_TAUGHT,
            promoted=True,
            promoted_confidence=0.9,
        )
    )
    ValuesRepository(tmp_memory_dir).save(
        ValuesEntry(
            description="Prefer focused diffs",
            category="workflow",
            confidence=0.5,
            evidence=[],
            total_evidence_count=1,
            origin=SourceType.USER_TAUGHT,
        )
    )

    result = stats.get_stats(tmp_memory_dir)

    assert result["notes_count"] == 2
    assert result["notes_by_date"] == {"2026-01-01": 1, "2026-01-02": 1}
    assert result["index_entries"] == 2
    assert result["knowledge_count"] == 1
    assert result["values_count"] == 2
    assert result["promoted_values_count"] == 1
    assert result["notes_since_last_knowledge_evaluation"] == 1
    assert result["notes_since_last_values_evaluation"] == 1
    assert result["storage_bytes"] > 0
    assert result["date_range"] == {"oldest": "2026-01-01", "newest": "2026-01-02"}
    assert result["sigfb_summary"][".agents/skills/software-engineer/SKILL.md"]["friction"] == 1
    assert result["state_items"][state.STATE_SHORT_KEYS["focus"]] == 1
    assert sample_note_path.exists()
    assert second_note.exists()


def test_get_stats_handles_missing_index(sample_note_path: Path, tmp_memory_dir: Path) -> None:
    result = stats.get_stats(tmp_memory_dir)

    assert result["notes_count"] == 1
    assert result["index_entries"] == 0
    assert result["knowledge_count"] == 0
    assert result["values_count"] == 0
    assert result["promoted_values_count"] == 0
    assert result["notes_since_last_knowledge_evaluation"] == 1
    assert result["notes_since_last_values_evaluation"] == 1
    assert result["sigfb_summary"] == {}
    assert result["date_range"] == {"oldest": "2026-01-01", "newest": "2026-01-01"}
    assert sample_note_path.exists()
