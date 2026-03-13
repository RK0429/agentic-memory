"""Note creation utilities for agentic-memory."""

from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path

from agentic_memory.core import config as memory_config


def now_local() -> _dt.datetime:
    return _dt.datetime.now()


def slugify(s: str, max_length: int = 50) -> str:
    """Create a filesystem-safe slug from a title string.

    CJK characters are preserved as-is for human readability.
    ASCII characters are lowercased and non-alphanumeric chars
    are replaced with hyphens (standard slug behavior).
    """
    original = s.strip()
    if not original:
        return "session"

    # Remove filesystem-unsafe characters
    s = re.sub(r'[/\\:*?"<>|\x00\r\n]+', "", original)

    # Per-character processing: lowercase ASCII, keep CJK
    result: list[str] = []
    for ch in s:
        if ch.isascii():
            lower = ch.lower()
            if lower.isalnum():
                result.append(lower)
            elif lower in " \t_.-":
                result.append("-")
            # other ASCII punctuation is dropped
        else:
            result.append(ch)

    s = "".join(result)
    s = re.sub(r"-{2,}", "-", s).strip("-")

    if len(s) > max_length:
        s = s[:max_length].rstrip("-")

    return s or "session"


def read_template(lang: str = "ja") -> str:
    return memory_config.load_template(lang=lang)


def create_note(
    memory_dir: Path,
    title: str,
    context: str | None = None,
    tags: str | None = None,
    keywords: str | None = None,
    auto_index: bool = True,
    lang: str = "ja",
) -> Path:
    """Create a new note from template and return created file path."""
    dt = now_local()
    date_s = dt.strftime("%Y-%m-%d")
    hhmm = dt.strftime("%H%M")
    start = dt.strftime("%H:%M")
    end = dt.strftime("%H:%M")

    slug = slugify(title)

    out_dir = memory_dir / date_s
    out_dir.mkdir(parents=True, exist_ok=True)

    out_path = out_dir / f"{hhmm}_{slug}.md"

    if out_path.exists():
        i = 2
        while True:
            cand = out_dir / f"{hhmm}_{slug}_{i}.md"
            if not cand.exists():
                out_path = cand
                break
            i += 1

    tpl = read_template(lang=lang)
    content = tpl
    content = content.replace("<short title>", title)
    content = content.replace("<YYYY-MM-DD>", date_s)
    content = content.replace("<HH:MM> - <HH:MM>", f"{start} - {end}")
    content = content.replace("<HH:MM>", start)
    content = content.replace("\\<issue/pr/link or N/A>", context or "")
    content = content.replace("\\<comma,separated,tags or empty>", tags or "")
    content = content.replace("\\<comma,separated,keywords or empty>", keywords or "")

    out_path.write_text(content, encoding="utf-8")

    if auto_index:
        from agentic_memory.core import index

        index.index_note(
            note_path=out_path,
            index_path=memory_dir / "_index.jsonl",
            dailynote_dir=memory_dir,
        )

    return out_path
