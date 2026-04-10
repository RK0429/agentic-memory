from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from agentic_memory.core.query import parse_query
from agentic_memory.core.scorer import build_idf_cache, score_generic_entry
from agentic_memory.core.values.model import ValuesEntry, is_substantially_equal

if TYPE_CHECKING:
    from agentic_memory.core.distillation.extractor import ValuesCandidate

_SEARCH_WEIGHTS = {"description": 6.0, "category": 4.0}
_SIMILARITY_SCORE_THRESHOLD = 3.0
_SIMILARITY_OVERLAP_THRESHOLD = 0.3
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u3040-\u30ff\u3400-\u9fff]+")
_STOPWORDS = {
    "the",
    "a",
    "an",
    "to",
    "of",
    "and",
    "or",
    "for",
    "with",
    "prefer",
    "avoid",
    "must",
    "should",
    "do",
    "not",
    "use",
}
_NEGATIVE_MARKERS = (
    " do not ",
    " don't ",
    " avoid ",
    " never ",
    " should not ",
    " cannot ",
    " skip ",
    " remove ",
    " 禁止",
    " 避ける",
    " しない",
    " 不要",
)
_POSITIVE_MARKERS = (
    " prefer ",
    " require ",
    " must ",
    " should ",
    " always ",
    " keep ",
    " add ",
    " use ",
    " 優先",
    " 必須",
    " 必要",
    " 推奨",
    " 追加",
)
_DEFAULT_CONFIDENCE_DELTA = 0.1


class ValuesIntegrationAction(StrEnum):
    CREATE_NEW = "create_new"
    REINFORCE_EXISTING = "reinforce_existing"
    CONTRADICT_EXISTING = "contradict_existing"
    SKIP_DUPLICATE = "skip_duplicate"


@dataclass(frozen=True, slots=True)
class ValuesIntegrationResult:
    action: ValuesIntegrationAction
    target_id: str | None = None
    confidence_delta: float | None = None
    contradiction_detail: str | None = None


class ValuesIntegrator:
    def integrate(
        self,
        candidate: ValuesCandidate,
        existing: list[ValuesEntry],
    ) -> ValuesIntegrationResult:
        for entry in existing:
            if self._is_duplicate(entry, candidate):
                return ValuesIntegrationResult(action=ValuesIntegrationAction.SKIP_DUPLICATE)

        scored = self._score_existing(candidate, existing)
        if not scored:
            return ValuesIntegrationResult(action=ValuesIntegrationAction.CREATE_NEW)

        best_score, best_entry = scored[0]
        same_category = is_substantially_equal(str(best_entry.category), candidate.category)
        overlap_ratio = self._topic_overlap_ratio(best_entry, candidate)
        if not same_category or (
            best_score < _SIMILARITY_SCORE_THRESHOLD
            and overlap_ratio < _SIMILARITY_OVERLAP_THRESHOLD
        ):
            return ValuesIntegrationResult(action=ValuesIntegrationAction.CREATE_NEW)

        delta = abs(candidate.confidence_delta or _DEFAULT_CONFIDENCE_DELTA)
        if self._is_contradiction(best_entry.description, candidate.description):
            return ValuesIntegrationResult(
                action=ValuesIntegrationAction.CONTRADICT_EXISTING,
                target_id=str(best_entry.id),
                confidence_delta=-delta,
                contradiction_detail="Opposing preference detected for the same topic",
            )
        return ValuesIntegrationResult(
            action=ValuesIntegrationAction.REINFORCE_EXISTING,
            target_id=str(best_entry.id),
            confidence_delta=delta,
        )

    @staticmethod
    def _is_duplicate(entry: ValuesEntry, candidate: ValuesCandidate) -> bool:
        return is_substantially_equal(
            entry.description, candidate.description
        ) and is_substantially_equal(str(entry.category), candidate.category)

    def _score_existing(
        self,
        candidate: ValuesCandidate,
        existing: list[ValuesEntry],
    ) -> list[tuple[float, ValuesEntry]]:
        qterms = parse_query(candidate.description)
        if not qterms:
            return []
        documents = [self._document(entry) for entry in existing]
        idf_cache = build_idf_cache(qterms, documents)
        avg_field_lengths = self._average_field_lengths(documents)
        scored: list[tuple[float, ValuesEntry]] = []
        for entry, document in zip(existing, documents, strict=False):
            score, _ = score_generic_entry(
                document,
                qterms,
                _SEARCH_WEIGHTS,
                idf_cache,
                prefer_recent=False,
                half_life_days=30.0,
                recency_boost_max=0.0,
                avg_field_lengths=avg_field_lengths,
            )
            if score > 0:
                scored.append((score, entry))
        scored.sort(
            key=lambda item: (item[0], item[1].confidence, item[1].updated_at),
            reverse=True,
        )
        return scored

    @staticmethod
    def _document(entry: ValuesEntry) -> dict[str, str]:
        updated_at = entry.updated_at
        updated_date = (
            updated_at.date().isoformat()
            if isinstance(updated_at, dt.datetime)
            else str(updated_at)[:10]
        )
        return {
            "description": entry.description,
            "category": str(entry.category),
            "date": updated_date,
        }

    @staticmethod
    def _average_field_lengths(documents: list[dict[str, str]]) -> dict[str, float]:
        if not documents:
            return {}
        sums = {field: 0.0 for field in _SEARCH_WEIGHTS}
        for document in documents:
            for field_name in _SEARCH_WEIGHTS:
                sums[field_name] += len(str(document.get(field_name, "")).split())
        return {field_name: total / len(documents) for field_name, total in sums.items()}

    def _is_contradiction(self, existing_description: str, candidate_description: str) -> bool:
        existing_tokens = self._topic_tokens(existing_description)
        candidate_tokens = self._topic_tokens(candidate_description)
        if not existing_tokens or not candidate_tokens:
            return False
        if not (existing_tokens & candidate_tokens):
            return False
        existing_direction = self._direction(existing_description)
        candidate_direction = self._direction(candidate_description)
        return (
            existing_direction != 0
            and candidate_direction != 0
            and existing_direction != candidate_direction
        )

    @staticmethod
    def _normalize_text(text: str) -> str:
        return " ".join(str(text).strip().split()).lower()

    @classmethod
    def _topic_tokens(cls, text: str) -> set[str]:
        return {
            token.lower()
            for token in _TOKEN_RE.findall(text)
            if token.lower() not in _STOPWORDS and len(token) > 1
        }

    def _topic_overlap_ratio(
        self,
        entry: ValuesEntry,
        candidate: ValuesCandidate,
    ) -> float:
        candidate_tokens = self._topic_tokens(candidate.description)
        entry_tokens = self._topic_tokens(entry.description)
        if not candidate_tokens or not entry_tokens:
            return 0.0
        return len(candidate_tokens & entry_tokens) / max(len(candidate_tokens), 1)

    @classmethod
    def _direction(cls, text: str) -> int:
        normalized = f" {cls._normalize_text(text)} "
        positive = sum(marker in normalized for marker in _POSITIVE_MARKERS)
        negative = sum(marker in normalized for marker in _NEGATIVE_MARKERS)
        if positive == negative:
            return 0
        return 1 if positive > negative else -1


__all__ = [
    "ValuesIntegrationAction",
    "ValuesIntegrationResult",
    "ValuesIntegrator",
]
