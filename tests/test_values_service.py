from __future__ import annotations

from pathlib import Path

import pytest

from agentic_memory.core.values import (
    Evidence,
    SourceType,
    ValuesEntry,
    ValuesRepository,
    ValuesService,
)


def _evidence(index: int) -> Evidence:
    return Evidence(
        ref=f"memory/2026-04-{index:02d}/note.md",
        summary=f"evidence-{index}",
        date=f"2026-04-{index:02d}",
    )


def _seed_entry(
    memory_dir: Path,
    *,
    description: str,
    category: str = "workflow",
    confidence: float = 0.3,
    evidence_count: int = 0,
    promoted: bool = False,
    promoted_confidence: float | None = None,
    updated_at: str = "2026-04-10T09:00:00",
) -> ValuesEntry:
    entry = ValuesEntry(
        description=description,
        category=category,
        confidence=confidence,
        evidence=[_evidence(index) for index in range(1, min(evidence_count, 10) + 1)],
        total_evidence_count=evidence_count,
        source_type=SourceType.USER_TAUGHT,
        promoted=promoted,
        promoted_confidence=promoted_confidence,
        created_at=updated_at,
        updated_at=updated_at,
    )
    ValuesRepository(memory_dir).save(entry)
    return entry


def test_add_rejects_strict_duplicate_after_normalization(tmp_memory_dir: Path) -> None:
    service = ValuesService()
    service.add(
        tmp_memory_dir,
        description="Prefer small, focused changes.",
        category="Workflow",
    )

    with pytest.raises(ValueError, match="Duplicate value exists"):
        service.add(
            tmp_memory_dir,
            description="  Prefer small,   focused changes.  ",
            category=" workflow ",
        )


def test_add_defaults_to_user_taught_source_type(tmp_memory_dir: Path) -> None:
    entry, _warnings = ValuesService().add(
        tmp_memory_dir,
        description="Prefer small, focused changes.",
        category="workflow",
    )

    assert entry.source_type is SourceType.USER_TAUGHT


def test_add_includes_secret_warning_on_suspicious_description(tmp_memory_dir: Path) -> None:
    entry, warnings = ValuesService().add(
        tmp_memory_dir,
        description='Prefer storing api_key="AbCdEf1234567890" only in secrets manager.',
        category="security",
    )

    assert entry.description == 'Prefer storing api_key="AbCdEf1234567890" only in secrets manager.'
    assert warnings == [
        "Content may contain secrets (detected: generic_api_token). Review before sharing."
    ]


def test_add_reports_similarity_and_preserves_initial_evidence_order(
    tmp_memory_dir: Path,
) -> None:
    service = ValuesService()
    first, first_warnings = service.add(
        tmp_memory_dir,
        description="Prefer focused reversible changes",
        category="workflow",
    )
    assert first_warnings == []

    entry, warnings = service.add(
        tmp_memory_dir,
        description="Prefer focused reversible changes in commits",
        category="workflow",
        confidence=0.8,
        evidence=[_evidence(index) for index in range(1, 12)],
    )

    assert warnings
    assert str(first.id) in warnings[0]
    assert len(entry.evidence) == 10
    assert entry.total_evidence_count == 11
    assert entry.evidence[0].summary == "evidence-1"
    assert entry.evidence[-1].summary == "evidence-10"
    assert entry.promotion_state.eligible is True


def test_add_no_similarity_warning_for_cjk_short_prefix(tmp_memory_dir: Path) -> None:
    """Short shared CJK prefix should not trigger false positive similarity warning."""
    service = ValuesService()
    _seed_entry(
        tmp_memory_dir,
        description="コード 品質を保つ",
        category="workflow",
    )

    _entry, warnings = service.add(
        tmp_memory_dir,
        description="コード レビューを重視する",
        category="workflow",
    )

    similarity_warnings = [w for w in warnings if w.startswith("Similar value exists")]
    assert similarity_warnings == []


def test_add_detects_similarity_for_genuine_cjk_overlap(tmp_memory_dir: Path) -> None:
    """CJK descriptions sharing substantial tokens should still flag as similar."""
    service = ValuesService()
    first = _seed_entry(
        tmp_memory_dir,
        description="CI パイプラインで テストを自動実行する",
        category="workflow",
    )

    _entry, warnings = service.add(
        tmp_memory_dir,
        description="CI パイプラインで カバレッジを計測する",
        category="workflow",
    )

    similarity_warnings = [w for w in warnings if w.startswith("Similar value exists")]
    assert similarity_warnings
    assert str(first.id) in similarity_warnings[0]


def test_search_with_query_applies_filters_and_scores(tmp_memory_dir: Path) -> None:
    service = ValuesService()
    primary = _seed_entry(
        tmp_memory_dir,
        description="Add regression tests for bug fixes",
        category="workflow",
        confidence=0.9,
        updated_at="2026-04-10T09:00:00",
    )
    _seed_entry(
        tmp_memory_dir,
        description="Document release checklist",
        category="workflow",
        confidence=0.95,
        updated_at="2026-04-09T09:00:00",
    )
    _seed_entry(
        tmp_memory_dir,
        description="Add regression tests for design reviews",
        category="review",
        confidence=0.4,
        updated_at="2026-04-11T09:00:00",
    )

    results = service.search(
        tmp_memory_dir,
        query="regression tests",
        category="workflow",
        min_confidence=0.5,
        top=5,
    )

    assert [entry.id for _, entry in results] == [primary.id]
    assert results[0][0] > 0


def test_search_with_category_only_sorts_by_confidence_then_updated_at(
    tmp_memory_dir: Path,
) -> None:
    service = ValuesService()
    older = _seed_entry(
        tmp_memory_dir,
        description="Prefer verbose commit messages",
        category="workflow",
        confidence=0.7,
        updated_at="2026-04-09T09:00:00",
    )
    newer = _seed_entry(
        tmp_memory_dir,
        description="Prefer rollback-safe deploy steps",
        category="workflow",
        confidence=0.7,
        updated_at="2026-04-10T09:00:00",
    )
    highest = _seed_entry(
        tmp_memory_dir,
        description="Always add regression coverage",
        category="workflow",
        confidence=0.9,
        updated_at="2026-04-01T09:00:00",
    )

    results = service.search(tmp_memory_dir, category="workflow", top=3)

    assert [(score, entry.id) for score, entry in results] == [
        (0.9, highest.id),
        (0.7, newer.id),
        (0.7, older.id),
    ]


def test_update_adds_evidence_and_returns_promotion_candidate(tmp_memory_dir: Path) -> None:
    service = ValuesService()
    entry, _ = service.add(
        tmp_memory_dir,
        description="Require regression coverage for bug fixes",
        category="review",
        confidence=0.8,
        evidence=[_evidence(index) for index in range(1, 5)],
    )

    updated, notifications = service.update(
        tmp_memory_dir,
        id=str(entry.id),
        add_evidence=_evidence(5),
    )

    assert updated.total_evidence_count == 5
    assert updated.evidence[0].summary == "evidence-5"
    assert notifications == {"promotion_candidate": True}


def test_update_rejects_duplicate_description_and_requires_fields(
    tmp_memory_dir: Path,
) -> None:
    service = ValuesService()
    first, _ = service.add(
        tmp_memory_dir,
        description="Prefer fast feedback loops",
        category="workflow",
    )
    second, _ = service.add(
        tmp_memory_dir,
        description="Prefer explicit review plans",
        category="workflow",
    )

    with pytest.raises(ValueError, match="At least one update field is required"):
        service.update(tmp_memory_dir, id=str(first.id))

    with pytest.raises(ValueError, match="Duplicate value exists"):
        service.update(
            tmp_memory_dir,
            id=str(second.id),
            description=" Prefer   fast feedback loops ",
        )


def test_update_includes_secret_warning_when_description_changed(
    tmp_memory_dir: Path,
) -> None:
    service = ValuesService()
    entry, _ = service.add(
        tmp_memory_dir,
        description="Prefer documented secret handling",
        category="security",
    )

    updated, notifications = service.update(
        tmp_memory_dir,
        id=str(entry.id),
        description='Prefer documenting auth_token="AbCdEf1234567890" handling',
    )

    assert updated.description == 'Prefer documenting auth_token="AbCdEf1234567890" handling'
    assert notifications["secret_warnings"] == [
        "Content may contain secrets (detected: generic_api_token). Review before sharing."
    ]


def test_update_no_secret_warning_when_description_unchanged(tmp_memory_dir: Path) -> None:
    service = ValuesService()
    entry, _ = service.add(
        tmp_memory_dir,
        description="Prefer explicit rollback plans",
        category="workflow",
    )

    _updated, notifications = service.update(
        tmp_memory_dir,
        id=str(entry.id),
        confidence=0.6,
    )

    assert "secret_warnings" not in notifications


def test_update_returns_demotion_candidate_for_promoted_entry(tmp_memory_dir: Path) -> None:
    service = ValuesService()
    entry = _seed_entry(
        tmp_memory_dir,
        description="Prefer conservative schema changes",
        category="design",
        confidence=0.9,
        evidence_count=6,
        promoted=True,
        promoted_confidence=0.9,
    )

    updated, notifications = service.update(
        tmp_memory_dir,
        id=str(entry.id),
        confidence=0.7,
    )

    assert updated.confidence == 0.7
    assert notifications == {"demotion_candidate": True}


def test_list_values_filters_and_sorts(tmp_memory_dir: Path) -> None:
    service = ValuesService()
    included_high = _seed_entry(
        tmp_memory_dir,
        description="Prefer paired review on risky changes",
        category="review",
        confidence=0.9,
        promoted=True,
        promoted_confidence=0.9,
        updated_at="2026-04-10T10:00:00",
    )
    _seed_entry(
        tmp_memory_dir,
        description="Prefer draft PRs for large work",
        category="review",
        confidence=0.95,
        promoted=False,
        updated_at="2026-04-11T10:00:00",
    )
    included_low = _seed_entry(
        tmp_memory_dir,
        description="Prefer reviewer context in PR body",
        category="review",
        confidence=0.7,
        promoted=True,
        promoted_confidence=0.7,
        updated_at="2026-04-09T10:00:00",
    )

    results = service.list_values(
        tmp_memory_dir,
        min_confidence=0.6,
        category="review",
        promoted_only=True,
        top=5,
    )

    assert [entry.id for entry in results] == [included_high.id, included_low.id]


def test_list_values_defaults_to_zero_min_confidence(tmp_memory_dir: Path) -> None:
    service = ValuesService()
    low_confidence = _seed_entry(
        tmp_memory_dir,
        description="Prefer low-confidence experiments",
        category="workflow",
        confidence=0.4,
        updated_at="2026-04-10T10:00:00",
    )
    included = _seed_entry(
        tmp_memory_dir,
        description="Prefer high-confidence changes",
        category="workflow",
        confidence=0.5,
        updated_at="2026-04-11T10:00:00",
    )

    results = service.list_values(tmp_memory_dir)

    assert [entry.id for entry in results] == [included.id, low_confidence.id]


def test_delete_returns_metadata_and_reason_for_non_promoted_entry(
    tmp_memory_dir: Path,
) -> None:
    service = ValuesService()
    entry = _seed_entry(
        tmp_memory_dir,
        description="Prefer focused diffs",
        category="workflow",
    )

    payload = service.delete(
        tmp_memory_dir,
        id=str(entry.id),
        reason="cleanup duplicate value",
    )

    assert payload == {
        "deleted_id": str(entry.id),
        "description": "Prefer focused diffs",
        "deleted": True,
        "was_promoted": False,
        "reason": "cleanup duplicate value",
    }
    assert ValuesRepository(tmp_memory_dir).find_by_id(entry.id) is None


def test_delete_truncates_long_description_with_ellipsis(tmp_memory_dir: Path) -> None:
    service = ValuesService()
    description = (
        "Prefer focused diffs with explicit rollback steps and reviewer context in every change."
    )
    entry = _seed_entry(
        tmp_memory_dir,
        description=description,
        category="workflow",
    )

    payload = service.delete(tmp_memory_dir, id=str(entry.id))

    assert payload["description"] == description[:80] + "…"
    assert ValuesRepository(tmp_memory_dir).find_by_id(entry.id) is None


def test_delete_promoted_missing_markers_suggests_memory_init(
    tmp_memory_dir: Path,
) -> None:
    service = ValuesService()
    entry = _seed_entry(
        tmp_memory_dir,
        description="Prefer reversible schema migrations",
        category="design",
        confidence=0.9,
        evidence_count=6,
        promoted=True,
        promoted_confidence=0.9,
    )
    agents_path = tmp_memory_dir.parent / "AGENTS.md"
    agents_path.write_text("# Agent Rules\n", encoding="utf-8")

    with pytest.raises(
        ValueError,
        match="AGENTS.md is missing promoted values markers. Run memory_init to recreate them.",
    ):
        service.delete(tmp_memory_dir, id=str(entry.id))
