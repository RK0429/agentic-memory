from __future__ import annotations

from dataclasses import dataclass

from agentic_memory.core.values import SourceType, ValuesEntry
from agentic_memory.core.values.integrator import (
    ValuesIntegrationAction,
    ValuesIntegrator,
)


@dataclass(frozen=True, slots=True)
class _ValuesCandidate:
    """Test-only concrete type satisfying ValuesCandidate protocol."""

    description: str
    category: str
    confidence_delta: float | None = None


def _entry(description: str, category: str) -> ValuesEntry:
    return ValuesEntry(
        description=description,
        category=category,
        confidence=0.6,
        origin=SourceType.MEMORY_DISTILLATION,
    )


def _candidate(description: str, category: str) -> _ValuesCandidate:
    return _ValuesCandidate(
        description=description,
        category=category,
    )


def test_integrate_skips_duplicate_values() -> None:
    integrator = ValuesIntegrator()
    existing = [_entry("Require regression tests for bug fixes", "review")]

    result = integrator.integrate(
        _candidate(" Require regression tests for bug fixes ", "review"),
        existing,
    )

    assert result.action is ValuesIntegrationAction.SKIP_DUPLICATE
    assert result.target_id is None


def test_integrate_reinforces_similar_values() -> None:
    integrator = ValuesIntegrator()
    existing = [_entry("Require regression tests for bug fixes", "review")]

    result = integrator.integrate(
        _candidate("Add regression tests whenever fixing bugs", "review"),
        existing,
    )

    assert result.action is ValuesIntegrationAction.REINFORCE_EXISTING
    assert result.target_id == str(existing[0].id)
    assert result.confidence_delta is not None
    assert result.confidence_delta > 0


def test_integrate_detects_contradicting_values() -> None:
    integrator = ValuesIntegrator()
    existing = [_entry("Require regression tests for bug fixes", "review")]

    result = integrator.integrate(
        _candidate("Avoid regression tests for bug fixes", "review"),
        existing,
    )

    assert result.action is ValuesIntegrationAction.CONTRADICT_EXISTING
    assert result.target_id == str(existing[0].id)
    assert result.confidence_delta is not None
    assert result.confidence_delta < 0
    assert result.contradiction_detail is not None


def test_integrate_creates_new_for_distinct_value() -> None:
    integrator = ValuesIntegrator()
    existing = [_entry("Require regression tests for bug fixes", "review")]

    result = integrator.integrate(
        _candidate("Prefer concise pull request summaries", "communication"),
        existing,
    )

    assert result.action is ValuesIntegrationAction.CREATE_NEW
    assert result.target_id is None
