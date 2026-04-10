from __future__ import annotations

from pathlib import Path

import pytest

from agentic_memory.core.config import PROMOTED_VALUES_BEGIN, PROMOTED_VALUES_END
from agentic_memory.core.values import (
    PromotionManager,
    PromotionService,
    SourceType,
    ValuesEntry,
    ValuesRepository,
)


def _agents_content() -> str:
    return f"# Agent Rules\n\n{PROMOTED_VALUES_BEGIN}\n{PROMOTED_VALUES_END}\n"


def _seed_entry(
    memory_dir: Path,
    *,
    description: str = "Prefer focused changes",
    confidence: float = 0.85,
    total_evidence_count: int = 5,
    promoted: bool = False,
    promoted_confidence: float | None = None,
) -> ValuesEntry:
    entry = ValuesEntry(
        description=description,
        category="workflow",
        confidence=confidence,
        evidence=[],
        total_evidence_count=total_evidence_count,
        source_type=SourceType.USER_TAUGHT,
        promoted=promoted,
        promoted_confidence=promoted_confidence,
    )
    ValuesRepository(memory_dir).save(entry)
    return entry


def test_promotion_manager_checks_candidate_and_demotion() -> None:
    candidate = ValuesEntry(
        description="Promotable",
        category="workflow",
        confidence=0.8,
        total_evidence_count=5,
        source_type=SourceType.USER_TAUGHT,
    )
    promoted = ValuesEntry(
        description="Demotable",
        category="workflow",
        confidence=0.65,
        total_evidence_count=6,
        source_type=SourceType.USER_TAUGHT,
        promoted=True,
        promoted_confidence=0.9,
    )

    assert PromotionManager.check_candidate(candidate) is True
    assert PromotionManager.check_demotion(promoted) is True


def test_promote_preview_requires_confirm_and_keeps_state(tmp_memory_dir: Path) -> None:
    agents_path = tmp_memory_dir.parent / "AGENTS.md"
    agents_path.write_text(_agents_content(), encoding="utf-8")
    entry = _seed_entry(tmp_memory_dir)
    service = PromotionService()

    preview = service.promote(tmp_memory_dir, str(entry.id), confirm=False)
    stored = ValuesRepository(tmp_memory_dir).load(entry.id)

    assert preview["preview"] is True
    assert preview["would_promote"] is True
    assert preview["entry_line"] == f"- [{entry.id}] {entry.description}"
    assert stored.promoted is False
    assert agents_path.read_text(encoding="utf-8") == _agents_content()


def test_promote_updates_agents_md_and_entry(tmp_memory_dir: Path) -> None:
    agents_path = tmp_memory_dir.parent / "AGENTS.md"
    agents_path.write_text(_agents_content(), encoding="utf-8")
    entry = _seed_entry(tmp_memory_dir, description="Prefer regression tests")
    service = PromotionService()

    result = service.promote(tmp_memory_dir, str(entry.id), confirm=True)
    stored = ValuesRepository(tmp_memory_dir).load(entry.id)

    assert result["promoted"] is True
    assert str(entry.id) in agents_path.read_text(encoding="utf-8")
    assert stored.promoted is True
    assert stored.promoted_confidence == entry.confidence
    assert stored.promoted_at is not None


def test_demote_preview_and_confirm_workflow(tmp_memory_dir: Path) -> None:
    agents_path = tmp_memory_dir.parent / "AGENTS.md"
    entry = _seed_entry(
        tmp_memory_dir,
        description="Prefer reversible migrations",
        promoted=True,
        promoted_confidence=0.9,
    )
    agents_path.write_text(
        "# Agent Rules\n\n"
        f"{PROMOTED_VALUES_BEGIN}\n"
        f"- [{entry.id}] {entry.description}\n"
        f"{PROMOTED_VALUES_END}\n",
        encoding="utf-8",
    )
    service = PromotionService()

    preview = service.demote(
        tmp_memory_dir,
        str(entry.id),
        reason="confidence dropped",
        confirm=False,
    )
    stored_before = ValuesRepository(tmp_memory_dir).load(entry.id)
    result = service.demote(
        tmp_memory_dir,
        str(entry.id),
        reason="confidence dropped",
        confirm=True,
    )
    stored_after = ValuesRepository(tmp_memory_dir).load(entry.id)

    assert preview["preview"] is True
    assert preview["entry_line"] == f"- [{entry.id}] {entry.description}"
    assert stored_before.promoted is True
    assert result["promoted"] is False
    assert stored_after.promoted is False
    assert stored_after.demotion_reason == "confidence dropped"
    assert stored_after.demoted_at is not None
    assert str(entry.id) not in agents_path.read_text(encoding="utf-8")


def test_repromotion_after_demotion_is_allowed(tmp_memory_dir: Path) -> None:
    agents_path = tmp_memory_dir.parent / "AGENTS.md"
    agents_path.write_text(_agents_content(), encoding="utf-8")
    entry = _seed_entry(
        tmp_memory_dir,
        description="Prefer reversible database changes",
        promoted=True,
        promoted_confidence=0.9,
    )
    service = PromotionService()

    service.demote(tmp_memory_dir, str(entry.id), reason="recent exceptions", confirm=True)
    result = service.promote(tmp_memory_dir, str(entry.id), confirm=True)
    stored = ValuesRepository(tmp_memory_dir).load(entry.id)

    assert result["promoted"] is True
    assert stored.promoted is True
    assert stored.demotion_reason is None


def test_promotion_service_validates_missing_agents_and_entry_state(tmp_memory_dir: Path) -> None:
    service = PromotionService()
    promotable = _seed_entry(tmp_memory_dir)
    promoted = _seed_entry(
        tmp_memory_dir,
        description="Already promoted",
        promoted=True,
        promoted_confidence=0.9,
    )
    weak = _seed_entry(
        tmp_memory_dir,
        description="Weak evidence",
        confidence=0.6,
        total_evidence_count=3,
    )

    with pytest.raises(FileNotFoundError, match="AGENTS.md not found"):
        service.promote(tmp_memory_dir, str(promotable.id), confirm=True)

    agents_path = tmp_memory_dir.parent / "AGENTS.md"
    agents_path.write_text(_agents_content(), encoding="utf-8")

    with pytest.raises(ValueError, match="already promoted"):
        service.promote(tmp_memory_dir, str(promoted.id), confirm=True)

    with pytest.raises(ValueError, match="does not meet promotion criteria"):
        service.promote(tmp_memory_dir, str(weak.id), confirm=True)

    with pytest.raises(ValueError, match="is not promoted"):
        service.demote(tmp_memory_dir, str(weak.id), reason="not promoted", confirm=True)
