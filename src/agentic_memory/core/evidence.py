"""
evidence.py — Extract a compact evidence pack from memory markdown files.

- Input: query + list of note paths
- Output: Markdown pack with key sections:
  Goal/Outcome/Decisions/Next/Pitfalls/Commands/Verification/Changes
- Only standard library.

This script is designed as a helper for agentic RAG:
it reduces reading cost while preserving provenance.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path

from agentic_memory.core import sections
from agentic_memory.core.query import parse_query

SECTION_ORDER = [
    "目標",
    "成果",
    "判断",
    "次のアクション",
    "注意点・残課題",
    "コマンド",
    "検証",
    "変更点",
    "作業ログ",
]


def _detect_note_language(parsed_sections: dict[str, list[str]]) -> str:
    """Detect note language from section headings."""
    for sec_name in parsed_sections:
        if sec_name in sections.NOTE_SECTION_ALIASES:
            return "ja"
    return "en"


def parse_sections(md: str) -> dict[str, list[str]]:
    """
    Very small markdown section parser for level-2 headings (## ...).
    Returns map: section title -> list of lines.
    """
    sections: dict[str, list[str]] = {}
    cur = None
    for line in md.splitlines():
        m = re.match(r"^##\s+(.*)\s*$", line)
        if m:
            cur = m.group(1).strip()
            sections.setdefault(cur, [])
            continue
        if cur is not None:
            sections[cur].append(line.rstrip())
    return sections


def extract_header(md: str) -> dict[str, str]:
    title = ""
    meta = {}
    for line in md.splitlines():
        if line.startswith("# ") and not title:
            title = line[2:].strip()
        m = re.match(r"^- (\w+):[ \t]*(.*)$", line)
        if m:
            meta[m.group(1)] = m.group(2).strip()
        # stop early after first big section
        if line.startswith("## "):
            break
    meta["title"] = title
    return meta


def build_regex_from_query(query: str) -> re.Pattern:
    terms = [qt.term for qt in parse_query(query) if qt.term and not qt.exclude]
    pats = [re.escape(t) for t in terms]
    if not pats:
        return re.compile(r"$^")
    return re.compile("|".join(pats), re.IGNORECASE)


# Template placeholder patterns that carry no meaningful content.
_TEMPLATE_PLACEHOLDER_RE = re.compile(
    r"^-?\s*(?:"
    r"##\s*(?:Files|Notes|Tests|Result|Outcome|Goal|Plan):?\s*$"
    r"|Query\s+used:\s*$"
    r"|Useful\s+notes:\s*$"
    r"|Missed\s+notes\s*/\s*gaps:\s*$"
    r"|Retrieval\s+improvements:\s*$"
    r"|$"
    r")"
)


def _is_empty_content(s: str) -> bool:
    """Return True if *s* is a bare bullet or template placeholder."""
    return s in ("-", "*") or bool(_TEMPLATE_PLACEHOLDER_RE.match(s))


def filter_lines(lines: list[str], rx: re.Pattern, max_lines: int) -> list[str]:
    """
    Keep lines matching rx, plus a few leading bullets if nothing matches.
    Skips template placeholder lines (bare bullets, ``## Files:``, etc.).
    """
    kept = []
    for ln in lines:
        if rx.search(ln):
            s = ln.strip()
            if s and not _is_empty_content(s):
                kept.append(s)
        if len(kept) >= max_lines:
            break
    if kept:
        return kept
    # fallback: keep first non-empty bullet-ish lines
    for ln in lines:
        s = ln.strip()
        if not s or _is_empty_content(s):
            continue
        if s.startswith("-") or s.startswith("*") or s.startswith("`") or s.startswith("Files:"):
            kept.append(s)
        if len(kept) >= max_lines:
            break
    return kept


def generate_evidence_pack(query: str, paths: Sequence[Path | str], max_lines: int = 12) -> str:
    """Generate markdown evidence pack from note paths."""
    rx = build_regex_from_query(query)
    out_lines: list[str] = []
    out_lines.append("# DailyNote Evidence Pack")
    out_lines.append(f"- Query: {query}")
    out_lines.append("")

    for p_str in paths:
        p = Path(p_str)
        if not p.exists():
            out_lines.append(f"## Missing: `{p_str}`")
            out_lines.append("")
            continue
        md = p.read_text(encoding="utf-8", errors="ignore")
        meta = extract_header(md)
        parsed_sections = parse_sections(md)

        out_lines.append(f"## `{p_str}`")
        title = meta.get("title", "").strip()
        if title:
            out_lines.append(f"- Title: {title}")
        date = meta.get("Date", "")
        time = meta.get("Time", "")
        ctx = meta.get("Context", "")
        if date:
            out_lines.append(f"- Date: {date}")
        if time:
            out_lines.append(f"- Time: {time}")
        if ctx:
            out_lines.append(f"- Context: {ctx}")
        out_lines.append("")

        # Use ordered sections, but also include any non-standard that match
        lang = _detect_note_language(parsed_sections)
        for sec in SECTION_ORDER:
            section_lines = sections.get_section(parsed_sections, sec)
            if not section_lines:
                continue
            filtered = filter_lines(section_lines, rx, max_lines)
            if not filtered:
                continue
            # Display section name in the note's language
            display_name = sec if lang == "ja" else sections.NOTE_SECTION_ALIASES.get(sec, sec)
            section_entries: list[str] = []
            for ln in filtered:
                content = ln.lstrip("- ").strip()
                if not content or _is_empty_content(ln.strip()):
                    continue
                if len(content) > 300:
                    content = content[:300] + "\u2026"
                section_entries.append(f"- {content}")
            if not section_entries:
                continue
            out_lines.append(f"### {display_name}")
            out_lines.extend(section_entries)
            out_lines.append("")

        # If nothing extracted, include short excerpt of first 30 lines
        if out_lines and out_lines[-1] != "":
            out_lines.append("")

    return "\n".join(out_lines).rstrip() + "\n"
