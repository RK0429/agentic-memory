"""Fallback retrieval implementations for agentic-memory search."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from agentic_memory.core.query import QueryTerm
from agentic_memory.core.scorer import _strict_term_match


def rg_available() -> bool:
    try:
        subprocess.run(["rg", "--version"], capture_output=True, text=True, check=False)
        return True
    except Exception:
        return False


def fallback_search_files(
    query_terms: list[QueryTerm], dailynote_dir: Path
) -> list[tuple[str, int]]:
    """
    Coarse fallback: run rg with OR of positive terms to get candidate files and hit counts.
    Then filter must/exclude by reading each candidate once.
    """
    if not dailynote_dir.exists():
        return []

    positives = [qt.term for qt in query_terms if qt.term and not qt.exclude]
    if not positives:
        return []

    pats = [re.escape(p) for p in set(positives)]
    rx = "|".join(pats)
    cmd = [
        "rg",
        "-n",
        "--no-heading",
        "--smart-case",
        "--glob",
        "*.md",
        "--glob",
        "!_*",
        rx,
        str(dailynote_dir),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode not in (0, 1):
        return []

    counts: dict[str, int] = {}
    for line in proc.stdout.splitlines():
        m = re.match(r"^(.*?):(\d+):(.*)$", line)
        if not m:
            continue
        path = m.group(1)
        counts[path] = counts.get(path, 0) + 1

    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)

    def ok(path: str) -> bool:
        try:
            text = Path(path).read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return False

        for qt in query_terms:
            if qt.exclude and _strict_term_match(text, qt.term, is_phrase=qt.is_phrase):
                return False

        for qt in query_terms:
            if qt.must and not _strict_term_match(text, qt.term, is_phrase=qt.is_phrase):
                return False

        return True

    return [(p, c) for (p, c) in ranked if ok(p)]


def search_python(query_terms: list[QueryTerm], dailynote_dir: Path) -> list[tuple[str, int]]:
    """Pure Python fallback: scan all markdown files and rank by hit count."""
    if not dailynote_dir.exists():
        return []

    positives = [qt.term.lower() for qt in query_terms if qt.term and not qt.exclude]
    if not positives:
        return []

    rx = re.compile("|".join(re.escape(p) for p in set(positives)), re.IGNORECASE)
    ranked: list[tuple[str, int]] = []

    md_files = [
        p for p in dailynote_dir.rglob("*.md") if p.is_file() and not p.name.startswith("_")
    ]
    for p in md_files:
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        hitcount = len(rx.findall(text))
        if hitcount <= 0:
            continue

        bad = any(
            qt.exclude and _strict_term_match(text, qt.term, is_phrase=qt.is_phrase)
            for qt in query_terms
        )
        if bad:
            continue

        miss = any(
            qt.must and (not _strict_term_match(text, qt.term, is_phrase=qt.is_phrase))
            for qt in query_terms
        )
        if miss:
            continue

        ranked.append((str(p), hitcount))

    ranked.sort(key=lambda x: x[1], reverse=True)
    return ranked


__all__ = ["rg_available", "fallback_search_files", "search_python"]
