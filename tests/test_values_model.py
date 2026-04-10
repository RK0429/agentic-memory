from __future__ import annotations

import pytest

from agentic_memory.core.values import (
    Category,
    Evidence,
    PromotionState,
    SourceType,
    ValuesEntry,
    ValuesId,
)


def _evidence(index: int) -> Evidence:
    return Evidence(
        ref=f"memory/2026-04-{index:02d}/note.md",
        summary=f"evidence-{index}",
        date=f"2026-04-{index:02d}",
    )


def test_values_id_generate_uses_v_prefix() -> None:
    generated = ValuesId.generate()
    assert str(generated).startswith("v-")


def test_values_entry_roundtrip_serialization() -> None:
    entry = ValuesEntry(
        description="Prefer small, focused changes.",
        category=" Workflow ",
        confidence=0.85,
        evidence=[_evidence(1), _evidence(2)],
        total_evidence_count=7,
        source_type=SourceType.USER_TAUGHT,
        promoted=True,
        promoted_confidence=0.85,
    )

    payload = entry.to_dict()
    restored = ValuesEntry.from_dict(payload)

    assert payload["source_type"] == "user_taught"
    assert payload["total_evidence_count"] == 7
    assert payload["promoted_confidence"] == 0.85
    assert restored.id == entry.id
    assert restored.category == "workflow"
    assert restored.evidence == entry.evidence
    assert restored.to_dict() == payload


def test_values_entry_rejects_out_of_range_confidence() -> None:
    with pytest.raises(ValueError):
        ValuesEntry(
            description="bad confidence",
            category="workflow",
            confidence=1.1,
            source_type=SourceType.MEMORY_DISTILLATION,
        )


def test_values_entry_keeps_evidence_newest_first_with_limit() -> None:
    entry = ValuesEntry(
        description="Collect evidence",
        category="workflow",
        confidence=0.5,
        evidence=[_evidence(index) for index in range(1, 12)],
        source_type=SourceType.MEMORY_DISTILLATION,
    )

    assert len(entry.evidence) == 10
    assert entry.total_evidence_count == 11
    assert entry.evidence[0].summary == "evidence-1"
    assert entry.evidence[-1].summary == "evidence-10"

    newest = Evidence(ref="memory/2026-04-12/new.md", summary="newest", date="2026-04-12")
    entry.add_evidence(newest)

    assert len(entry.evidence) == 10
    assert entry.total_evidence_count == 12
    assert entry.evidence[0] == newest
    assert entry.evidence[-1].summary == "evidence-9"


def test_category_normalization_uses_kebab_case() -> None:
    assert Category.normalize("coding style") == "coding-style"
    assert Category.normalize("  Coding   Style  ") == "coding-style"
    assert Category.normalize("code_review / guide!") == "code-review-guide"


def test_promotion_state_reports_eligibility_and_promoted_confidence() -> None:
    entry = ValuesEntry(
        description="Promotable",
        category=Category.normalize("Coding Style"),
        confidence=0.8,
        evidence=[_evidence(index) for index in range(1, 6)],
        total_evidence_count=5,
        source_type=SourceType.AUTONOMOUS_RESEARCH,
        promoted_confidence=0.9,
    )

    assert entry.promotion_state == PromotionState(
        confidence=0.8,
        evidence_count=5,
        promoted=False,
        promoted_confidence=0.9,
    )
    assert entry.promotion_state.eligible is True
