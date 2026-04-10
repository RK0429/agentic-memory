from __future__ import annotations

# REQ-NF-001 / REQ-NF-002 benchmark coverage for knowledge/values search and distillation.
import math
import time
from collections.abc import Callable
from pathlib import Path
from typing import Final

import pytest

from agentic_memory.core.distillation import (
    DistillationService,
    KnowledgeCandidate,
    MockExtractorPort,
    ValuesCandidate,
)
from agentic_memory.core.knowledge import KnowledgeEntry, KnowledgeRepository, KnowledgeService
from agentic_memory.core.values import (
    SourceType,
    ValuesEntry,
    ValuesRepository,
    ValuesService,
)

ENTRY_COUNT: Final[int] = 1000
MEASUREMENT_COUNT: Final[int] = 100
SEARCH_P95_THRESHOLD_MS: Final[float] = 500.0
DISTILLATION_THRESHOLD_S: Final[float] = 5.0


def _p95_milliseconds(times_ms: list[float]) -> float:
    sorted_times = sorted(times_ms)
    index = math.ceil(len(sorted_times) * 0.95) - 1
    return sorted_times[index]


def _measure_p95_ms(func: Callable[[], object]) -> float:
    func()
    times_ms: list[float] = []
    for _ in range(MEASUREMENT_COUNT):
        started_at = time.perf_counter()
        func()
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        times_ms.append(elapsed_ms)
    return _p95_milliseconds(times_ms)


def _seed_knowledge_entries(memory_dir: Path) -> None:
    repository = KnowledgeRepository(memory_dir)
    for index in range(ENTRY_COUNT):
        repository.save(
            KnowledgeEntry(
                title=f"Knowledge entry {index}",
                content=(
                    f"Detailed content about topic {index} with extra words "
                    "to simulate real entries."
                ),
                domain=f"domain-{index % 10}",
                tags=[f"tag-{index % 5}", f"tag-{(index + 1) % 7}"],
                accuracy="uncertain",
                source_type=SourceType.USER_TAUGHT,
            )
        )


def _seed_values_entries(memory_dir: Path) -> None:
    repository = ValuesRepository(memory_dir)
    for index in range(ENTRY_COUNT):
        repository.save(
            ValuesEntry(
                description=f"Value preference about approach {index} with context.",
                category=f"category-{index % 8}",
                confidence=0.3 + (index % 7) * 0.1,
                source_type=SourceType.USER_TAUGHT,
            )
        )


def _write_note(memory_dir: Path, *, index: int) -> Path:
    date = f"2026-01-{(index % 25) + 1:02d}"
    note_dir = memory_dir / date
    note_dir.mkdir(parents=True, exist_ok=True)
    note_path = note_dir / f"note_{index:03d}.md"
    note_path.write_text(
        "\n".join(
            [
                f"# Benchmark note {index}",
                "",
                f"- Date: {date}",
                "- Time: 09:00 - 09:30",
                "",
                "## 判断",
                "",
                f"- Decision {index} about topic {index}",
                "",
                "## 成果",
                "",
                f"- Outcome {index} for topic {index}",
                "",
                "## 作業ログ",
                "",
                f"- Work log {index} with extra benchmark words",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return note_path


def _build_candidates(memory_dir: Path, note_paths: list[Path]) -> list[KnowledgeCandidate]:
    return [
        KnowledgeCandidate(
            title=f"Distilled topic {index}",
            content=f"Collected benchmark knowledge from note {index}.",
            domain=f"domain-{index % 10}",
            tags=[f"tag-{index % 5}"],
            source_ref=str(note_path.relative_to(memory_dir.parent)),
            source_summary=f"Benchmark note {index} ({note_path.parent.name})",
        )
        for index, note_path in enumerate(note_paths[:5])
    ]


def _build_values_candidates(memory_dir: Path, note_paths: list[Path]) -> list[ValuesCandidate]:
    return [
        ValuesCandidate(
            description=f"Prefer benchmark workflow {index} when processing notes.",
            category=f"category-{index % 8}",
            source_ref=str(note_path.relative_to(memory_dir.parent)),
            source_summary=f"Benchmark note {index} ({note_path.parent.name})",
        )
        for index, note_path in enumerate(note_paths[:5])
    ]


@pytest.mark.benchmark
def test_knowledge_search_p95_under_500ms(tmp_memory_dir: Path) -> None:
    _seed_knowledge_entries(tmp_memory_dir)
    service = KnowledgeService()

    p95_ms = _measure_p95_ms(
        lambda: service.search(tmp_memory_dir, query="topic", top=10),
    )

    assert p95_ms <= SEARCH_P95_THRESHOLD_MS, f"knowledge search p95={p95_ms:.2f}ms"


@pytest.mark.benchmark
def test_values_search_p95_under_500ms(tmp_memory_dir: Path) -> None:
    _seed_values_entries(tmp_memory_dir)
    service = ValuesService()

    p95_ms = _measure_p95_ms(
        lambda: service.search(tmp_memory_dir, query="approach", top=10),
    )

    assert p95_ms <= SEARCH_P95_THRESHOLD_MS, f"values search p95={p95_ms:.2f}ms"


@pytest.mark.benchmark
def test_distillation_collect_integrate_under_5s_per_100_notes(
    tmp_memory_dir: Path,
) -> None:
    note_paths = [_write_note(tmp_memory_dir, index=index) for index in range(100)]
    extractor = MockExtractorPort(
        knowledge_candidates=_build_candidates(tmp_memory_dir, note_paths)
    )
    service = DistillationService()

    started_at = time.perf_counter()
    report = service.distill_knowledge(
        tmp_memory_dir,
        date_from="2026-01-01",
        date_to="2026-01-31",
        domain=None,
        dry_run=False,
        extractor=extractor,
    )
    elapsed_s = time.perf_counter() - started_at

    assert report.new_count == 5
    assert len(KnowledgeRepository(tmp_memory_dir).list_all()) == 5
    assert elapsed_s <= DISTILLATION_THRESHOLD_S, f"distillation time={elapsed_s:.2f}s"


@pytest.mark.benchmark
def test_values_distillation_collect_integrate_under_5s_per_100_notes(
    tmp_memory_dir: Path,
) -> None:
    note_paths = [_write_note(tmp_memory_dir, index=index) for index in range(100)]
    extractor = MockExtractorPort(
        values_candidates=_build_values_candidates(tmp_memory_dir, note_paths)
    )
    service = DistillationService()

    started_at = time.perf_counter()
    report = service.distill_values(
        tmp_memory_dir,
        date_from="2026-01-01",
        date_to="2026-01-31",
        category=None,
        dry_run=False,
        extractor=extractor,
    )
    elapsed_s = time.perf_counter() - started_at

    assert report.new_count == 5
    assert len(ValuesRepository(tmp_memory_dir).list_all()) == 5
    assert elapsed_s <= DISTILLATION_THRESHOLD_S, f"distillation time={elapsed_s:.2f}s"
