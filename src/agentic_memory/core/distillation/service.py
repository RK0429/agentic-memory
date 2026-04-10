from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agentic_memory.core import index, sections, state
from agentic_memory.core.distillation.extractor import (
    DistillationExtractorPort,
    KnowledgeCandidate,
    ValuesCandidate,
)
from agentic_memory.core.knowledge import (
    Accuracy,
    KnowledgeEntry,
    KnowledgeRepository,
    KnowledgeService,
    Source,
    SourceType,
)
from agentic_memory.core.knowledge.integrator import (
    KnowledgeIntegrationAction,
    KnowledgeIntegrator,
)
from agentic_memory.core.security import SecretScanPolicy
from agentic_memory.core.values import Evidence, ValuesEntry, ValuesRepository, ValuesService
from agentic_memory.core.values.integrator import ValuesIntegrationAction, ValuesIntegrator

_NOTE_DATE_DIR_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATE_IN_REF_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
_STATE_PREFIX_DATE_RE = re.compile(r"^\[(\d{4}-\d{2}-\d{2})")


@dataclass(frozen=True, slots=True)
class ReportEntry:
    candidate_summary: str
    action: str
    target_id: str | None = None
    detail: str | None = None


@dataclass(slots=True)
class DistillationReport:
    entries: list[ReportEntry] = field(default_factory=list)
    new_count: int = 0
    merged_count: int = 0
    linked_count: int = 0
    reinforced_count: int = 0
    contradicted_count: int = 0
    skipped_count: int = 0
    secret_skipped_count: int = 0

    def add_entry(
        self,
        *,
        candidate_summary: str,
        action: str,
        target_id: str | None = None,
        detail: str | None = None,
    ) -> None:
        self.entries.append(
            ReportEntry(
                candidate_summary=candidate_summary,
                action=action,
                target_id=target_id,
                detail=detail,
            )
        )
        if action == "create_new":
            self.new_count += 1
        elif action == "merge_existing":
            self.merged_count += 1
        elif action == "link_related":
            self.linked_count += 1
        elif action == "reinforce_existing":
            self.reinforced_count += 1
        elif action == "contradict_existing":
            self.contradicted_count += 1
        elif action == "skip_duplicate":
            self.skipped_count += 1
        elif action == "secret_skipped":
            self.secret_skipped_count += 1


class DistillationService:
    def __init__(
        self,
        *,
        knowledge_service: KnowledgeService | None = None,
        values_service: ValuesService | None = None,
        knowledge_integrator: KnowledgeIntegrator | None = None,
        values_integrator: ValuesIntegrator | None = None,
    ) -> None:
        self.knowledge_service = knowledge_service or KnowledgeService()
        self.values_service = values_service or ValuesService()
        self.knowledge_integrator = knowledge_integrator or KnowledgeIntegrator()
        self.values_integrator = values_integrator or ValuesIntegrator()

    def distill_knowledge(
        self,
        memory_dir: str | Path,
        date_from: str | None,
        date_to: str | None,
        domain: str | None,
        dry_run: bool,
        extractor: DistillationExtractorPort,
    ) -> DistillationReport:
        resolved_memory_dir = Path(memory_dir)
        start_date, end_date = self._validate_date_range(date_from, date_to)
        notes_content = self._collect_knowledge_notes(
            resolved_memory_dir,
            start_date=start_date,
            end_date=end_date,
        )
        candidates = extractor.extract_knowledge(notes_content, domain)
        report = DistillationReport()
        existing_entries = self._list_knowledge(resolved_memory_dir)
        persisted_at = self._now().isoformat(timespec="seconds")
        persisted_any = False

        for candidate in candidates:
            result = self.knowledge_integrator.integrate(candidate, existing_entries)
            candidate_summary = self._knowledge_candidate_summary(candidate)

            if dry_run:
                report.add_entry(
                    candidate_summary=candidate_summary,
                    action=result.action.value,
                    target_id=result.target_id,
                    detail=result.conflict_detail,
                )
                existing_entries = self._simulate_knowledge(existing_entries, candidate, result)
                continue

            if result.action is KnowledgeIntegrationAction.SKIP_DUPLICATE:
                report.add_entry(
                    candidate_summary=candidate_summary,
                    action=result.action.value,
                )
                continue

            if result.action is KnowledgeIntegrationAction.CREATE_NEW:
                if SecretScanPolicy.contains_secret(candidate.content):
                    report.add_entry(
                        candidate_summary=candidate_summary,
                        action="secret_skipped",
                        detail="Candidate content may contain secrets",
                    )
                    continue
                entry = self.knowledge_service.add(
                    resolved_memory_dir,
                    title=candidate.title,
                    content=candidate.content,
                    domain=candidate.domain,
                    tags=candidate.tags,
                    accuracy=Accuracy.UNCERTAIN,
                    sources=[self._knowledge_source(candidate)],
                    source_type=SourceType.MEMORY_DISTILLATION,
                )
                existing_entries.append(entry)
                persisted_any = True
                report.add_entry(
                    candidate_summary=candidate_summary,
                    action=result.action.value,
                    detail=str(entry.id),
                )
                continue

            if result.action is KnowledgeIntegrationAction.MERGE_EXISTING:
                merged_content = result.merged_content or candidate.content
                if SecretScanPolicy.contains_secret(merged_content):
                    report.add_entry(
                        candidate_summary=candidate_summary,
                        action="secret_skipped",
                        target_id=result.target_id,
                        detail="Merged content may contain secrets",
                    )
                    continue
                entry = self.knowledge_service.update(
                    resolved_memory_dir,
                    id=str(result.target_id),
                    content=merged_content,
                    sources=[self._knowledge_source(candidate)],
                    accuracy="uncertain" if result.conflict_detail else None,
                )
                existing_entries = self._replace_knowledge(existing_entries, entry)
                persisted_any = True
                report.add_entry(
                    candidate_summary=candidate_summary,
                    action=result.action.value,
                    target_id=result.target_id,
                    detail=result.conflict_detail,
                )
                continue

            if SecretScanPolicy.contains_secret(candidate.content):
                report.add_entry(
                    candidate_summary=candidate_summary,
                    action="secret_skipped",
                    target_id=result.target_id,
                    detail="Candidate content may contain secrets",
                )
                continue
            entry = self.knowledge_service.add(
                resolved_memory_dir,
                title=candidate.title,
                content=candidate.content,
                domain=candidate.domain,
                tags=candidate.tags,
                accuracy=Accuracy.UNCERTAIN,
                sources=[self._knowledge_source(candidate)],
                source_type=SourceType.MEMORY_DISTILLATION,
                related=[str(result.target_id)] if result.target_id is not None else None,
            )
            existing_entries = self._simulate_knowledge(
                existing_entries,
                candidate,
                result,
                entry=entry,
            )
            persisted_any = True
            report.add_entry(
                candidate_summary=candidate_summary,
                action=result.action.value,
                target_id=result.target_id,
                detail=str(entry.id),
            )

        if not dry_run:
            updates: dict[str, str] = {"last_knowledge_evaluated_at": persisted_at}
            if persisted_any:
                updates["last_knowledge_distilled_at"] = persisted_at
            state.update_distillation_frontmatter(
                resolved_memory_dir / "_state.md",
                **updates,
            )

        return report

    def distill_values(
        self,
        memory_dir: str | Path,
        date_from: str | None,
        date_to: str | None,
        category: str | None,
        dry_run: bool,
        extractor: DistillationExtractorPort,
    ) -> DistillationReport:
        resolved_memory_dir = Path(memory_dir)
        start_date, end_date = self._validate_date_range(date_from, date_to)
        notes_content = self._collect_values_notes(
            resolved_memory_dir,
            start_date=start_date,
            end_date=end_date,
        )
        decisions_content = self._collect_state_decisions(resolved_memory_dir / "_state.md")
        candidates = extractor.extract_values(notes_content, decisions_content, category)
        report = DistillationReport()
        existing_entries = self._list_values(resolved_memory_dir)
        execution_date = self._now().date().isoformat()
        evaluated_at = self._now().isoformat(timespec="seconds")
        persisted_any = False

        for candidate in candidates:
            result = self.values_integrator.integrate(candidate, existing_entries)
            candidate_summary = candidate.description

            if dry_run:
                report.add_entry(
                    candidate_summary=candidate_summary,
                    action=result.action.value,
                    target_id=result.target_id,
                    detail=result.contradiction_detail,
                )
                existing_entries = self._simulate_values(
                    existing_entries,
                    candidate,
                    result,
                    execution_date,
                )
                continue

            if result.action is ValuesIntegrationAction.SKIP_DUPLICATE:
                report.add_entry(
                    candidate_summary=candidate_summary,
                    action=result.action.value,
                )
                continue

            if SecretScanPolicy.contains_secret(candidate.description):
                report.add_entry(
                    candidate_summary=candidate_summary,
                    action="secret_skipped",
                    target_id=result.target_id,
                    detail="Candidate description may contain secrets",
                )
                continue

            evidence = self._values_evidence(
                candidate,
                execution_date=execution_date,
                contradiction_detail=result.contradiction_detail,
            )

            if result.action is ValuesIntegrationAction.CREATE_NEW:
                entry, _warnings = self.values_service.add(
                    resolved_memory_dir,
                    description=candidate.description,
                    category=candidate.category,
                    evidence=[evidence],
                    source_type=SourceType.MEMORY_DISTILLATION,
                )
                existing_entries.append(entry)
                persisted_any = True
                report.add_entry(
                    candidate_summary=candidate_summary,
                    action=result.action.value,
                    detail=str(entry.id),
                )
                continue

            target = self._find_values(existing_entries, str(result.target_id))
            updated_confidence = self._clamp_confidence(
                target.confidence + float(result.confidence_delta or 0.0)
            )
            entry, _notifications = self.values_service.update(
                resolved_memory_dir,
                id=str(result.target_id),
                confidence=updated_confidence,
                add_evidence=evidence,
            )
            existing_entries = self._replace_values(existing_entries, entry)
            if result.action is ValuesIntegrationAction.REINFORCE_EXISTING:
                persisted_any = True
            report.add_entry(
                candidate_summary=candidate_summary,
                action=result.action.value,
                target_id=result.target_id,
                detail=result.contradiction_detail,
            )

        if not dry_run:
            updates = {"last_values_evaluated_at": evaluated_at}
            if persisted_any:
                updates["last_values_distilled_at"] = evaluated_at
            state.update_distillation_frontmatter(
                resolved_memory_dir / "_state.md",
                **updates,
            )

        return report

    def _collect_knowledge_notes(
        self,
        memory_dir: Path,
        *,
        start_date: dt.date | None,
        end_date: dt.date,
    ) -> list[dict[str, Any]]:
        note_paths = self._collect_note_paths(memory_dir, start_date=start_date, end_date=end_date)
        return [self._build_knowledge_snapshot(path, memory_dir) for path in note_paths]

    def _collect_values_notes(
        self,
        memory_dir: Path,
        *,
        start_date: dt.date | None,
        end_date: dt.date,
    ) -> list[dict[str, Any]]:
        note_paths = self._collect_note_paths(memory_dir, start_date=start_date, end_date=end_date)
        return [self._build_values_snapshot(path, memory_dir) for path in note_paths]

    def _collect_note_paths(
        self,
        memory_dir: Path,
        *,
        start_date: dt.date | None,
        end_date: dt.date,
    ) -> list[Path]:
        note_paths: list[Path] = []
        if not memory_dir.exists():
            return note_paths
        for child in sorted(memory_dir.iterdir()):
            if not child.is_dir() or not _NOTE_DATE_DIR_RE.fullmatch(child.name):
                continue
            dir_date = dt.date.fromisoformat(child.name)
            if start_date is not None and dir_date < start_date:
                continue
            if dir_date > end_date:
                continue
            note_paths.extend(sorted(path for path in child.glob("*.md") if path.is_file()))
        return note_paths

    def _build_knowledge_snapshot(self, note_path: Path, memory_dir: Path) -> dict[str, Any]:
        markdown = index.read_text(note_path)
        parsed_sections = index.parse_sections(markdown)
        section_map = {
            "decisions": self._section_items(parsed_sections, "判断"),
            "pitfalls": self._section_items(parsed_sections, "注意点・残課題"),
            "outcome": self._section_items(parsed_sections, "成果"),
            "work_log": self._section_items(parsed_sections, "作業ログ"),
        }
        return self._note_snapshot(note_path, memory_dir, markdown, section_map)

    def _build_values_snapshot(self, note_path: Path, memory_dir: Path) -> dict[str, Any]:
        markdown = index.read_text(note_path)
        parsed_sections = index.parse_sections(markdown)
        section_map = {
            "decisions": self._section_items(parsed_sections, "判断"),
        }
        return self._note_snapshot(note_path, memory_dir, markdown, section_map)

    def _note_snapshot(
        self,
        note_path: Path,
        memory_dir: Path,
        markdown: str,
        section_map: dict[str, list[str]],
    ) -> dict[str, Any]:
        ref = self._note_ref(note_path, memory_dir)
        combined: list[str] = []
        for section_name, items in section_map.items():
            if not items:
                continue
            combined.append(f"## {section_name}\n" + "\n".join(f"- {item}" for item in items))
        return {
            "ref": ref,
            "title": index.first_h1(markdown),
            "date": note_path.parent.name,
            "source_summary": f"{index.first_h1(markdown)} ({note_path.parent.name})",
            "sections": section_map,
            "content": "\n\n".join(combined),
        }

    @staticmethod
    def _section_items(parsed_sections: dict[str, list[str]], section_name: str) -> list[str]:
        lines = sections.get_section(parsed_sections, section_name)
        items = state.bullets(lines)
        if items:
            return items
        return [
            line.strip() for line in lines if line.strip() and not line.strip().startswith("```")
        ]

    @staticmethod
    def _note_ref(note_path: Path, memory_dir: Path) -> str:
        try:
            return str(note_path.relative_to(memory_dir.parent))
        except ValueError:
            return str(note_path)

    @staticmethod
    def _collect_state_decisions(state_path: Path) -> str | None:
        sections_data = state.load_state(state_path)
        decisions = sections_data.get(state.STATE_SHORT_KEYS["decisions"], [])
        if not decisions:
            return None
        return "\n".join(item.render() for item in decisions)

    @staticmethod
    def _knowledge_source(candidate: KnowledgeCandidate) -> Source:
        return Source(
            type=SourceType.MEMORY_DISTILLATION,
            ref=candidate.source_ref,
            summary=candidate.source_summary,
        )

    @staticmethod
    def _knowledge_candidate_summary(candidate: KnowledgeCandidate) -> str:
        return f"{candidate.title} [{candidate.domain}]"

    @staticmethod
    def _values_evidence(
        candidate: ValuesCandidate,
        *,
        execution_date: str,
        contradiction_detail: str | None,
    ) -> Evidence:
        summary = candidate.source_summary
        if contradiction_detail:
            summary = f"{summary} (contradiction: {contradiction_detail})"
        return Evidence(
            ref=candidate.source_ref,
            summary=summary,
            date=DistillationService._derive_values_evidence_date(
                candidate,
                execution_date=execution_date,
            ),
        )

    @staticmethod
    def _derive_values_evidence_date(
        candidate: ValuesCandidate,
        *,
        execution_date: str,
    ) -> str:
        if "_state.md" in candidate.source_ref:
            match = _STATE_PREFIX_DATE_RE.match(candidate.source_summary.strip())
            if match:
                return match.group(1)
            return execution_date

        match = _DATE_IN_REF_RE.search(candidate.source_ref)
        if match:
            return match.group(1)
        return execution_date

    @staticmethod
    def _validate_date_range(
        date_from: str | None,
        date_to: str | None,
    ) -> tuple[dt.date | None, dt.date]:
        start_date = dt.date.fromisoformat(date_from) if date_from is not None else None
        end_date = dt.date.fromisoformat(date_to) if date_to is not None else dt.date.today()
        if start_date is not None and start_date > end_date:
            raise ValueError("date_from must be on or before date_to")
        return start_date, end_date

    @staticmethod
    def _replace_knowledge(
        entries: list[KnowledgeEntry],
        updated: KnowledgeEntry,
    ) -> list[KnowledgeEntry]:
        return [updated if str(entry.id) == str(updated.id) else entry for entry in entries]

    @staticmethod
    def _replace_values(entries: list[ValuesEntry], updated: ValuesEntry) -> list[ValuesEntry]:
        return [updated if str(entry.id) == str(updated.id) else entry for entry in entries]

    @staticmethod
    def _find_values(entries: list[ValuesEntry], target_id: str) -> ValuesEntry:
        for entry in entries:
            if str(entry.id) == target_id:
                return entry
        raise FileNotFoundError(f"Values entry not found: {target_id}")

    def _simulate_knowledge(
        self,
        entries: list[KnowledgeEntry],
        candidate: KnowledgeCandidate,
        result: Any,
        *,
        entry: KnowledgeEntry | None = None,
    ) -> list[KnowledgeEntry]:
        if result.action is KnowledgeIntegrationAction.CREATE_NEW:
            simulated = entry or KnowledgeEntry(
                title=candidate.title,
                content=candidate.content,
                domain=candidate.domain,
                tags=candidate.tags,
                accuracy=Accuracy.UNCERTAIN,
                sources=[self._knowledge_source(candidate)],
                source_type=SourceType.MEMORY_DISTILLATION,
            )
            return [*entries, simulated]

        if (
            result.action is KnowledgeIntegrationAction.MERGE_EXISTING
            and result.target_id is not None
        ):
            updated_entries: list[KnowledgeEntry] = []
            for current in entries:
                if str(current.id) != str(result.target_id):
                    updated_entries.append(current)
                    continue
                payload = current.to_dict()
                payload["content"] = result.merged_content or current.content
                payload["sources"] = [
                    *payload["sources"],
                    self._knowledge_source(candidate).to_dict(),
                ]
                if result.conflict_detail:
                    payload["accuracy"] = Accuracy.UNCERTAIN.value
                updated_entries.append(KnowledgeEntry.from_dict(payload))
            return updated_entries

        if result.action is KnowledgeIntegrationAction.LINK_RELATED:
            simulated = entry or KnowledgeEntry(
                title=candidate.title,
                content=candidate.content,
                domain=candidate.domain,
                tags=candidate.tags,
                accuracy=Accuracy.UNCERTAIN,
                sources=[self._knowledge_source(candidate)],
                source_type=SourceType.MEMORY_DISTILLATION,
                related=[str(result.target_id)] if result.target_id is not None else [],
            )
            updated_entries = [*entries, simulated]
            if result.target_id is None:
                return updated_entries
            return [
                self._add_related(entry_item, str(simulated.id))
                if str(entry_item.id) == str(result.target_id)
                else entry_item
                for entry_item in updated_entries
            ]

        return entries

    def _simulate_values(
        self,
        entries: list[ValuesEntry],
        candidate: ValuesCandidate,
        result: Any,
        execution_date: str,
    ) -> list[ValuesEntry]:
        if result.action is ValuesIntegrationAction.CREATE_NEW:
            simulated = ValuesEntry(
                description=candidate.description,
                category=candidate.category,
                confidence=0.3,
                evidence=[
                    self._values_evidence(
                        candidate,
                        execution_date=execution_date,
                        contradiction_detail=None,
                    )
                ],
                total_evidence_count=1,
                source_type=SourceType.MEMORY_DISTILLATION,
            )
            return [*entries, simulated]

        if result.target_id is None:
            return entries

        updated_entries: list[ValuesEntry] = []
        for current in entries:
            if str(current.id) != str(result.target_id):
                updated_entries.append(current)
                continue
            payload = current.to_dict()
            payload["confidence"] = self._clamp_confidence(
                current.confidence + float(result.confidence_delta or 0.0)
            )
            evidence = self._values_evidence(
                candidate,
                execution_date=execution_date,
                contradiction_detail=result.contradiction_detail,
            )
            payload["evidence"] = [evidence.to_dict(), *payload["evidence"]][:10]
            payload["total_evidence_count"] = int(payload["total_evidence_count"]) + 1
            updated_entries.append(ValuesEntry.from_dict(payload))
        return updated_entries

    @staticmethod
    def _add_related(entry: KnowledgeEntry, related_id: str) -> KnowledgeEntry:
        related = [str(item) for item in entry.related]
        if related_id not in related:
            related.append(related_id)
        payload = entry.to_dict()
        payload["related"] = related
        return KnowledgeEntry.from_dict(payload)

    @staticmethod
    def _list_knowledge(memory_dir: Path) -> list[KnowledgeEntry]:
        return KnowledgeRepository(memory_dir).list_all()

    @staticmethod
    def _list_values(memory_dir: Path) -> list[ValuesEntry]:
        return ValuesRepository(memory_dir).list_all()

    @staticmethod
    def _clamp_confidence(value: float) -> float:
        return max(0.0, min(1.0, float(value)))

    @staticmethod
    def _now() -> dt.datetime:
        return dt.datetime.now().replace(microsecond=0)


__all__ = ["DistillationReport", "DistillationService", "ReportEntry"]
