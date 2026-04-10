from __future__ import annotations

import datetime as dt
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, cast

from agentic_memory.core.knowledge.model import (
    SourceType,
    _normalize_kebab,
    is_substantially_equal,
)

_VALUES_ID_RE = re.compile(r"^v-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def _now() -> dt.datetime:
    return dt.datetime.now().replace(microsecond=0)


def _coerce_datetime(value: dt.datetime | str | None) -> dt.datetime | None:
    if value is None or isinstance(value, dt.datetime):
        return value
    return dt.datetime.fromisoformat(value)


class ValuesId(str):
    def __new__(cls, value: str) -> ValuesId:
        normalized = str(value).strip()
        if not _VALUES_ID_RE.fullmatch(normalized):
            raise ValueError(f"Invalid values id: {value!r}")
        return str.__new__(cls, normalized)

    @property
    def value(self) -> str:
        return str(self)

    @classmethod
    def generate(cls) -> ValuesId:
        return cls(f"v-{uuid.uuid4()}")


class Category(str):
    def __new__(cls, value: str) -> Category:
        normalized = _normalize_kebab(value)
        if not normalized:
            raise ValueError("Category cannot be empty")
        return str.__new__(cls, normalized)

    @property
    def value(self) -> str:
        return str(self)

    @classmethod
    def normalize(cls, value: str) -> Category:
        return cls(_normalize_kebab(value))


@dataclass(frozen=True, slots=True)
class Evidence:
    ref: str
    summary: str
    date: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "ref", str(self.ref).strip())
        object.__setattr__(self, "summary", str(self.summary).strip())
        object.__setattr__(self, "date", str(self.date).strip())
        if not self.ref:
            raise ValueError("Evidence.ref cannot be empty")
        if not self.summary:
            raise ValueError("Evidence.summary cannot be empty")
        dt.date.fromisoformat(self.date)

    def to_dict(self) -> dict[str, str]:
        return {
            "ref": self.ref,
            "summary": self.summary,
            "date": self.date,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Evidence:
        return cls(
            ref=str(payload["ref"]),
            summary=str(payload["summary"]),
            date=str(payload["date"]),
        )


@dataclass(frozen=True, slots=True)
class PromotionState:
    confidence: float
    evidence_count: int
    promoted: bool
    promoted_confidence: float | None = None

    @property
    def eligible(self) -> bool:
        return self.confidence >= 0.8 and self.evidence_count >= 5 and not self.promoted

    @classmethod
    def from_entry(cls, entry: ValuesEntry) -> PromotionState:
        return cls(
            confidence=entry.confidence,
            evidence_count=entry.total_evidence_count,
            promoted=entry.promoted,
            promoted_confidence=entry.promoted_confidence,
        )


@dataclass(slots=True, kw_only=True)
class ValuesEntry:
    description: str
    category: Category | str
    source_type: SourceType | str
    id: ValuesId | str = field(default_factory=ValuesId.generate)
    confidence: float = 0.3
    evidence: list[Evidence] = field(default_factory=list)
    total_evidence_count: int = 0
    promoted: bool = False
    promoted_at: dt.datetime | str | None = None
    promoted_confidence: float | None = None
    demoted_at: dt.datetime | str | None = None
    demotion_reason: str | None = None
    created_at: dt.datetime | str = field(default_factory=_now)
    updated_at: dt.datetime | str = field(default_factory=_now)

    def __post_init__(self) -> None:
        self.id = self.id if isinstance(self.id, ValuesId) else ValuesId(str(self.id))
        self.description = str(self.description).strip()
        if not self.description:
            raise ValueError("ValuesEntry.description cannot be empty")
        self.category = (
            self.category
            if isinstance(self.category, Category)
            else Category.normalize(self.category)
        )
        self.source_type = SourceType(self.source_type)
        self.confidence = float(self.confidence)
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("ValuesEntry.confidence must be between 0.0 and 1.0")
        evidence_items = [
            item if isinstance(item, Evidence) else Evidence.from_dict(item)
            for item in self.evidence
        ]
        self.total_evidence_count = int(self.total_evidence_count)
        if self.total_evidence_count < 0:
            raise ValueError("ValuesEntry.total_evidence_count cannot be negative")
        self.evidence = evidence_items[:10]
        self.total_evidence_count = max(len(evidence_items), self.total_evidence_count)
        self.promoted = bool(self.promoted)
        self.promoted_at = _coerce_datetime(self.promoted_at)
        self.promoted_confidence = (
            None if self.promoted_confidence is None else float(self.promoted_confidence)
        )
        if self.promoted_confidence is not None and not 0.0 <= self.promoted_confidence <= 1.0:
            raise ValueError("ValuesEntry.promoted_confidence must be between 0.0 and 1.0")
        self.demoted_at = _coerce_datetime(self.demoted_at)
        if self.demotion_reason is not None:
            self.demotion_reason = str(self.demotion_reason).strip() or None
        self.created_at = _coerce_datetime(self.created_at) or _now()
        self.updated_at = _coerce_datetime(self.updated_at) or _now()

    @property
    def promotion_state(self) -> PromotionState:
        return PromotionState.from_entry(self)

    def add_evidence(self, evidence: Evidence | dict[str, Any]) -> None:
        candidate = evidence if isinstance(evidence, Evidence) else Evidence.from_dict(evidence)
        self.evidence = [candidate, *self.evidence][:10]
        self.total_evidence_count += 1
        self.updated_at = _now()

    def to_dict(self) -> dict[str, Any]:
        source_type = cast(SourceType, self.source_type)
        created_at = cast(dt.datetime, self.created_at)
        updated_at = cast(dt.datetime, self.updated_at)
        promoted_at = cast(dt.datetime | None, self.promoted_at)
        demoted_at = cast(dt.datetime | None, self.demoted_at)
        return {
            "id": str(self.id),
            "description": self.description,
            "category": str(self.category),
            "confidence": self.confidence,
            "evidence": [item.to_dict() for item in self.evidence],
            "total_evidence_count": self.total_evidence_count,
            "source_type": source_type.value,
            "promoted": self.promoted,
            "promoted_at": promoted_at.isoformat(timespec="seconds") if promoted_at else None,
            "promoted_confidence": self.promoted_confidence,
            "demoted_at": demoted_at.isoformat(timespec="seconds") if demoted_at else None,
            "demotion_reason": self.demotion_reason,
            "created_at": created_at.isoformat(timespec="seconds"),
            "updated_at": updated_at.isoformat(timespec="seconds"),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ValuesEntry:
        return cls(
            id=payload.get("id", ValuesId.generate()),
            description=str(payload["description"]),
            category=payload["category"],
            confidence=float(payload.get("confidence", 0.3)),
            evidence=[Evidence.from_dict(item) for item in list(payload.get("evidence") or [])],
            total_evidence_count=int(
                payload.get("total_evidence_count", payload.get("evidence_count", 0))
            ),
            source_type=payload["source_type"],
            promoted=bool(payload.get("promoted", False)),
            promoted_at=payload.get("promoted_at"),
            promoted_confidence=payload.get("promoted_confidence"),
            demoted_at=payload.get("demoted_at"),
            demotion_reason=payload.get("demotion_reason"),
            created_at=payload.get("created_at", _now()),
            updated_at=payload.get("updated_at", _now()),
        )


__all__ = [
    "Category",
    "Evidence",
    "PromotionState",
    "SourceType",
    "ValuesEntry",
    "ValuesId",
    "is_substantially_equal",
]
