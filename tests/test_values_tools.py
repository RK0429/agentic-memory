from __future__ import annotations

import json
from pathlib import Path

from agentic_memory.core.values import Evidence, SourceType, ValuesEntry, ValuesRepository
from agentic_memory.server import (
    memory_values_add,
    memory_values_delete,
    memory_values_demote,
    memory_values_list,
    memory_values_promote,
    memory_values_search,
    memory_values_update,
)


def _evidence(index: int) -> dict[str, str]:
    return {
        "ref": f"memory/2026-04-{index:02d}/note.md",
        "summary": f"evidence-{index}",
        "date": f"2026-04-{index:02d}",
    }


def _seed_promoted_entry(memory_dir: Path) -> ValuesEntry:
    entry = ValuesEntry(
        description="Prefer reversible schema migrations",
        category="design",
        confidence=0.9,
        evidence=[Evidence.from_dict(_evidence(index)) for index in range(1, 7)],
        total_evidence_count=6,
        source_type=SourceType.USER_TAUGHT,
        promoted=True,
        promoted_confidence=0.9,
        created_at="2026-04-10T09:00:00",
        updated_at="2026-04-10T09:00:00",
    )
    ValuesRepository(memory_dir).save(entry)
    return entry


def test_memory_values_add_returns_path_warning_and_promotion_candidate(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    first = json.loads(
        memory_values_add(
            description="Prefer focused reversible changes",
            category="workflow",
            memory_dir=str(tmp_memory_dir),
        )
    )

    payload = json.loads(
        memory_values_add(
            description="Prefer focused reversible changes in commits",
            category="workflow",
            confidence=0.85,
            evidence=[_evidence(index) for index in range(1, 6)],
            memory_dir=str(tmp_memory_dir),
        )
    )

    assert payload["ok"] is True
    assert payload["path"] == f"values/{payload['id']}.md"
    assert payload["promotion_candidate"] is True
    assert str(first["id"]) in payload["warnings"][0]


def test_memory_values_add_reports_duplicate_as_validation_error(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    memory_values_add(
        description="Prefer compact PR summaries",
        category="communication",
        memory_dir=str(tmp_memory_dir),
    )

    payload = json.loads(
        memory_values_add(
            description=" Prefer compact  PR summaries ",
            category=" communication ",
            memory_dir=str(tmp_memory_dir),
        )
    )

    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert "Duplicate value exists" in payload["message"]


def test_memory_values_add_returns_secret_warning(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)

    payload = json.loads(
        memory_values_add(
            description='Prefer storing api_key="AbCdEf1234567890" only in vaults',
            category="security",
            memory_dir=str(tmp_memory_dir),
        )
    )

    assert payload["ok"] is True
    assert payload["warnings"] == [
        "Content may contain secrets (detected: generic_api_token). Review before sharing."
    ]


def test_memory_values_add_malformed_evidence_returns_validation_error(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)

    payload = json.loads(
        memory_values_add(
            description="Prefer evidence with complete metadata",
            category="workflow",
            evidence=[{"ref": "memory/2026-04-10/note.md", "summary": "missing date"}],
            memory_dir=str(tmp_memory_dir),
        )
    )

    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert "{ref, summary, date}" in payload["hint"]
    assert "date" in payload["hint"]


def test_memory_values_search_requires_query_or_category(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)

    payload = json.loads(memory_values_search(memory_dir=str(tmp_memory_dir)))

    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"


def test_memory_values_search_returns_ranked_entries(tmp_memory_dir: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    memory_values_add(
        description="Add regression tests for bug fixes",
        category="review",
        confidence=0.9,
        memory_dir=str(tmp_memory_dir),
    )
    memory_values_add(
        description="Document release checklist",
        category="workflow",
        confidence=0.8,
        memory_dir=str(tmp_memory_dir),
    )

    payload = json.loads(
        memory_values_search(
            query="regression tests",
            min_confidence=0.5,
            top=5,
            memory_dir=str(tmp_memory_dir),
        )
    )

    assert payload["ok"] is True
    assert payload["entries"][0]["description"] == "Add regression tests for bug fixes"
    assert payload["entries"][0]["score"] > 0


def test_memory_values_update_validates_input_and_not_found(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    validation_payload = json.loads(
        memory_values_update(
            id="v-00000000-0000-0000-0000-000000000000",
            memory_dir=str(tmp_memory_dir),
        )
    )
    not_found_payload = json.loads(
        memory_values_update(
            id="v-11111111-1111-1111-1111-111111111111",
            confidence=0.4,
            memory_dir=str(tmp_memory_dir),
        )
    )

    assert validation_payload["ok"] is False
    assert validation_payload["error_type"] == "validation_error"
    assert not_found_payload["ok"] is False
    assert not_found_payload["error_type"] == "not_found"


def test_memory_values_update_returns_promotion_and_demotion_notifications(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    added = json.loads(
        memory_values_add(
            description="Require regression coverage for bug fixes",
            category="review",
            confidence=0.8,
            evidence=[_evidence(index) for index in range(1, 5)],
            memory_dir=str(tmp_memory_dir),
        )
    )
    promoted_entry = _seed_promoted_entry(tmp_memory_dir)

    promotion_payload = json.loads(
        memory_values_update(
            id=added["id"],
            add_evidence=_evidence(5),
            memory_dir=str(tmp_memory_dir),
        )
    )
    demotion_payload = json.loads(
        memory_values_update(
            id=str(promoted_entry.id),
            confidence=0.7,
            memory_dir=str(tmp_memory_dir),
        )
    )

    assert promotion_payload["ok"] is True
    assert promotion_payload["promotion_candidate"] is True
    assert demotion_payload["ok"] is True
    assert demotion_payload["demotion_candidate"] is True


def test_memory_values_update_add_evidence_accepts_list(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    added = json.loads(
        memory_values_add(
            description="Prefer accumulating evidence in batches",
            category="workflow",
            confidence=0.7,
            memory_dir=str(tmp_memory_dir),
        )
    )

    payload = json.loads(
        memory_values_update(
            id=added["id"],
            add_evidence=[_evidence(1), _evidence(2)],
            memory_dir=str(tmp_memory_dir),
        )
    )

    assert payload["ok"] is True
    entry = ValuesRepository(tmp_memory_dir).load(added["id"])
    assert entry.total_evidence_count == 2
    assert [item.ref for item in entry.evidence] == [
        _evidence(2)["ref"],
        _evidence(1)["ref"],
    ]


def test_memory_values_update_returns_secret_warning_for_description_update(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    added = json.loads(
        memory_values_add(
            description="Prefer documented secret handling",
            category="security",
            memory_dir=str(tmp_memory_dir),
        )
    )

    payload = json.loads(
        memory_values_update(
            id=added["id"],
            description='Prefer documenting auth_token="AbCdEf1234567890" handling',
            memory_dir=str(tmp_memory_dir),
        )
    )

    assert payload["ok"] is True
    assert payload["warnings"] == [
        "Content may contain secrets (detected: generic_api_token). Review before sharing."
    ]


def test_memory_values_list_filters_promoted_only(tmp_memory_dir: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    _seed_promoted_entry(tmp_memory_dir)
    memory_values_add(
        description="Prefer draft PRs for large work",
        category="review",
        confidence=0.95,
        memory_dir=str(tmp_memory_dir),
    )

    payload = json.loads(
        memory_values_list(
            promoted_only=True,
            top=10,
            memory_dir=str(tmp_memory_dir),
        )
    )

    assert payload["ok"] is True
    assert len(payload["entries"]) == 1
    assert payload["entries"][0]["promoted"] is True


def test_memory_values_list_defaults_to_all_confidence_entries(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    low = json.loads(
        memory_values_add(
            description="Prefer low-confidence experiments",
            category="workflow",
            confidence=0.4,
            memory_dir=str(tmp_memory_dir),
        )
    )
    high = json.loads(
        memory_values_add(
            description="Prefer high-confidence changes",
            category="workflow",
            confidence=0.5,
            memory_dir=str(tmp_memory_dir),
        )
    )

    payload = json.loads(memory_values_list(memory_dir=str(tmp_memory_dir)))

    assert payload["ok"] is True
    assert [entry["id"] for entry in payload["entries"]] == [high["id"], low["id"]]


def test_memory_values_promote_preview_and_confirm(tmp_memory_dir: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    agents_path = tmp_memory_dir.parent / "AGENTS.md"
    agents_path.write_text(
        "# Agent Rules\n\n<!-- BEGIN:PROMOTED_VALUES -->\n<!-- END:PROMOTED_VALUES -->\n",
        encoding="utf-8",
    )
    added = json.loads(
        memory_values_add(
            description="Prefer focused reversible changes",
            category="workflow",
            confidence=0.85,
            evidence=[_evidence(index) for index in range(1, 6)],
            memory_dir=str(tmp_memory_dir),
        )
    )

    preview = json.loads(
        memory_values_promote(
            id=added["id"],
            confirm=False,
            memory_dir=str(tmp_memory_dir),
        )
    )
    result = json.loads(
        memory_values_promote(
            id=added["id"],
            confirm=True,
            memory_dir=str(tmp_memory_dir),
        )
    )

    assert preview["ok"] is True
    assert preview["preview"] is True
    assert result["ok"] is True
    assert result["promoted"] is True
    assert added["id"] in agents_path.read_text(encoding="utf-8")


def test_memory_values_demote_preview_and_confirm(tmp_memory_dir: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    agents_path = tmp_memory_dir.parent / "AGENTS.md"
    promoted_entry = _seed_promoted_entry(tmp_memory_dir)
    agents_path.write_text(
        "# Agent Rules\n\n"
        "<!-- BEGIN:PROMOTED_VALUES -->\n"
        f"- [{promoted_entry.id}] {promoted_entry.description}\n"
        "<!-- END:PROMOTED_VALUES -->\n",
        encoding="utf-8",
    )

    preview = json.loads(
        memory_values_demote(
            id=str(promoted_entry.id),
            reason="confidence dropped",
            confirm=False,
            memory_dir=str(tmp_memory_dir),
        )
    )
    result = json.loads(
        memory_values_demote(
            id=str(promoted_entry.id),
            reason="confidence dropped",
            confirm=True,
            memory_dir=str(tmp_memory_dir),
        )
    )

    assert preview["ok"] is True
    assert preview["preview"] is True
    assert result["ok"] is True
    assert result["promoted"] is False
    assert result["demotion_reason"] == "confidence dropped"
    assert str(promoted_entry.id) not in agents_path.read_text(encoding="utf-8")


def test_memory_values_promote_and_demote_report_errors(tmp_memory_dir: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    added = json.loads(
        memory_values_add(
            description="Prefer explicit rollback plans",
            category="workflow",
            confidence=0.85,
            evidence=[_evidence(index) for index in range(1, 6)],
            memory_dir=str(tmp_memory_dir),
        )
    )

    missing_agents_payload = json.loads(
        memory_values_promote(
            id=added["id"],
            confirm=True,
            memory_dir=str(tmp_memory_dir),
        )
    )
    not_promoted = json.loads(
        memory_values_demote(
            id="v-11111111-1111-1111-1111-111111111111",
            reason="missing",
            confirm=True,
            memory_dir=str(tmp_memory_dir),
        )
    )

    assert missing_agents_payload["ok"] is False
    assert missing_agents_payload["error_type"] == "not_found"
    assert not_promoted["ok"] is False
    assert not_promoted["error_type"] == "not_found"


def test_memory_values_promote_ineligible_includes_current_and_threshold(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    added = json.loads(
        memory_values_add(
            description="Prefer shipping ineligible promoted values",
            category="workflow",
            confidence=0.7,
            evidence=[_evidence(index) for index in range(1, 5)],
            memory_dir=str(tmp_memory_dir),
        )
    )

    payload = json.loads(
        memory_values_promote(
            id=added["id"],
            confirm=False,
            memory_dir=str(tmp_memory_dir),
        )
    )

    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert "confidence=0.7" in payload["message"]
    assert "required>=0.8" in payload["message"]
    assert "evidence_count=4" in payload["message"]
    assert "required>=5" in payload["message"]
    assert "promoted=False" in payload["message"]
    assert "Increase confidence to >= 0.8" in payload["message"]


def test_memory_values_promote_rejects_secret_containing_entry(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    added = json.loads(
        memory_values_add(
            description='Prefer sharing api_key="AbCdEf1234567890" in chat',
            category="security",
            confidence=0.85,
            evidence=[_evidence(index) for index in range(1, 6)],
            memory_dir=str(tmp_memory_dir),
        )
    )

    payload = json.loads(
        memory_values_promote(
            id=added["id"],
            confirm=False,
            memory_dir=str(tmp_memory_dir),
        )
    )

    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert payload["message"] == "Cannot promote value containing potential secrets"


def test_memory_values_delete_removes_non_promoted_entry(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    added = json.loads(
        memory_values_add(
            description="Prefer focused diffs",
            category="workflow",
            memory_dir=str(tmp_memory_dir),
        )
    )

    payload = json.loads(
        memory_values_delete(
            id=added["id"],
            memory_dir=str(tmp_memory_dir),
        )
    )

    assert payload == {
        "ok": True,
        "deleted_id": added["id"],
        "description": "Prefer focused diffs",
        "deleted": True,
        "was_promoted": False,
    }
    assert ValuesRepository(tmp_memory_dir).find_by_id(added["id"]) is None
    assert not (tmp_memory_dir / f"values/{added['id']}.md").exists()


def test_memory_values_delete_promoted_entry_requires_confirm_preview_then_deletes(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    agents_path = tmp_memory_dir.parent / "AGENTS.md"
    promoted_entry = _seed_promoted_entry(tmp_memory_dir)
    agents_path.write_text(
        "# Agent Rules\n\n"
        "<!-- BEGIN:PROMOTED_VALUES -->\n"
        f"- [{promoted_entry.id}] {promoted_entry.description}\n"
        "<!-- END:PROMOTED_VALUES -->\n",
        encoding="utf-8",
    )

    preview = json.loads(
        memory_values_delete(
            id=str(promoted_entry.id),
            confirm=False,
            memory_dir=str(tmp_memory_dir),
        )
    )
    payload = json.loads(
        memory_values_delete(
            id=str(promoted_entry.id),
            confirm=True,
            memory_dir=str(tmp_memory_dir),
        )
    )

    assert preview["ok"] is True
    assert preview["deleted_id"] == str(promoted_entry.id)
    assert preview["description"] == promoted_entry.description[:80]
    assert preview["preview"] is True
    assert preview["was_promoted"] is True
    assert preview["entry_line"] == f"- [{promoted_entry.id}] {promoted_entry.description}"
    assert payload == {
        "ok": True,
        "deleted_id": str(promoted_entry.id),
        "description": "Prefer reversible schema migrations",
        "deleted": True,
        "was_promoted": True,
    }
    assert ValuesRepository(tmp_memory_dir).find_by_id(promoted_entry.id) is None
    assert str(promoted_entry.id) not in agents_path.read_text(encoding="utf-8")


def test_memory_values_delete_with_reason_echoes_back(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    added = json.loads(
        memory_values_add(
            description="Prefer focused diffs",
            category="workflow",
            memory_dir=str(tmp_memory_dir),
        )
    )

    payload = json.loads(
        memory_values_delete(
            id=added["id"],
            reason="cleanup duplicate value",
            memory_dir=str(tmp_memory_dir),
        )
    )

    assert payload == {
        "ok": True,
        "deleted_id": added["id"],
        "description": "Prefer focused diffs",
        "deleted": True,
        "was_promoted": False,
        "reason": "cleanup duplicate value",
    }


def test_memory_values_delete_promoted_missing_markers_suggests_memory_init(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    agents_path = tmp_memory_dir.parent / "AGENTS.md"
    promoted_entry = _seed_promoted_entry(tmp_memory_dir)
    agents_path.write_text("# Agent Rules\n", encoding="utf-8")

    payload = json.loads(
        memory_values_delete(
            id=str(promoted_entry.id),
            memory_dir=str(tmp_memory_dir),
        )
    )

    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert "Run memory_init to recreate them." in payload["message"]
    assert "Run `memory_init`" in payload["hint"]
