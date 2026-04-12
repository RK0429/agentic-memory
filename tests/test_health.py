from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from agentic_memory.core import health, index
from agentic_memory.core.config import PROMOTED_VALUES_BEGIN, PROMOTED_VALUES_END
from agentic_memory.core.knowledge import KnowledgeEntry, KnowledgeRepository, SourceType
from agentic_memory.core.values import AgentsMdAdapter, ValuesEntry, ValuesRepository


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


def test_health_check_treats_missing_kv_indexes_as_healthy_when_unused(
    tmp_memory_dir: Path,
) -> None:
    result = health.health_check(tmp_memory_dir)

    assert result["knowledge_index"]["index_exists"] is False
    assert result["knowledge_index"]["orphan_entries"] == []
    assert result["knowledge_index"]["orphan_files"] == []
    assert result["values_index"]["index_exists"] is False
    assert result["values_index"]["orphan_entries"] == []
    assert result["values_index"]["orphan_files"] == []


def test_health_check_detects_kv_orphans_related_issues_and_promoted_sync(
    tmp_memory_dir: Path,
) -> None:
    knowledge_repository = KnowledgeRepository(tmp_memory_dir)
    values_repository = ValuesRepository(tmp_memory_dir)
    adapter = AgentsMdAdapter()

    target = KnowledgeEntry(
        title="Target knowledge",
        content="shared target",
        domain="python",
        origin=SourceType.USER_TAUGHT,
    )
    knowledge_repository.save(target)
    broken = KnowledgeEntry(
        title="Broken knowledge",
        content="has broken links",
        domain="python",
        origin=SourceType.USER_TAUGHT,
        related=[
            str(target.id),
            "k-00000000-0000-0000-0000-000000000001",
        ],
    )
    knowledge_repository.save(broken)
    orphan_knowledge = KnowledgeEntry(
        title="Orphan knowledge file",
        content="index row removed",
        domain="python",
        origin=SourceType.USER_TAUGHT,
    )
    knowledge_repository.save(orphan_knowledge)

    knowledge_index_path = tmp_memory_dir / "_knowledge.jsonl"
    knowledge_rows = [
        row
        for row in (
            json.loads(line)
            for line in knowledge_index_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
        if row["id"] != str(orphan_knowledge.id)
    ]
    knowledge_rows.append(
        {
            "id": "k-00000000-0000-0000-0000-000000000099",
            "path": "knowledge/k-00000000-0000-0000-0000-000000000099.md",
            "title": "missing knowledge",
        }
    )
    knowledge_index_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in knowledge_rows) + "\n",
        encoding="utf-8",
    )

    promoted = ValuesEntry(
        description="Prefer reversible schema changes",
        category="workflow",
        confidence=0.9,
        evidence=[],
        total_evidence_count=6,
        origin=SourceType.USER_TAUGHT,
        promoted=True,
        promoted_confidence=0.9,
    )
    values_repository.save(promoted)
    mismatched = ValuesEntry(
        description="Prefer safer promotion sync\n<!-- comment --> " + ("x" * 220),
        category="workflow",
        confidence=0.85,
        evidence=[],
        total_evidence_count=6,
        origin=SourceType.USER_TAUGHT,
        promoted=True,
        promoted_confidence=0.85,
    )
    values_repository.save(mismatched)
    orphan_values = ValuesEntry(
        description="Orphan values file",
        category="workflow",
        confidence=0.4,
        evidence=[],
        total_evidence_count=1,
        origin=SourceType.USER_TAUGHT,
    )
    values_repository.save(orphan_values)

    values_index_path = tmp_memory_dir / "_values.jsonl"
    values_rows = [
        row
        for row in (
            json.loads(line)
            for line in values_index_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
        if row["id"] != str(orphan_values.id)
    ]
    values_rows.append(
        {
            "id": "v-00000000-0000-0000-0000-000000000099",
            "path": "values/v-00000000-0000-0000-0000-000000000099.md",
            "description": "missing values",
            "category": "workflow",
            "confidence": 0.1,
            "evidence_count": 0,
            "origin": "user_taught",
            "promoted": False,
            "promoted_at": None,
            "promoted_confidence": None,
            "demotion_reason": None,
            "demoted_at": None,
            "created_at": "2026-04-10T09:00:00",
            "updated_at": "2026-04-10T09:00:00",
        }
    )
    values_index_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in values_rows) + "\n",
        encoding="utf-8",
    )

    agents_path = tmp_memory_dir.parent / "AGENTS.md"
    agents_path.write_text(
        "# Agent Rules\n\n"
        f"{PROMOTED_VALUES_BEGIN}\n"
        "- [v-00000000-0000-0000-0000-000000000001] orphan promoted entry\n"
        f"- [{mismatched.id}] stale promoted description\n"
        f"{PROMOTED_VALUES_END}\n",
        encoding="utf-8",
    )

    result = health.health_check(tmp_memory_dir)

    assert result["knowledge_index"]["orphan_entries"] == [
        {
            "id": "k-00000000-0000-0000-0000-000000000099",
            "path": "knowledge/k-00000000-0000-0000-0000-000000000099.md",
        }
    ]
    assert result["knowledge_index"]["orphan_files"] == [f"knowledge/{orphan_knowledge.id}.md"]
    assert result["knowledge_related"]["orphan_links"] == [
        {
            "source_id": str(broken.id),
            "target_id": "k-00000000-0000-0000-0000-000000000001",
        }
    ]
    assert result["knowledge_related"]["unidirectional_links"] == [
        {
            "source_id": str(broken.id),
            "target_id": str(target.id),
        }
    ]
    assert result["values_index"]["orphan_entries"] == [
        {
            "id": "v-00000000-0000-0000-0000-000000000099",
            "path": "values/v-00000000-0000-0000-0000-000000000099.md",
        }
    ]
    assert result["values_index"]["orphan_files"] == [f"values/{orphan_values.id}.md"]
    assert result["promoted_values_sync"]["orphan_in_agents_md"] == [
        "v-00000000-0000-0000-0000-000000000001"
    ]
    assert result["promoted_values_sync"]["missing_in_agents_md"] == [str(promoted.id)]
    assert result["promoted_values_sync"]["description_mismatches"] == [
        {
            "id": str(mismatched.id),
            "agents_md_description": "stale promoted description",
            "projected_description": adapter.project_description(mismatched.description),
        }
    ]


def test_health_check_fix_repairs_kv_indexes_related_links_and_promoted_sync(
    tmp_memory_dir: Path,
) -> None:
    knowledge_repository = KnowledgeRepository(tmp_memory_dir)
    values_repository = ValuesRepository(tmp_memory_dir)
    adapter = AgentsMdAdapter()

    target = KnowledgeEntry(
        title="Target knowledge",
        content="shared target",
        domain="python",
        origin=SourceType.USER_TAUGHT,
    )
    knowledge_repository.save(target)
    broken = KnowledgeEntry(
        title="Broken knowledge",
        content="has broken links",
        domain="python",
        origin=SourceType.USER_TAUGHT,
        related=[
            str(target.id),
            "k-00000000-0000-0000-0000-000000000001",
        ],
    )
    knowledge_repository.save(broken)
    orphan_knowledge = KnowledgeEntry(
        title="Orphan knowledge file",
        content="index row removed",
        domain="python",
        origin=SourceType.USER_TAUGHT,
    )
    knowledge_repository.save(orphan_knowledge)

    knowledge_index_path = tmp_memory_dir / "_knowledge.jsonl"
    knowledge_rows = [
        row
        for row in (
            json.loads(line)
            for line in knowledge_index_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
        if row["id"] != str(orphan_knowledge.id)
    ]
    knowledge_rows.append(
        {
            "id": "k-00000000-0000-0000-0000-000000000099",
            "path": "knowledge/k-00000000-0000-0000-0000-000000000099.md",
            "title": "missing knowledge",
        }
    )
    knowledge_index_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in knowledge_rows) + "\n",
        encoding="utf-8",
    )

    promoted = ValuesEntry(
        description="Prefer reversible schema changes",
        category="workflow",
        confidence=0.9,
        evidence=[],
        total_evidence_count=6,
        origin=SourceType.USER_TAUGHT,
        promoted=True,
        promoted_confidence=0.9,
    )
    values_repository.save(promoted)
    mismatched = ValuesEntry(
        description="Prefer safer promotion sync\n<!-- comment --> " + ("x" * 220),
        category="workflow",
        confidence=0.85,
        evidence=[],
        total_evidence_count=6,
        origin=SourceType.USER_TAUGHT,
        promoted=True,
        promoted_confidence=0.85,
    )
    values_repository.save(mismatched)
    orphan_values = ValuesEntry(
        description="Orphan values file",
        category="workflow",
        confidence=0.4,
        evidence=[],
        total_evidence_count=1,
        origin=SourceType.USER_TAUGHT,
    )
    values_repository.save(orphan_values)

    values_index_path = tmp_memory_dir / "_values.jsonl"
    values_rows = [
        row
        for row in (
            json.loads(line)
            for line in values_index_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
        if row["id"] != str(orphan_values.id)
    ]
    values_rows.append(
        {
            "id": "v-00000000-0000-0000-0000-000000000099",
            "path": "values/v-00000000-0000-0000-0000-000000000099.md",
            "description": "missing values",
            "category": "workflow",
            "confidence": 0.1,
            "evidence_count": 0,
            "origin": "user_taught",
            "promoted": False,
            "promoted_at": None,
            "promoted_confidence": None,
            "demotion_reason": None,
            "demoted_at": None,
            "created_at": "2026-04-10T09:00:00",
            "updated_at": "2026-04-10T09:00:00",
        }
    )
    values_index_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in values_rows) + "\n",
        encoding="utf-8",
    )

    agents_path = tmp_memory_dir.parent / "AGENTS.md"
    agents_path.write_text(
        "# Agent Rules\n\n"
        f"{PROMOTED_VALUES_BEGIN}\n"
        "- [v-00000000-0000-0000-0000-000000000001] orphan promoted entry\n"
        f"- [{mismatched.id}] stale promoted description\n"
        f"{PROMOTED_VALUES_END}\n",
        encoding="utf-8",
    )

    result = health.fix_issues(tmp_memory_dir)
    post_check = health.health_check(tmp_memory_dir)

    assert result["knowledge_orphans_removed"] == 1
    assert result["values_orphans_removed"] == 1
    assert result["knowledge_reindexed"] == [f"knowledge/{orphan_knowledge.id}.md"]
    assert result["values_reindexed"] == [f"values/{orphan_values.id}.md"]
    assert result["orphan_links_removed"] == 1
    assert result["bidirectional_links_restored"] == 1
    assert result["orphans_removed_from_agents_md"] == 1
    assert result["missing_added_to_agents_md"] == 1
    assert result["descriptions_updated_in_agents_md"] == 1
    assert post_check["knowledge_index"]["orphan_entries"] == []
    assert post_check["knowledge_index"]["orphan_files"] == []
    assert post_check["values_index"]["orphan_entries"] == []
    assert post_check["values_index"]["orphan_files"] == []
    assert post_check["knowledge_related"]["orphan_links"] == []
    assert post_check["knowledge_related"]["unidirectional_links"] == []
    assert post_check["promoted_values_sync"]["orphan_in_agents_md"] == []
    assert post_check["promoted_values_sync"]["missing_in_agents_md"] == []
    assert post_check["promoted_values_sync"]["description_mismatches"] == []
    agents_text = agents_path.read_text(encoding="utf-8")
    projected_mismatch = adapter.project_description(mismatched.description)
    assert str(promoted.id) in agents_text
    assert f"- [{mismatched.id}] {projected_mismatch}" in agents_text

    repaired_target = knowledge_repository.load(target.id)
    repaired_broken = knowledge_repository.load(broken.id)
    assert [str(item) for item in repaired_broken.related] == [str(target.id)]
    assert [str(item) for item in repaired_target.related] == [str(broken.id)]


def test_health_check_handles_invalid_index(sample_note_path: Path, tmp_memory_dir: Path) -> None:
    (tmp_memory_dir / "_index.jsonl").write_text("{not-json}\n", encoding="utf-8")

    result = health.health_check(tmp_memory_dir)

    assert result["orphan_entries"] == []
    assert result["stale_entries"] == []
    assert result["unindexed_notes"] == ["memory/2026-01-01/1015_sample-session.md"]
    assert "読み込みに失敗" in result["summary"]
    assert sample_note_path.exists()
