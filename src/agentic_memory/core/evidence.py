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
        m = re.match(r"^- (\w+):\s*(.*)$", line)
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


def filter_lines(lines: list[str], rx: re.Pattern, max_lines: int) -> list[str]:
    """
    Keep lines matching rx, plus a few leading bullets if nothing matches.
    """
    kept = []
    for ln in lines:
        if rx.search(ln):
            s = ln.strip()
            if s:
                kept.append(s)
        if len(kept) >= max_lines:
            break
    if kept:
        return kept
    # fallback: keep first non-empty bullet-ish lines
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        if s.startswith("-") or s.startswith("*") or s.startswith("`") or s.startswith("Files:"):
            kept.append(s)
        if len(kept) >= max_lines:
            break
    return kept


def generate_evidence_pack(query: str, paths: list[Path | str], max_lines: int = 8) -> str:
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
        for sec in SECTION_ORDER:
            section_lines = sections.get_section(parsed_sections, sec)
            if not section_lines:
                continue
            filtered = filter_lines(section_lines, rx, max_lines)
            if not filtered:
                continue
            out_lines.append(f"### {sec}")
            for ln in filtered:
                # Avoid super long lines
                if len(ln) > 300:
                    ln = ln[:300] + "\u2026"
                out_lines.append(f"- {ln.lstrip('- ').strip()}")
            out_lines.append("")

        # If nothing extracted, include short excerpt of first 30 lines
        if out_lines and out_lines[-1] != "":
            out_lines.append("")

    return "\n".join(out_lines).rstrip() + "\n"
