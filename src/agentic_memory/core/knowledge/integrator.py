from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from agentic_memory.core.knowledge.model import KnowledgeEntry, is_substantially_equal
from agentic_memory.core.query import parse_query
from agentic_memory.core.scorer import build_idf_cache, score_generic_entry

if TYPE_CHECKING:
    from agentic_memory.core.distillation.extractor import KnowledgeCandidate

_SEARCH_WEIGHTS = {
    "title": 6.0,
    "content": 5.0,
    "domain": 4.0,
    "tags": 2.5,
}
_MERGE_OVERLAP_THRESHOLD = 0.55
_LINK_OVERLAP_THRESHOLD = 0.18
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u3040-\u30ff\u3400-\u9fff]+")
_DIRECTION_NEGATIVE_MARKERS = (
    " do not ",
    " don't ",
    " avoid ",
    " never ",
    " should not ",
    " cannot ",
    " 禁止",
    " 避ける",
    " しない",
    " 不可",
)
_DIRECTION_POSITIVE_MARKERS = (
    " must ",
    " should ",
    " require ",
    " prefer ",
    " always ",
    " 必須",
    " 必要",
    " 推奨",
    " 優先",
)
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
    "use",
    "using",
    "avoid",
    "prefer",
    "must",
    "should",
}


class KnowledgeIntegrationAction(StrEnum):
    CREATE_NEW = "create_new"
    MERGE_EXISTING = "merge_existing"
    LINK_RELATED = "link_related"
    SKIP_DUPLICATE = "skip_duplicate"


@dataclass(frozen=True, slots=True)
class KnowledgeIntegrationResult:
    action: KnowledgeIntegrationAction
    target_id: str | None = None
    merged_content: str | None = None
    conflict_detail: str | None = None


class KnowledgeIntegrator:
    def integrate(
        self,
        candidate: KnowledgeCandidate,
        existing: list[KnowledgeEntry],
    ) -> KnowledgeIntegrationResult:
        for entry in existing:
            if self._is_duplicate(entry, candidate):
                return KnowledgeIntegrationResult(action=KnowledgeIntegrationAction.SKIP_DUPLICATE)

        scored = self._score_existing(candidate, existing)
        if not scored:
            return KnowledgeIntegrationResult(action=KnowledgeIntegrationAction.CREATE_NEW)

        best_score, best_entry = scored[0]
        same_domain = is_substantially_equal(str(best_entry.domain), candidate.domain)
        same_title = is_substantially_equal(best_entry.title, candidate.title)
        overlap_ratio = self._topic_overlap_ratio(best_entry, candidate)

        if same_domain and (same_title or overlap_ratio >= _MERGE_OVERLAP_THRESHOLD):
            merged_content, conflict_detail = self._merge_content(
                best_entry.content,
                candidate.content,
            )
            return KnowledgeIntegrationResult(
                action=KnowledgeIntegrationAction.MERGE_EXISTING,
                target_id=str(best_entry.id),
                merged_content=merged_content,
                conflict_detail=conflict_detail,
            )

        if same_domain and overlap_ratio >= _LINK_OVERLAP_THRESHOLD:
            return KnowledgeIntegrationResult(
                action=KnowledgeIntegrationAction.LINK_RELATED,
                target_id=str(best_entry.id),
            )

        return KnowledgeIntegrationResult(action=KnowledgeIntegrationAction.CREATE_NEW)

    @staticmethod
    def _is_duplicate(entry: KnowledgeEntry, candidate: KnowledgeCandidate) -> bool:
        return (
            is_substantially_equal(entry.title, candidate.title)
            and is_substantially_equal(str(entry.domain), candidate.domain)
            and is_substantially_equal(entry.content, candidate.content)
        )

    def _score_existing(
        self,
        candidate: KnowledgeCandidate,
        existing: list[KnowledgeEntry],
    ) -> list[tuple[float, KnowledgeEntry]]:
        qterms = parse_query(
            " ".join([candidate.title, candidate.content, " ".join(candidate.tags)]).strip()
        )
        if not qterms:
            return []

        documents = [self._document(entry) for entry in existing]
        idf_cache = build_idf_cache(qterms, documents)
        avg_field_lengths = self._average_field_lengths(documents)
        scored: list[tuple[float, KnowledgeEntry]] = []
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
        scored.sort(key=lambda item: (item[0], item[1].updated_at), reverse=True)
        return scored

    @staticmethod
    def _document(entry: KnowledgeEntry) -> dict[str, str]:
        updated_at = entry.updated_at
        updated_date = (
            updated_at.date().isoformat()
            if isinstance(updated_at, dt.datetime)
            else str(updated_at)[:10]
        )
        return {
            "title": entry.title,
            "content": entry.content,
            "domain": str(entry.domain),
            "tags": " ".join(entry.tags),
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

    def _merge_content(
        self,
        existing_content: str,
        candidate_content: str,
    ) -> tuple[str, str | None]:
        if is_substantially_equal(existing_content, candidate_content):
            return existing_content, None

        normalized_existing = self._normalize_text(existing_content)
        normalized_candidate = self._normalize_text(candidate_content)
        if normalized_candidate in normalized_existing:
            return existing_content, None
        if normalized_existing in normalized_candidate:
            return candidate_content, None

        conflict_detail = self._detect_conflict(existing_content, candidate_content)
        return f"{existing_content.rstrip()}\n\n{candidate_content.strip()}", conflict_detail

    def _detect_conflict(self, existing_content: str, candidate_content: str) -> str | None:
        existing_tokens = self._topic_tokens(existing_content)
        candidate_tokens = self._topic_tokens(candidate_content)
        if not existing_tokens or not candidate_tokens:
            return None
        overlap = existing_tokens & candidate_tokens
        if not overlap:
            return None
        existing_direction = self._direction(existing_content)
        candidate_direction = self._direction(candidate_content)
        if existing_direction == 0 or candidate_direction == 0:
            return None
        if existing_direction == candidate_direction:
            return None
        sample = ", ".join(sorted(list(overlap))[:5])
        return f"Conflicting guidance detected around: {sample}"

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
        entry: KnowledgeEntry,
        candidate: KnowledgeCandidate,
    ) -> float:
        candidate_tokens = self._topic_tokens(
            " ".join([candidate.title, candidate.content, " ".join(candidate.tags)])
        )
        entry_tokens = self._topic_tokens(
            " ".join([entry.title, entry.content, " ".join(entry.tags)])
        )
        if not candidate_tokens or not entry_tokens:
            return 0.0
        return len(candidate_tokens & entry_tokens) / max(len(candidate_tokens), 1)

    @classmethod
    def _direction(cls, text: str) -> int:
        normalized = f" {cls._normalize_text(text)} "
        positive = sum(marker in normalized for marker in _DIRECTION_POSITIVE_MARKERS)
        negative = sum(marker in normalized for marker in _DIRECTION_NEGATIVE_MARKERS)
        if positive == negative:
            return 0
        return 1 if positive > negative else -1


__all__ = [
    "KnowledgeIntegrationAction",
    "KnowledgeIntegrationResult",
    "KnowledgeIntegrator",
]
