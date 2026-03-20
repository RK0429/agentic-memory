"""Shared helpers for index timestamp parsing and stale-entry tolerance."""

from __future__ import annotations

import datetime as dt

INDEXED_AT_TOLERANCE_SECONDS = 1.0


def parse_indexed_at(value: object) -> dt.datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return dt.datetime.fromisoformat(value)
    except ValueError:
        return None
