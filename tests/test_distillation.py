from __future__ import annotations

from pathlib import Path

from agentic_memory.core import state
from agentic_memory.core.distillation.prepare import DistillationPreparer
from agentic_memory.core.knowledge import KnowledgeService, SourceType
from agentic_memory.core.values import ValuesService


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


def test_prepare_knowledge_returns_notes_and_schema(tmp_memory_dir: Path) -> None:
    _write_note(
        tmp_memory_dir,
        date="2026-04-09",
        name="0900_knowledge.md",
        title="Knowledge Source",
        decisions=["Rust ownership clarified borrow rules"],
        outcome=["Explained the ownership model"],
    )

    preparer = DistillationPreparer()
    result = preparer.prepare_knowledge(
        tmp_memory_dir,
        date_from="2026-04-01",
        date_to="2026-04-10",
    )

    assert len(result.notes) == 1
    assert result.notes[0]["title"] == "Knowledge Source"
    assert result.notes[0]["date"] == "2026-04-09"
    assert "decisions" in result.notes[0]["content"]
    assert result.decisions is None
    assert isinstance(result.existing_items, list)
    assert "title" in result.candidate_schema["properties"]
    assert result.instructions


def test_prepare_values_returns_notes_and_decisions(tmp_memory_dir: Path) -> None:
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

    preparer = DistillationPreparer()
    result = preparer.prepare_values(
        tmp_memory_dir,
        date_from="2026-04-01",
        date_to="2026-04-10",
    )

    assert len(result.notes) == 1
    assert result.notes[0]["title"] == "Values Source"
    assert result.decisions is not None
    assert "regression tests" in result.decisions
    assert "description" in result.candidate_schema["properties"]


def test_prepare_knowledge_filters_by_domain(tmp_memory_dir: Path) -> None:
    _write_note(
        tmp_memory_dir,
        date="2026-04-09",
        name="0900_rust.md",
        title="Rust Note",
        decisions=["Ownership is important"],
    )

    KnowledgeService().add(
        tmp_memory_dir,
        title="Python decorators",
        content="Decorators wrap functions",
        domain="python",
        origin=SourceType.USER_TAUGHT,
    )
    KnowledgeService().add(
        tmp_memory_dir,
        title="Rust ownership",
        content="Ownership manages memory",
        domain="rust",
        origin=SourceType.USER_TAUGHT,
    )

    preparer = DistillationPreparer()
    result = preparer.prepare_knowledge(
        tmp_memory_dir,
        date_from="2026-04-01",
        date_to="2026-04-10",
        domain="rust",
    )

    assert len(result.existing_items) == 1
    assert result.existing_items[0]["domain"] == "rust"


def test_prepare_values_filters_by_category(tmp_memory_dir: Path) -> None:
    _write_note(
        tmp_memory_dir,
        date="2026-04-08",
        name="0900_review.md",
        title="Review Note",
        decisions=["Regression tests are important"],
    )

    ValuesService().add(
        tmp_memory_dir,
        description="Prefer small PRs",
        category="review",
    )
    ValuesService().add(
        tmp_memory_dir,
        description="Use kebab-case for file names",
        category="naming",
    )

    preparer = DistillationPreparer()
    result = preparer.prepare_values(
        tmp_memory_dir,
        date_from="2026-04-01",
        date_to="2026-04-10",
        category="review",
    )

    assert len(result.existing_items) == 1
    assert result.existing_items[0]["category"] == "review"


def test_prepare_knowledge_empty_when_no_notes(tmp_memory_dir: Path) -> None:
    preparer = DistillationPreparer()
    result = preparer.prepare_knowledge(tmp_memory_dir)
    assert result.notes == []
    assert result.existing_items == []


def test_prepare_date_range_validation() -> None:
    import pytest

    from agentic_memory.core.distillation.prepare import _validate_date_range

    with pytest.raises(ValueError, match="date_from must be on or before date_to"):
        _validate_date_range("2026-04-10", "2026-04-01")
