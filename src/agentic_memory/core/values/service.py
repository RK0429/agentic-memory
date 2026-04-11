from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, cast

from agentic_memory.core import tokenizer as _tokenizer
from agentic_memory.core.query import parse_query
from agentic_memory.core.scorer import build_idf_cache, score_generic_entry
from agentic_memory.core.security import SecretScanPolicy
from agentic_memory.core.values.agents_md import AgentsMdAdapter
from agentic_memory.core.values.model import (
    Category,
    Evidence,
    SourceType,
    ValuesEntry,
    ValuesId,
    is_substantially_equal,
)
from agentic_memory.core.values.promotion import PromotionManager
from agentic_memory.core.values.repository import ValuesRepository

_SEARCH_WEIGHTS = {"description": 6.0, "category": 4.0}
_SIMILARITY_THRESHOLD = 0.7
_TOPIC_OVERLAP_THRESHOLD = 0.3
_SCORE_HALF_LIFE_DAYS = 30.0
_SCORE_RECENCY_BOOST_MAX = 0.0
_TOPIC_STOPWORDS = frozenset(
    {
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
)


def _now() -> dt.datetime:
    return dt.datetime.now().replace(microsecond=0)


class ValuesService:
    def __init__(self, *, agents_md_adapter: AgentsMdAdapter | None = None) -> None:
        self._agents_md_adapter = agents_md_adapter or AgentsMdAdapter()

    def add(
        self,
        memory_dir: str | Path,
        description: str,
        category: str,
        confidence: float = 0.3,
        evidence: Iterable[Evidence | dict[str, Any]] | None = None,
        source_type: SourceType | str = SourceType.USER_TAUGHT,
    ) -> tuple[ValuesEntry, list[str]]:
        repository = self._repository(memory_dir)
        normalized_description = self._normalize_description(description)
        normalized_category = Category.normalize(category)
        existing_entries = repository.list_all()
        self._ensure_not_duplicate(
            existing_entries,
            description=normalized_description,
            category=normalized_category,
        )

        evidence_items = self._coerce_evidence(evidence)
        entry = ValuesEntry(
            id=ValuesId.generate(),
            description=normalized_description,
            category=normalized_category,
            confidence=confidence,
            evidence=evidence_items[:10],
            total_evidence_count=len(evidence_items),
            source_type=source_type,
        )
        warnings = self._similarity_warnings(
            existing_entries,
            description=entry.description,
            category=normalized_category,
        )
        repository.save(entry)
        warnings.extend(self._secret_warnings(entry.description))
        return entry, warnings

    def search(
        self,
        memory_dir: str | Path,
        query: str | None = None,
        category: str | None = None,
        min_confidence: float = 0.0,
        top: int = 5,
    ) -> list[tuple[float, ValuesEntry]]:
        if top <= 0:
            raise ValueError("top must be greater than 0")

        query_text = (query or "").strip()
        category_filter = Category.normalize(category) if category is not None else None
        if not query_text and category_filter is None:
            raise ValueError("At least one of 'query' or 'category' must be provided.")

        filtered_entries = [
            entry
            for entry in self._repository(memory_dir).list_all()
            if entry.confidence >= min_confidence
            and (category_filter is None or entry.category == category_filter)
        ]
        if not query_text:
            ordered = self._sort_by_confidence(filtered_entries)
            return [(entry.confidence, entry) for entry in ordered[:top]]

        qterms = parse_query(query_text)
        if not qterms:
            return []

        documents = [self._score_document(entry) for entry in filtered_entries]
        idf_cache = build_idf_cache(qterms, documents)
        avg_field_lengths = self._compute_avg_field_lengths(documents)
        scored: list[tuple[float, ValuesEntry]] = []
        for entry, document in zip(filtered_entries, documents, strict=False):
            score, _ = score_generic_entry(
                document,
                qterms,
                _SEARCH_WEIGHTS,
                idf_cache,
                prefer_recent=False,
                half_life_days=_SCORE_HALF_LIFE_DAYS,
                recency_boost_max=_SCORE_RECENCY_BOOST_MAX,
                avg_field_lengths=avg_field_lengths,
            )
            if score > 0:
                scored.append((score, entry))
        scored.sort(
            key=lambda item: (item[0], item[1].confidence, self._updated_at(item[1])),
            reverse=True,
        )
        return scored[:top]

    def update(
        self,
        memory_dir: str | Path,
        id: str,
        confidence: float | None = None,
        add_evidence: Sequence[Evidence | dict[str, Any]] | None = None,
        description: str | None = None,
    ) -> tuple[ValuesEntry, dict[str, bool | list[str]]]:
        if confidence is None and add_evidence is None and description is None:
            raise ValueError("At least one update field is required")

        repository = self._repository(memory_dir)
        entry = repository.find_by_id(id)
        if entry is None:
            raise FileNotFoundError(f"Values entry not found: {id}")

        if description is not None:
            normalized_description = self._normalize_description(description)
            self._ensure_not_duplicate(
                repository.list_all(),
                description=normalized_description,
                category=Category(str(entry.category)),
                exclude_id=ValuesId(str(entry.id)),
            )
            entry.description = normalized_description

        if confidence is not None:
            confidence_value = float(confidence)
            if not 0.0 <= confidence_value <= 1.0:
                raise ValueError("ValuesEntry.confidence must be between 0.0 and 1.0")
            entry.confidence = confidence_value

        if add_evidence is not None:
            if isinstance(add_evidence, dict):
                raise TypeError("`add_evidence` must be a list of evidence objects.")
            evidence_items = list(add_evidence)
            for item in evidence_items:
                entry.add_evidence(item)

        entry.updated_at = _now()
        repository.save(entry)

        notifications: dict[str, bool | list[str]] = {}
        if PromotionManager.check_candidate(entry):
            notifications["promotion_candidate"] = True
        if PromotionManager.check_demotion(entry):
            notifications["demotion_candidate"] = True
        if description is not None:
            notifications["secret_warnings"] = self._secret_warnings(entry.description)
        return entry, notifications

    def delete(
        self,
        memory_dir: str | Path,
        id: str,
        confirm: bool = False,
        reason: str | None = None,
    ) -> dict[str, Any]:
        repository = self._repository(memory_dir)
        entry = repository.find_by_id(id)
        if entry is None:
            raise FileNotFoundError(f"Values entry not found: {id}")

        description = self._delete_description(entry)
        preview: dict[str, Any] = {
            "deleted_id": str(entry.id),
            "description": description,
            "preview": True,
            "would_delete": True,
            "was_promoted": entry.promoted,
        }
        if reason is not None:
            preview["reason"] = reason

        if entry.promoted:
            agents_md_path = self._agents_md_adapter.resolve_agents_md_path(Path(memory_dir))
            if agents_md_path is None:
                raise FileNotFoundError("AGENTS.md not found")

            preview["agents_md_path"] = str(agents_md_path)
            preview["entry_line"] = (
                f"- [{entry.id}] {self._agents_md_adapter.project_description(entry.description)}"
            )

        if not confirm:
            return preview

        if entry.promoted:
            assert agents_md_path is not None
            try:
                self._agents_md_adapter.remove_entry(agents_md_path, str(entry.id))
            except ValueError as exc:
                raise self._delete_agents_md_error(exc) from exc

        repository.delete(entry.id)
        payload: dict[str, Any] = {
            "deleted_id": str(entry.id),
            "description": description,
            "deleted": True,
            "was_promoted": entry.promoted,
        }
        if reason is not None:
            payload["reason"] = reason
        return payload

    def list_values(
        self,
        memory_dir: str | Path,
        min_confidence: float = 0.0,
        category: str | None = None,
        promoted_only: bool = False,
        top: int = 20,
    ) -> list[ValuesEntry]:
        if top <= 0:
            raise ValueError("top must be greater than 0")

        category_filter = Category.normalize(category) if category is not None else None
        filtered_entries = [
            entry
            for entry in self._repository(memory_dir).list_all()
            if entry.confidence >= min_confidence
            and (category_filter is None or entry.category == category_filter)
            and (not promoted_only or entry.promoted)
        ]
        return self._sort_by_confidence(filtered_entries)[:top]

    @staticmethod
    def _repository(memory_dir: str | Path) -> ValuesRepository:
        return ValuesRepository(Path(memory_dir))

    @staticmethod
    def _normalize_description(description: str) -> str:
        normalized = str(description).strip()
        if not normalized:
            raise ValueError("ValuesEntry.description cannot be empty")
        return normalized

    @staticmethod
    def _coerce_evidence(
        evidence: Iterable[Evidence | dict[str, Any]] | None,
    ) -> list[Evidence]:
        if evidence is None:
            return []
        return [
            item if isinstance(item, Evidence) else Evidence.from_dict(item) for item in evidence
        ]

    @staticmethod
    def _is_duplicate(
        entry: ValuesEntry,
        *,
        description: str,
        category: Category,
    ) -> bool:
        return is_substantially_equal(entry.description, description) and is_substantially_equal(
            str(entry.category),
            str(category),
        )

    def _ensure_not_duplicate(
        self,
        entries: list[ValuesEntry],
        *,
        description: str,
        category: Category,
        exclude_id: ValuesId | None = None,
    ) -> None:
        for existing in entries:
            if exclude_id is not None and existing.id == exclude_id:
                continue
            if self._is_duplicate(existing, description=description, category=category):
                raise ValueError(f"Duplicate value exists: {existing.id}")

    def _similarity_warnings(
        self,
        entries: list[ValuesEntry],
        *,
        description: str,
        category: Category,
    ) -> list[str]:
        qterms = parse_query(description)
        if not qterms:
            return []

        new_tokens = self._topic_tokens(description)

        candidates = [
            entry
            for entry in entries
            if not self._is_duplicate(entry, description=description, category=category)
        ]
        documents = [self._score_document(entry) for entry in candidates]
        if not documents:
            return []

        idf_cache = build_idf_cache(qterms, documents)
        avg_field_lengths = self._compute_avg_field_lengths(documents)
        scored: list[tuple[float, ValuesEntry]] = []
        for entry, document in zip(candidates, documents, strict=False):
            score, _ = score_generic_entry(
                document,
                qterms,
                _SEARCH_WEIGHTS,
                idf_cache,
                prefer_recent=False,
                half_life_days=_SCORE_HALF_LIFE_DAYS,
                recency_boost_max=_SCORE_RECENCY_BOOST_MAX,
                avg_field_lengths=avg_field_lengths,
            )
            if score > 0:
                scored.append((score, entry))
        if not scored:
            return []

        max_score = max(score for score, _ in scored)
        if max_score <= 0:
            return []

        warnings: list[str] = []
        for score, entry in sorted(
            scored,
            key=lambda item: (item[0], item[1].confidence, self._updated_at(item[1])),
            reverse=True,
        ):
            normalized_score = score / max_score
            if normalized_score >= _SIMILARITY_THRESHOLD:
                if new_tokens:
                    entry_tokens = self._topic_tokens(entry.description)
                    overlap = len(new_tokens & entry_tokens) / len(new_tokens)
                    if overlap < _TOPIC_OVERLAP_THRESHOLD:
                        continue
                warnings.append(f"Similar value exists: {entry.id} - {entry.description}")
        return warnings

    @staticmethod
    def _topic_tokens(text: str) -> set[str]:
        """Extract meaningful topic tokens for overlap comparison.

        Uses the CJK-aware tokenizer to produce boundary-split tokens,
        then filters stopwords and very short tokens.
        """
        tokens = _tokenizer.tokenize(text, min_length=2)
        return {t.lower() for t in tokens if t.lower() not in _TOPIC_STOPWORDS}

    @staticmethod
    def _score_document(entry: ValuesEntry) -> dict[str, str]:
        return {
            "description": entry.description,
            "category": str(entry.category),
            "date": ValuesService._updated_at(entry).date().isoformat(),
        }

    @staticmethod
    def _compute_avg_field_lengths(documents: list[dict[str, str]]) -> dict[str, float]:
        if not documents:
            return {}

        sums: dict[str, float] = {}
        for document in documents:
            for field_name, value in document.items():
                sums[field_name] = sums.get(field_name, 0.0) + len(str(value).split())
        return {field_name: total / len(documents) for field_name, total in sums.items()}

    @staticmethod
    def _sort_by_confidence(entries: list[ValuesEntry]) -> list[ValuesEntry]:
        return sorted(
            entries,
            key=lambda entry: (entry.confidence, ValuesService._updated_at(entry)),
            reverse=True,
        )

    @staticmethod
    def _updated_at(entry: ValuesEntry) -> dt.datetime:
        return cast(dt.datetime, entry.updated_at)

    @staticmethod
    def _secret_warnings(description: str) -> list[str]:
        matches = SecretScanPolicy.scan(description)
        if not matches:
            return []
        pattern_names = ", ".join(sorted({match.pattern_name for match in matches}))
        return [f"Content may contain secrets (detected: {pattern_names}). Review before sharing."]

    def _existing_agents_entry(self, agents_md_path: Path, entry: ValuesEntry) -> str | None:
        prefix = f"- [{entry.id}] "
        for line in self._agents_md_adapter.list_entries(agents_md_path):
            if line.startswith(prefix):
                return line
        return None

    @staticmethod
    def _entry_line(entry: ValuesEntry) -> str:
        return f"- [{entry.id}] {entry.description}"

    @staticmethod
    def _delete_description(entry: ValuesEntry) -> str:
        desc = entry.description
        if len(desc) <= 80:
            return desc
        return desc[:80] + "\u2026"

    @staticmethod
    def _delete_agents_md_error(exc: ValueError) -> ValueError:
        message = str(exc)
        if message == "AGENTS.md is missing promoted values markers":
            message = f"{message}. Run memory_init to recreate them."
        return ValueError(message)


__all__ = ["ValuesService"]
