from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

from agentic_memory.core.security import SecretScanPolicy
from agentic_memory.core.values.agents_md import AgentsMdAdapter
from agentic_memory.core.values.model import ValuesEntry
from agentic_memory.core.values.repository import ValuesRepository


def _now() -> dt.datetime:
    return dt.datetime.now().replace(microsecond=0)


class PromotionManager:
    CONFIDENCE_THRESHOLD = 0.8
    EVIDENCE_THRESHOLD = 5

    @staticmethod
    def check_candidate(entry: ValuesEntry) -> bool:
        return (
            entry.confidence >= PromotionManager.CONFIDENCE_THRESHOLD
            and entry.total_evidence_count >= PromotionManager.EVIDENCE_THRESHOLD
            and not entry.promoted
        )

    @staticmethod
    def check_demotion(entry: ValuesEntry) -> bool:
        if not entry.promoted or entry.promoted_confidence is None:
            return False
        return (entry.promoted_confidence - entry.confidence) >= 0.2


class PromotionService:
    def __init__(
        self,
        *,
        promotion_manager: PromotionManager | None = None,
        agents_md_adapter: AgentsMdAdapter | None = None,
    ) -> None:
        self._promotion_manager = promotion_manager or PromotionManager()
        self._agents_md_adapter = agents_md_adapter or AgentsMdAdapter()

    def promote(
        self,
        memory_dir: str | Path,
        id: str,
        confirm: bool = False,
    ) -> dict[str, Any]:
        repository = ValuesRepository(Path(memory_dir))
        entry = repository.find_by_id(id)
        if entry is None:
            raise FileNotFoundError(f"Values entry not found: {id}")
        if entry.promoted:
            raise ValueError(f"Values entry already promoted: {id}")
        if SecretScanPolicy.contains_secret(entry.description):
            raise ValueError("Cannot promote value containing potential secrets")
        if not self._promotion_manager.check_candidate(entry):
            raise ValueError(
                "Values entry does not meet promotion criteria: "
                f"{id} (confidence={entry.confidence}, "
                f"required>={PromotionManager.CONFIDENCE_THRESHOLD}; "
                f"evidence_count={entry.total_evidence_count}, "
                f"required>={PromotionManager.EVIDENCE_THRESHOLD}; "
                f"promoted={entry.promoted}). "
                f"Increase confidence to >= {PromotionManager.CONFIDENCE_THRESHOLD} "
                f"and accumulate >= {PromotionManager.EVIDENCE_THRESHOLD} evidence items "
                "via memory_values_update."
            )

        agents_md_path = self._agents_md_adapter.resolve_agents_md_path(Path(memory_dir))
        if agents_md_path is None:
            raise FileNotFoundError("AGENTS.md not found")

        preview = {
            "id": str(entry.id),
            "preview": True,
            "would_promote": True,
            "agents_md_path": str(agents_md_path),
            "entry_line": self._agents_md_adapter.format_entry_line(
                description=entry.description,
                entry_id=str(entry.id),
            ),
        }
        if not confirm:
            return preview

        self._agents_md_adapter.append_entry(
            agents_md_path,
            description=entry.description,
            entry_id=str(entry.id),
            lock_dir=Path(memory_dir),
        )
        timestamp = _now()
        entry.promoted = True
        entry.promoted_at = timestamp
        entry.promoted_confidence = entry.confidence
        entry.demoted_at = None
        entry.demotion_reason = None
        entry.updated_at = timestamp
        repository.save(entry)
        return {
            "id": str(entry.id),
            "promoted": True,
            "agents_md_path": str(agents_md_path),
        }

    def demote(
        self,
        memory_dir: str | Path,
        id: str,
        reason: str,
        confirm: bool = False,
    ) -> dict[str, Any]:
        repository = ValuesRepository(Path(memory_dir))
        entry = repository.find_by_id(id)
        if entry is None:
            raise FileNotFoundError(f"Values entry not found: {id}")
        if not entry.promoted:
            raise ValueError(f"Values entry is not promoted: {id}")

        normalized_reason = str(reason).strip()
        if not normalized_reason:
            raise ValueError("Demotion reason cannot be empty")

        agents_md_path = self._agents_md_adapter.resolve_agents_md_path(Path(memory_dir))
        if agents_md_path is None:
            raise FileNotFoundError("AGENTS.md not found")

        preview = {
            "id": str(entry.id),
            "preview": True,
            "would_demote": True,
            "demotion_reason": normalized_reason,
            "agents_md_path": str(agents_md_path),
            "entry_line": self._existing_entry_line(agents_md_path, entry)
            or self._agents_md_adapter.format_entry_line(
                description=entry.description,
                entry_id=str(entry.id),
            ),
        }
        if not confirm:
            return preview

        self._agents_md_adapter.remove_entry(
            agents_md_path,
            str(entry.id),
            lock_dir=Path(memory_dir),
        )
        timestamp = _now()
        entry.promoted = False
        entry.demotion_reason = normalized_reason
        entry.demoted_at = timestamp
        entry.updated_at = timestamp
        repository.save(entry)
        return {
            "id": str(entry.id),
            "promoted": False,
            "demotion_reason": normalized_reason,
            "agents_md_path": str(agents_md_path),
        }

    def _existing_entry_line(self, agents_md_path: Path, entry: ValuesEntry) -> str | None:
        prefix = f"- [{entry.id}] "
        for line in self._agents_md_adapter.list_entries(agents_md_path):
            if line.startswith(prefix):
                return line
        return None


__all__ = ["PromotionManager", "PromotionService"]
