from __future__ import annotations

from pathlib import Path

from agentic_memory.core import state
from agentic_memory.core.distillation import (
    DistillationService,
    DistillationTrigger,
    KnowledgeCandidate,
    MockExtractorPort,
    ValuesCandidate,
)
from agentic_memory.core.values import ValuesRepository, ValuesService


def _write_note(
    memory_dir: Path,
    *,
    date: str,
    name: str,
    title: str,
    decisions: list[str] | None = None,
    outcome: list[str] | None = None,
    work_log: list[str] | None = None,
    pitfalls: list[str] | None = None,
) -> Path:
    note_dir = memory_dir / date
    note_dir.mkdir(parents=True, exist_ok=True)
    note_path = note_dir / name
    lines = [
        f"# {title}",
        "",
        f"- Date: {date}",
        "- Time: 09:00 - 09:30",
        "",
    ]
    if decisions is not None:
        lines.extend(["## 判断", "", *[f"- {item}" for item in decisions], ""])
    if outcome is not None:
        lines.extend(["## 成果", "", *[f"- {item}" for item in outcome], ""])
    if work_log is not None:
        lines.extend(["## 作業ログ", "", *[f"- {item}" for item in work_log], ""])
    if pitfalls is not None:
        lines.extend(["## 注意点・残課題", "", *[f"- {item}" for item in pitfalls], ""])
    note_path.write_text("\n".join(lines), encoding="utf-8")
    return note_path


def test_distill_knowledge_dry_run_returns_candidates_without_persisting(
    tmp_memory_dir: Path,
) -> None:
    note_path = _write_note(
        tmp_memory_dir,
        date="2026-04-09",
        name="0900_knowledge.md",
        title="Knowledge Source",
        decisions=["Rust ownership clarified borrow rules"],
        outcome=["Explained the ownership model"],
    )
    service = DistillationService()
    extractor = MockExtractorPort(
        knowledge_candidates=[
            KnowledgeCandidate(
                title="Rust ownership",
                content="Ownership explains moves and borrows.",
                domain="rust",
                source_ref=str(note_path.relative_to(tmp_memory_dir.parent)),
                source_summary="Knowledge Source (2026-04-09)",
            )
        ]
    )

    report = service.distill_knowledge(
        tmp_memory_dir,
        date_from="2026-04-01",
        date_to="2026-04-10",
        domain=None,
        dry_run=True,
        extractor=extractor,
    )

    assert report.new_count == 1
    assert report.secret_skipped_count == 0
    assert not (tmp_memory_dir / "_knowledge.jsonl").exists()
    assert state.load_state_frontmatter(tmp_memory_dir / "_state.md") == {
        "last_knowledge_distilled_at": None,
        "last_values_distilled_at": None,
        "last_knowledge_evaluated_at": None,
        "last_values_evaluated_at": None,
    }


def test_distill_values_persists_and_updates_frontmatter(tmp_memory_dir: Path) -> None:
    _write_note(
        tmp_memory_dir,
        date="2026-04-08",
        name="0900_values.md",
        title="Values Source",
        decisions=["Asked for regression tests on a bug fix"],
    )
    state.cmd_add(
        tmp_memory_dir / "_state.md",
        "decisions",
        ["[2026-04-10 09:00] Asked for regression tests again"],
    )
    service = DistillationService()
    extractor = MockExtractorPort(
        values_candidates=[
            ValuesCandidate(
                description="Require regression tests for bug fixes",
                category="review",
                source_ref="_state.md#decisions",
                source_summary="[2026-04-10 09:00] Asked for regression tests again",
            )
        ]
    )

    report = service.distill_values(
        tmp_memory_dir,
        date_from="2026-04-01",
        date_to="2026-04-10",
        category=None,
        dry_run=False,
        extractor=extractor,
    )

    assert report.new_count == 1
    entries = ValuesRepository(tmp_memory_dir).list_all()
    assert len(entries) == 1
    assert entries[0].evidence[0].date == "2026-04-10"
    assert entries[0].source_type.value == "memory_distillation"
    frontmatter = state.load_state_frontmatter(tmp_memory_dir / "_state.md")
    assert frontmatter["last_values_evaluated_at"] is not None
    assert frontmatter["last_values_distilled_at"] is not None


def test_distill_values_contradiction_updates_confidence_but_not_distilled_timestamp(
    tmp_memory_dir: Path,
) -> None:
    seeded, _warnings = ValuesService().add(
        tmp_memory_dir,
        description="Require regression tests for bug fixes",
        category="review",
    )
    service = DistillationService()
    extractor = MockExtractorPort(
        values_candidates=[
            ValuesCandidate(
                description="Avoid regression tests for bug fixes",
                category="review",
                source_ref="_state.md#decisions",
                source_summary="[2026-04-10 10:00] Avoided regression tests",
            )
        ]
    )

    report = service.distill_values(
        tmp_memory_dir,
        date_from=None,
        date_to="2026-04-10",
        category=None,
        dry_run=False,
        extractor=extractor,
    )

    updated = ValuesRepository(tmp_memory_dir).load(seeded.id)
    assert report.contradicted_count == 1
    assert updated.confidence < 0.3
    frontmatter = state.load_state_frontmatter(tmp_memory_dir / "_state.md")
    assert frontmatter["last_values_evaluated_at"] is not None
    assert frontmatter["last_values_distilled_at"] is None


def test_distillation_trigger_uses_note_count_or_elapsed_time() -> None:
    trigger = DistillationTrigger()

    assert trigger.should_distill(notes_since_last=0, hours_since_last=None) is False
    assert trigger.should_distill(notes_since_last=1, hours_since_last=None) is True
    assert trigger.should_distill(notes_since_last=10, hours_since_last=1.0) is True
    assert trigger.should_distill(notes_since_last=0, hours_since_last=168.0) is True
    assert trigger.should_distill(notes_since_last=3, hours_since_last=10.0) is False
