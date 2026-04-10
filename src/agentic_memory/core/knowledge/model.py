from __future__ import annotations

import datetime as dt
import json
import re
import unicodedata
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, cast

_KNOWLEDGE_ID_RE = re.compile(r"^k-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_SPACE_RE = re.compile(r"\s+")
_KEBAB_SEPARATOR_RE = re.compile(r"[\s_]+")
_NON_KEBAB_RE = re.compile(r"[^\w-]")
_MULTI_HYPHEN_RE = re.compile(r"-+")


def _now() -> dt.datetime:
    return dt.datetime.now().replace(microsecond=0)


def _normalize_text(value: str) -> str:
    return _SPACE_RE.sub(" ", unicodedata.normalize("NFC", value).strip())


def _normalize_kebab(value: str) -> str:
    normalized = unicodedata.normalize("NFC", str(value)).strip()
    normalized = _KEBAB_SEPARATOR_RE.sub("-", normalized)
    normalized = _NON_KEBAB_RE.sub("", normalized)
    normalized = _MULTI_HYPHEN_RE.sub("-", normalized).strip("-")
    return normalized.lower()


def _normalize_tags(tags: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        candidate = _normalize_text(str(tag))
        if not candidate:
            continue
        key = candidate.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(candidate)
    return normalized


def _coerce_datetime(value: dt.datetime | str) -> dt.datetime:
    if isinstance(value, dt.datetime):
        return value
    return dt.datetime.fromisoformat(value)


def is_substantially_equal(a: str, b: str) -> bool:
    return _normalize_text(a) == _normalize_text(b)


class Accuracy(StrEnum):
    VERIFIED = "verified"
    LIKELY = "likely"
    UNCERTAIN = "uncertain"


class SourceType(StrEnum):
    MEMORY_DISTILLATION = "memory_distillation"
    AUTONOMOUS_RESEARCH = "autonomous_research"
    USER_TAUGHT = "user_taught"


class UserUnderstanding(StrEnum):
    UNKNOWN = "unknown"
    NOVICE = "novice"
    FAMILIAR = "familiar"
    PROFICIENT = "proficient"
    EXPERT = "expert"


class KnowledgeId(str):
    def __new__(cls, value: str) -> KnowledgeId:
        normalized = str(value).strip()
        if not _KNOWLEDGE_ID_RE.fullmatch(normalized):
            raise ValueError(f"Invalid knowledge id: {value!r}")
        return str.__new__(cls, normalized)

    @property
    def value(self) -> str:
        return str(self)

    @classmethod
    def generate(cls) -> KnowledgeId:
        return cls(f"k-{uuid.uuid4()}")


class Domain(str):
    def __new__(cls, value: str) -> Domain:
        normalized = _normalize_kebab(value)
        if not normalized:
            raise ValueError("Domain cannot be empty")
        return str.__new__(cls, normalized)

    @property
    def value(self) -> str:
        return str(self)

    @classmethod
    def normalize(cls, value: str) -> Domain:
        return cls(_normalize_kebab(value))


@dataclass(frozen=True, slots=True)
class Source:
    type: SourceType
    ref: str
    summary: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "type", SourceType(self.type))
        object.__setattr__(self, "ref", str(self.ref).strip())
        object.__setattr__(self, "summary", str(self.summary).strip())
        if not self.ref:
            raise ValueError("Source.ref cannot be empty")
        if not self.summary:
            raise ValueError("Source.summary cannot be empty")

    def to_dict(self) -> dict[str, str]:
        return {
            "type": self.type.value,
            "ref": self.ref,
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Source:
        return cls(
            type=SourceType(str(payload["type"])),
            ref=str(payload["ref"]),
            summary=str(payload["summary"]),
        )


@dataclass(slots=True, kw_only=True)
class KnowledgeEntry:
    title: str
    content: str
    domain: Domain | str
    source_type: SourceType | str
    id: KnowledgeId | str = field(default_factory=KnowledgeId.generate)
    tags: list[str] = field(default_factory=list)
    accuracy: Accuracy | str = Accuracy.UNCERTAIN
    sources: list[Source] = field(default_factory=list)
    user_understanding: UserUnderstanding | str = UserUnderstanding.UNKNOWN
    related: list[KnowledgeId | str] = field(default_factory=list)
    created_at: dt.datetime | str = field(default_factory=_now)
    updated_at: dt.datetime | str = field(default_factory=_now)

    def __post_init__(self) -> None:
        self.id = self.id if isinstance(self.id, KnowledgeId) else KnowledgeId(str(self.id))
        self.title = str(self.title).strip()
        self.content = str(self.content).strip()
        if not self.title:
            raise ValueError("KnowledgeEntry.title cannot be empty")
        if not self.content:
            raise ValueError("KnowledgeEntry.content cannot be empty")
        self.domain = (
            self.domain if isinstance(self.domain, Domain) else Domain.normalize(self.domain)
        )
        self.tags = _normalize_tags(self.tags)
        self.accuracy = Accuracy(self.accuracy)
        self.sources = [
            source if isinstance(source, Source) else Source.from_dict(source)
            for source in self.sources
        ]
        self.source_type = SourceType(self.source_type)
        self.user_understanding = UserUnderstanding(self.user_understanding)
        self.related = [
            related if isinstance(related, KnowledgeId) else KnowledgeId(str(related))
            for related in self.related
            if str(related).strip()
        ]
        self.created_at = _coerce_datetime(self.created_at)
        self.updated_at = _coerce_datetime(self.updated_at)

    def add_sources(self, new_sources: Iterable[Source | dict[str, Any]]) -> None:
        existing = list(self.sources)
        for source in new_sources:
            candidate = source if isinstance(source, Source) else Source.from_dict(source)
            if candidate not in existing:
                existing.append(candidate)
        self.sources = existing
        self.updated_at = _now()

    def to_dict(self) -> dict[str, Any]:
        accuracy = cast(Accuracy, self.accuracy)
        source_type = cast(SourceType, self.source_type)
        user_understanding = cast(UserUnderstanding, self.user_understanding)
        created_at = cast(dt.datetime, self.created_at)
        updated_at = cast(dt.datetime, self.updated_at)
        return {
            "id": str(self.id),
            "title": self.title,
            "content": self.content,
            "domain": str(self.domain),
            "tags": list(self.tags),
            "accuracy": accuracy.value,
            "sources": [source.to_dict() for source in self.sources],
            "source_type": source_type.value,
            "user_understanding": user_understanding.value,
            "related": [str(related) for related in self.related],
            "created_at": created_at.isoformat(timespec="seconds"),
            "updated_at": updated_at.isoformat(timespec="seconds"),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> KnowledgeEntry:
        return cls(
            id=payload.get("id", KnowledgeId.generate()),
            title=str(payload["title"]),
            content=str(payload["content"]),
            domain=payload["domain"],
            tags=list(payload.get("tags") or []),
            accuracy=payload.get("accuracy", Accuracy.UNCERTAIN.value),
            sources=[Source.from_dict(item) for item in list(payload.get("sources") or [])],
            source_type=payload["source_type"],
            user_understanding=payload.get("user_understanding", UserUnderstanding.UNKNOWN.value),
            related=list(payload.get("related") or []),
            created_at=payload.get("created_at", _now()),
            updated_at=payload.get("updated_at", _now()),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


__all__ = [
    "Accuracy",
    "Domain",
    "KnowledgeEntry",
    "KnowledgeId",
    "Source",
    "SourceType",
    "UserUnderstanding",
    "is_substantially_equal",
]
