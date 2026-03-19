from __future__ import annotations

import re

from agentic_memory.core import tokenizer

LEGACY_TASK_ID_PATTERN = re.compile(r"^(TASK|GOAL)-\d{3,}$")
LEGACY_TASK_ID_EXTRACT_PATTERN = re.compile(r"\b((?:TASK|GOAL)-\d{3,})\b")
RELAY_TASK_UUID_PATTERN = re.compile(
    r"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$"
)
RELAY_TASK_UUID_EXTRACT_PATTERN = re.compile(
    r"\b([0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12})\b"
)


def normalize_task_id(
    value: str | None,
    *,
    allow_embedded: bool = True,
    allow_uuid_embedded: bool = True,
) -> str | None:
    if value is None:
        return None
    normalized = tokenizer.normalize_text(value).strip()
    if not normalized:
        return None

    upper = normalized.upper()
    if LEGACY_TASK_ID_PATTERN.fullmatch(upper):
        return upper
    if RELAY_TASK_UUID_PATTERN.fullmatch(normalized):
        return normalized.lower()
    if not allow_embedded:
        return None

    legacy_match = LEGACY_TASK_ID_EXTRACT_PATTERN.search(upper)
    if legacy_match:
        return legacy_match.group(1)

    if allow_uuid_embedded:
        uuid_match = RELAY_TASK_UUID_EXTRACT_PATTERN.search(normalized)
        if uuid_match:
            return uuid_match.group(1).lower()

    return None


def invalid_task_id_message(value: str | None) -> str:
    return f"Invalid task_id: {value!r}. Expected TASK-123 / GOAL-123 or a relay task UUID."
