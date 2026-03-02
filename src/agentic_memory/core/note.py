"""Note creation utilities for agentic-memory."""

from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path

TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "assets/note-template.md"


def now_local() -> _dt.datetime:
    return _dt.datetime.now()


def slugify(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9\s\-_.]+", "", s)
    s = s.replace("_", "-").replace(".", "-")
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s or "session"


def read_template() -> str:
    tpl = TEMPLATE_PATH.resolve()
    if tpl.exists():
        return tpl.read_text(encoding="utf-8")
    return "# <short title>\n- Date: <YYYY-MM-DD>\n- Time: <HH:MM> - <HH:MM>\n\n## 目標\n- \n"


def create_note(
    memory_dir: Path,
    title: str,
    context: str | None = None,
    tags: str | None = None,
    keywords: str | None = None,
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

    tpl = read_template()
    content = tpl
    content = content.replace("<short title>", title)
    content = content.replace("<YYYY-MM-DD>", date_s)
    content = content.replace("<HH:MM> - <HH:MM>", f"{start} - {end}")
    content = content.replace("<HH:MM>", start)
    if context is not None:
        content = content.replace("\\<issue/pr/link or N/A>", context)
    if tags is not None:
        content = content.replace("\\<comma,separated,tags or empty>", tags)
    if keywords is not None:
        content = content.replace("\\<comma,separated,keywords or empty>", keywords)

    out_path.write_text(content, encoding="utf-8")
    return out_path
