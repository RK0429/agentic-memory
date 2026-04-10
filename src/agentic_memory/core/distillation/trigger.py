from __future__ import annotations


class DistillationTrigger:
    NOTE_COUNT_THRESHOLD = 10
    TIME_THRESHOLD_HOURS = 168

    def should_distill(
        self,
        notes_since_last: int,
        hours_since_last: float | None,
    ) -> bool:
        if hours_since_last is None:
            return notes_since_last >= 1
        return (
            notes_since_last >= self.NOTE_COUNT_THRESHOLD
            or hours_since_last >= self.TIME_THRESHOLD_HOURS
        )


__all__ = ["DistillationTrigger"]
