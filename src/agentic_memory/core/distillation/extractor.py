from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from agentic_memory.core.knowledge.model import Domain
from agentic_memory.core.values.model import Category


def _normalize_tags(tags: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        candidate = str(tag).strip()
        if not candidate:
            continue
        key = candidate.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(candidate)
    return normalized


@dataclass(frozen=True, slots=True)
class KnowledgeCandidate:
    title: str
    content: str
    domain: str
    tags: list[str] = field(default_factory=list)
    source_ref: str = ""
    source_summary: str = ""

    def __post_init__(self) -> None:
        title = str(self.title).strip()
        content = str(self.content).strip()
        source_ref = str(self.source_ref).strip()
        source_summary = str(self.source_summary).strip()
        if not title:
            raise ValueError("KnowledgeCandidate.title cannot be empty")
        if not content:
            raise ValueError("KnowledgeCandidate.content cannot be empty")
        if not source_ref:
            raise ValueError("KnowledgeCandidate.source_ref cannot be empty")
        if not source_summary:
            raise ValueError("KnowledgeCandidate.source_summary cannot be empty")

        object.__setattr__(self, "title", title)
        object.__setattr__(self, "content", content)
        object.__setattr__(self, "domain", str(Domain.normalize(self.domain)))
        object.__setattr__(self, "tags", _normalize_tags(self.tags))
        object.__setattr__(self, "source_ref", source_ref)
        object.__setattr__(self, "source_summary", source_summary)


@dataclass(frozen=True, slots=True)
class ValuesCandidate:
    description: str
    category: str
    source_ref: str
    source_summary: str
    confidence_delta: float | None = None

    def __post_init__(self) -> None:
        description = str(self.description).strip()
        source_ref = str(self.source_ref).strip()
        source_summary = str(self.source_summary).strip()
        if not description:
            raise ValueError("ValuesCandidate.description cannot be empty")
        if not source_ref:
            raise ValueError("ValuesCandidate.source_ref cannot be empty")
        if not source_summary:
            raise ValueError("ValuesCandidate.source_summary cannot be empty")

        object.__setattr__(self, "description", description)
        object.__setattr__(self, "category", str(Category.normalize(self.category)))
        object.__setattr__(self, "source_ref", source_ref)
        object.__setattr__(self, "source_summary", source_summary)
        if self.confidence_delta is not None:
            object.__setattr__(self, "confidence_delta", float(self.confidence_delta))


class DistillationExtractorPort(ABC):
    @abstractmethod
    def extract_knowledge(
        self,
        notes_content: list[dict[str, Any]],
        domain: str | None,
    ) -> list[KnowledgeCandidate]:
        raise NotImplementedError

    @abstractmethod
    def extract_values(
        self,
        notes_content: list[dict[str, Any]],
        decisions_content: str | None,
        category: str | None,
    ) -> list[ValuesCandidate]:
        raise NotImplementedError


class MockExtractorPort(DistillationExtractorPort):
    def __init__(
        self,
        *,
        knowledge_candidates: list[KnowledgeCandidate] | None = None,
        values_candidates: list[ValuesCandidate] | None = None,
    ) -> None:
        self.knowledge_candidates = list(knowledge_candidates or [])
        self.values_candidates = list(values_candidates or [])

    def extract_knowledge(
        self,
        notes_content: list[dict[str, Any]],
        domain: str | None,
    ) -> list[KnowledgeCandidate]:
        del notes_content, domain
        return list(self.knowledge_candidates)

    def extract_values(
        self,
        notes_content: list[dict[str, Any]],
        decisions_content: str | None,
        category: str | None,
    ) -> list[ValuesCandidate]:
        del notes_content, decisions_content, category
        return list(self.values_candidates)


class UnconfiguredExtractorPort(DistillationExtractorPort):
    def extract_knowledge(
        self,
        notes_content: list[dict[str, Any]],
        domain: str | None,
    ) -> list[KnowledgeCandidate]:
        del notes_content, domain
        raise NotImplementedError("Distillation extractor is not configured")

    def extract_values(
        self,
        notes_content: list[dict[str, Any]],
        decisions_content: str | None,
        category: str | None,
    ) -> list[ValuesCandidate]:
        del notes_content, decisions_content, category
        raise NotImplementedError("Distillation extractor is not configured")


__all__ = [
    "DistillationExtractorPort",
    "KnowledgeCandidate",
    "MockExtractorPort",
    "UnconfiguredExtractorPort",
    "ValuesCandidate",
]
