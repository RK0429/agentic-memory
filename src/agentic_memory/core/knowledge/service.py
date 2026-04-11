from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

from agentic_memory.core.knowledge.model import (
    Accuracy,
    Domain,
    KnowledgeEntry,
    KnowledgeId,
    Source,
    SourceType,
    UserUnderstanding,
    is_substantially_equal,
)
from agentic_memory.core.knowledge.repository import KnowledgeRepository
from agentic_memory.core.query import expand_terms, parse_query
from agentic_memory.core.scorer import build_idf_cache, score_generic_entry
from agentic_memory.core.security import SecretScanPolicy

_SEARCH_WEIGHTS = {
    "title": 6.0,
    "content": 5.0,
    "domain": 4.0,
    "tags": 3.0,
}


class DuplicateKnowledgeError(ValueError):
    """Raised when a knowledge entry would duplicate an existing entry."""


class KnowledgeService:
    def __init__(self) -> None:
        self.last_warnings: list[str] = []

    def add(
        self,
        memory_dir: str | Path,
        title: str,
        content: str,
        domain: str,
        tags: list[str] | None = None,
        accuracy: Accuracy | str = Accuracy.UNCERTAIN,
        sources: list[Source | dict[str, Any]] | None = None,
        source_type: SourceType | str = SourceType.MEMORY_DISTILLATION,
        user_understanding: UserUnderstanding | str = UserUnderstanding.UNKNOWN,
        related: list[str] | None = None,
    ) -> KnowledgeEntry:
        repository = self._repository(memory_dir)
        related_ids = self._normalize_related(related)
        related_entries = self._load_related_entries(repository, related_ids)
        entry = KnowledgeEntry(
            title=title,
            content=content,
            domain=domain,
            tags=tags or [],
            accuracy=accuracy,
            sources=self._coerce_sources(sources),
            source_type=source_type,
            user_understanding=user_understanding,
            related=[str(related_id) for related_id in related_ids],
        )
        self._ensure_no_duplicate(repository.list_all(), candidate=entry)
        repository.save(entry)
        self._ensure_bidirectional_links(repository, entry.id, related_entries)
        self.last_warnings = self._secret_warnings(entry.content)
        return entry

    def search(
        self,
        memory_dir: str | Path,
        query: str | None = None,
        domain: str | None = None,
        accuracy: Accuracy | str | None = None,
        user_understanding: UserUnderstanding | str | None = None,
        top: int = 10,
        no_cjk_expand: bool = False,
    ) -> list[tuple[float, KnowledgeEntry]]:
        normalized_query = (query or "").strip()
        normalized_domain = self._normalize_domain(domain)
        if not normalized_query and normalized_domain is None:
            raise ValueError("At least one of 'query' or 'domain' must be provided.")
        if top < 1:
            raise ValueError("top must be >= 1")

        repository = self._repository(memory_dir)
        entries = repository.list_all()
        if normalized_domain is not None:
            entries = [entry for entry in entries if str(entry.domain) == normalized_domain]

        accuracy_filter = Accuracy(accuracy) if accuracy is not None else None
        understanding_filter = (
            UserUnderstanding(user_understanding) if user_understanding is not None else None
        )

        if not normalized_query:
            ordered = sorted(entries, key=lambda entry: entry.updated_at, reverse=True)
            filtered_entries = [
                entry
                for entry in ordered
                if self._matches_filters(
                    entry,
                    accuracy=accuracy_filter,
                    user_understanding=understanding_filter,
                )
            ]
            return [(0.0, entry) for entry in filtered_entries[:top]]

        qterms = parse_query(normalized_query)
        qterms = expand_terms(qterms, config={}, enable=True, no_cjk_expand=no_cjk_expand)
        docs = [self._field_texts(entry) for entry in entries]
        idf_cache = build_idf_cache(qterms, docs)
        avg_field_lengths = self._average_field_lengths(docs)
        scored: list[tuple[float, KnowledgeEntry]] = []
        for entry, doc in zip(entries, docs, strict=False):
            score, _ = score_generic_entry(
                doc,
                qterms,
                _SEARCH_WEIGHTS,
                idf_cache,
                prefer_recent=False,
                half_life_days=30.0,
                recency_boost_max=0.0,
                avg_field_lengths=avg_field_lengths,
            )
            if score <= 0:
                continue
            scored.append((score, entry))

        scored.sort(key=lambda item: (item[0], item[1].updated_at), reverse=True)
        filtered_results = [
            (score, entry)
            for score, entry in scored
            if self._matches_filters(
                entry,
                accuracy=accuracy_filter,
                user_understanding=understanding_filter,
            )
        ]
        return filtered_results[:top]

    def update(
        self,
        memory_dir: str | Path,
        id: str,
        content: str | None = None,
        accuracy: Accuracy | str | None = None,
        sources: list[Source | dict[str, Any]] | None = None,
        user_understanding: UserUnderstanding | str | None = None,
        related: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> KnowledgeEntry:
        if all(
            value is None
            for value in (content, accuracy, sources, user_understanding, related, tags)
        ):
            raise ValueError(
                "At least one update field is required "
                "(content, accuracy, sources, user_understanding, related, tags)"
            )

        repository = self._repository(memory_dir)
        existing = repository.find_by_id(id)
        if existing is None:
            raise FileNotFoundError(f"Knowledge entry not found: {id}")
        related_ids = self._normalize_related(related)
        related_entries = self._load_related_entries(
            repository,
            related_ids,
            current_id=KnowledgeId(str(existing.id)),
        )

        payload = existing.to_dict()
        if content is not None:
            payload["content"] = content
        if accuracy is not None:
            payload["accuracy"] = Accuracy(accuracy).value
        if sources is not None:
            payload["sources"] = self._merge_sources(payload["sources"], sources)
        if user_understanding is not None:
            payload["user_understanding"] = UserUnderstanding(user_understanding).value
        if related is not None:
            payload["related"] = self._merge_related(
                payload["related"],
                related_ids,
                current_id=KnowledgeId(str(existing.id)),
            )
        if tags is not None:
            payload["tags"] = tags
        payload["updated_at"] = self._now().isoformat(timespec="seconds")

        updated = KnowledgeEntry.from_dict(payload)
        if content is not None:
            self._ensure_no_duplicate(
                repository.list_all(),
                candidate=updated,
                exclude_id=KnowledgeId(str(updated.id)),
            )
        repository.save(updated)
        if related is not None:
            self._ensure_bidirectional_links(repository, updated.id, related_entries)
        self.last_warnings = self._secret_warnings(updated.content) if content is not None else []
        return updated

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
            raise FileNotFoundError(f"Knowledge entry not found: {id}")

        deleted_id = str(entry.id)
        preview: dict[str, Any] = {
            "deleted_id": deleted_id,
            "title": entry.title,
            "preview": True,
            "would_delete": True,
        }
        if reason is not None:
            preview["reason"] = reason
        if not confirm:
            return preview

        repository.delete(entry.id)
        for candidate in repository.list_all():
            candidate_related = [str(related_id) for related_id in candidate.related]
            if deleted_id not in candidate_related:
                continue
            payload = candidate.to_dict()
            payload["related"] = [
                related_id for related_id in candidate_related if related_id != deleted_id
            ]
            payload["updated_at"] = self._now().isoformat(timespec="seconds")
            repository.save(KnowledgeEntry.from_dict(payload))
        response: dict[str, Any] = {
            "deleted_id": deleted_id,
            "title": entry.title,
            "deleted": True,
        }
        if reason is not None:
            response["reason"] = reason
        return response

    def _repository(self, memory_dir: str | Path) -> KnowledgeRepository:
        return KnowledgeRepository(Path(memory_dir))

    @staticmethod
    def _now() -> dt.datetime:
        return dt.datetime.now().replace(microsecond=0)

    @staticmethod
    def _normalize_domain(domain: str | None) -> str | None:
        if domain is None:
            return None
        return str(Domain.normalize(domain))

    @staticmethod
    def _coerce_sources(
        sources: list[Source | dict[str, Any]] | None,
    ) -> list[Source]:
        if sources is None:
            return []
        coerced: list[Source] = []
        for source in sources:
            candidate = source if isinstance(source, Source) else Source.from_dict(source)
            if candidate not in coerced:
                coerced.append(candidate)
        return coerced

    @staticmethod
    def _normalize_related(related: list[str] | None) -> list[KnowledgeId]:
        if related is None:
            return []
        normalized: list[KnowledgeId] = []
        seen: set[KnowledgeId] = set()
        for raw in related:
            candidate = KnowledgeId(str(raw))
            if candidate in seen:
                continue
            seen.add(candidate)
            normalized.append(candidate)
        return normalized

    @staticmethod
    def _merge_sources(
        existing_sources: list[dict[str, Any]],
        new_sources: list[Source | dict[str, Any]],
    ) -> list[dict[str, Any]]:
        merged: list[Source] = []
        for existing_source in existing_sources:
            candidate = (
                existing_source
                if isinstance(existing_source, Source)
                else Source.from_dict(existing_source)
            )
            if candidate not in merged:
                merged.append(candidate)
        for new_source in new_sources:
            candidate = (
                new_source if isinstance(new_source, Source) else Source.from_dict(new_source)
            )
            if candidate not in merged:
                merged.append(candidate)
        return [source.to_dict() for source in merged]

    @staticmethod
    def _merge_related(
        existing_related: list[str],
        new_related: list[KnowledgeId],
        *,
        current_id: KnowledgeId,
    ) -> list[str]:
        merged: list[str] = []
        seen: set[KnowledgeId] = set()
        for raw in [*existing_related, *[str(related_id) for related_id in new_related]]:
            candidate = KnowledgeId(str(raw))
            if candidate == current_id or candidate in seen:
                continue
            seen.add(candidate)
            merged.append(str(candidate))
        return merged

    @staticmethod
    def _is_duplicate(existing: KnowledgeEntry, candidate: KnowledgeEntry) -> bool:
        return (
            is_substantially_equal(existing.title, candidate.title)
            and is_substantially_equal(str(existing.domain), str(candidate.domain))
            and is_substantially_equal(existing.content, candidate.content)
        )

    def _ensure_no_duplicate(
        self,
        entries: list[KnowledgeEntry],
        *,
        candidate: KnowledgeEntry,
        exclude_id: KnowledgeId | None = None,
    ) -> None:
        for existing in entries:
            existing_id = KnowledgeId(str(existing.id))
            if exclude_id is not None and existing_id == exclude_id:
                continue
            if self._is_duplicate(existing, candidate):
                raise DuplicateKnowledgeError(
                    f"Duplicate knowledge entry already exists: {existing.id}"
                )

    @staticmethod
    def _load_related_entries(
        repository: KnowledgeRepository,
        related_ids: list[KnowledgeId],
        *,
        current_id: KnowledgeId | None = None,
    ) -> list[KnowledgeEntry]:
        related_entries: list[KnowledgeEntry] = []
        for related_id in related_ids:
            if current_id is not None and related_id == current_id:
                continue
            entry = repository.find_by_id(related_id)
            if entry is None:
                raise FileNotFoundError(f"Knowledge entry not found: {related_id}")
            related_entries.append(entry)
        return related_entries

    @staticmethod
    def _ensure_bidirectional_links(
        repository: KnowledgeRepository,
        current_id: KnowledgeId | str,
        related_entries: list[KnowledgeEntry],
    ) -> None:
        current = KnowledgeId(str(current_id))
        for related_entry in related_entries:
            current_related = [str(related_id) for related_id in related_entry.related]
            if str(current) in current_related:
                continue
            payload = related_entry.to_dict()
            payload["related"] = [*current_related, str(current)]
            payload["updated_at"] = KnowledgeService._now().isoformat(timespec="seconds")
            repository.save(KnowledgeEntry.from_dict(payload))

    @staticmethod
    def _field_texts(entry: KnowledgeEntry) -> dict[str, str]:
        return {
            "title": entry.title,
            "content": entry.content,
            "domain": str(entry.domain),
            "tags": " ".join(entry.tags),
        }

    @staticmethod
    def _average_field_lengths(docs: list[dict[str, str]]) -> dict[str, float]:
        if not docs:
            return {}
        sums = {field: 0.0 for field in _SEARCH_WEIGHTS}
        for doc in docs:
            for field in _SEARCH_WEIGHTS:
                sums[field] += len(str(doc.get(field, "")).split())
        return {field: total / len(docs) for field, total in sums.items()}

    @staticmethod
    def _matches_filters(
        entry: KnowledgeEntry,
        *,
        accuracy: Accuracy | None,
        user_understanding: UserUnderstanding | None,
    ) -> bool:
        if accuracy is not None and entry.accuracy != accuracy:
            return False
        return user_understanding is None or entry.user_understanding == user_understanding

    @staticmethod
    def _secret_warnings(content: str) -> list[str]:
        matches = SecretScanPolicy.scan(content)
        if not matches:
            return []
        pattern_names = ", ".join(sorted({match.pattern_name for match in matches}))
        return [f"Content may contain secrets (detected: {pattern_names}). Review before sharing."]


__all__ = ["DuplicateKnowledgeError", "KnowledgeService"]
