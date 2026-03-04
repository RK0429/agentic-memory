"""
index.py — Build / update memory index JSONL (lightweight, explainable index)

Why this exists:
- Improves retrieval quality and speed without bloating agent context.
- Extracts *structured* signals
  (title/date/tags/files/errors/skills/decisions/next...) deterministically.
- Standard library only.
"""

from __future__ import annotations

import datetime as _dt
import fcntl
import json
import os
import re
import sys
import tempfile
import time
from contextlib import suppress
from pathlib import Path
from typing import TextIO

from agentic_memory.core import dense, sections, signals, tokenizer

ERROR_PATTERNS = [
    r"\b[A-Z]{2,}[A-Z0-9_]{2,}\b",  # ECONNRESET, ERR_FOO_BAR
    r"\bHTTP\s?[1-5]\d{2}\b",  # HTTP 500
    r"\b[1-5]\d{2}\b",  # 500, 404 (weak)
    r"\b[A-Za-z]+Exception\b",
    r"\b[A-Za-z]+Error\b",
    r"\bTraceback\b",
]

STOPWORDS = set(
    [
        "the",
        "and",
        "or",
        "to",
        "of",
        "in",
        "a",
        "an",
        "for",
        "on",
        "with",
        "by",
        "md",
        "daily",
        "note",
        "files",
        "result",
        "tests",
        "time",
        "date",
        "context",
    ]
)
CJK_CHUNK_RE = tokenizer.CJK_CHUNK_RE
TASK_ID_PATTERN = re.compile(r"^(TASK|GOAL)-\d{3,}$")
TASK_ID_EXTRACT_PATTERN = re.compile(r"\b((?:TASK|GOAL)-\d{3,})\b")


def now_iso() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def _normalize_note_path(note_path: Path, dailynote_dir: Path) -> str:
    """Normalize note path to daily_note/... relative form."""
    try:
        return str(note_path.resolve().relative_to(dailynote_dir.resolve().parent))
    except ValueError:
        # If path cannot be made relative, use as-is
        return str(note_path)


def _atomic_write_text(path: Path, content: str) -> None:
    """Write content to path atomically via temp file + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, str(path))
    except BaseException:
        with suppress(OSError):
            os.unlink(tmp)
        raise


normalize_text = tokenizer.normalize_text


def read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="ignore")


def first_h1(md: str) -> str:
    for ln in md.splitlines():
        if ln.startswith("# "):
            return ln[2:].strip()
    return "Untitled"


def header_field(md: str, label: str) -> str:
    # matches "- Label: value" before the first "##"
    rx = re.compile(rf"^- {re.escape(label)}:\s*(.*)\s*$", re.MULTILINE)
    m = rx.search(md)
    if not m:
        return ""
    return m.group(1).strip()


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = normalize_text(value).strip()
    return normalized or None


def _normalize_task_id(value: str | None) -> str | None:
    normalized = _normalize_optional_text(value)
    if not normalized:
        return None
    upper = normalized.upper()
    if TASK_ID_PATTERN.fullmatch(upper):
        return upper
    match = TASK_ID_EXTRACT_PATTERN.search(upper)
    if match:
        return match.group(1)
    return None


def _resolve_task_id(task_id: str | None, md: str) -> str | None:
    explicit = _normalize_optional_text(task_id)
    if explicit is not None:
        resolved = _normalize_task_id(explicit)
        if resolved is None:
            raise ValueError(f"Invalid task_id: {task_id!r}")
        return resolved

    header = _normalize_task_id(header_field(md, "Task-ID"))
    if header:
        return header

    return _normalize_task_id(md)


def parse_list_field(v: str) -> list[str]:
    v = normalize_text(v).strip()
    if not v:
        return []
    v = v.strip("[]")
    parts = [p.strip() for p in re.split(r"[,\u3001\uFF0C;；]+", v)]
    return dedupe([p for p in parts if p])


def parse_sections(md: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    cur = None
    for ln in md.splitlines():
        m = re.match(r"^##\s+(.*)\s*$", ln)
        if m:
            cur = m.group(1).strip()
            sections.setdefault(cur, [])
            continue
        if cur is not None:
            sections[cur].append(ln.rstrip())
    return sections


def bullets(lines: list[str]) -> list[str]:
    out = []
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        if s.startswith("-"):
            out.append(s.lstrip("-").strip())
    return out


def indent_width(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def is_path_like(candidate: str) -> bool:
    c = (candidate or "").strip()
    if not c:
        return False
    if c.lower().startswith(("files:", "notes:", "tests:", "result:")):
        return False

    # Windows absolute path
    if re.match(r"^[A-Za-z]:\\", c):
        return True

    # Relative/absolute unix-like path or basename with extension
    if "/" in c or "\\" in c:
        return re.fullmatch(r"[A-Za-z0-9._~\-/\\]+", c) is not None
    if "." in c and re.fullmatch(r"[A-Za-z0-9._~\-]+", c):
        return re.search(r"\.[A-Za-z0-9_+\-]{1,10}$", c) is not None
    return False


def normalize_path_candidate(raw: str) -> str:
    c = (raw or "").strip()
    if not c:
        return ""
    # prefer backtick-enclosed token if present
    m = re.search(r"`([^`]+)`", c)
    c = m.group(1).strip() if m else c.split(" ", 1)[0].strip()
    c = c.strip("`'\",.;:()[]{}")
    return c if is_path_like(c) else ""


def extract_files(changes_lines: list[str]) -> list[str]:
    files = []
    i = 0
    while i < len(changes_lines):
        ln = changes_lines[i]
        s = ln.strip()
        if not re.match(r"^-\s*Files:\s*$", s, re.IGNORECASE):
            i += 1
            continue

        base_indent = indent_width(ln)
        i += 1
        while i < len(changes_lines):
            cur = changes_lines[i]
            cur_s = cur.strip()
            cur_indent = indent_width(cur)

            if not cur_s:
                i += 1
                continue

            # Leave Files subsection when a sibling list item starts.
            if cur_indent <= base_indent and cur_s.startswith("-"):
                break

            if cur_indent > base_indent and cur_s.startswith("-"):
                cand = normalize_path_candidate(cur_s.lstrip("-").strip())
                if cand:
                    files.append(cand)
            i += 1
    return dedupe(files)


def extract_commands(cmd_lines: list[str]) -> list[str]:
    cmds = []
    in_code = False
    for ln in cmd_lines:
        if ln.strip().startswith("```"):
            in_code = not in_code
            continue
        s = ln.strip()
        if not s:
            continue
        if in_code:
            cmds.append(s)
        elif s.startswith("-"):
            cmds.append(s.lstrip("-").strip())
    return dedupe(cmds)[:30]


def extract_plan_keywords(plan_lines: list[str]) -> list[str]:
    """Extract keyword-like tokens from Plan/計画 section."""
    raw_lines: list[str] = []
    for ln in plan_lines:
        s = ln.strip()
        if not s:
            continue
        if s.startswith("-"):
            s = s.lstrip("-").strip()
        if s:
            raw_lines.append(s)
    tokens = split_tokens(" ".join(raw_lines))
    return dedupe(tokens)[:30]


_TEST_PLACEHOLDERS = {
    "",
    "none",
    "n/a",
    "na",
    "なし",
    "-",
}


def _normalize_test_item(raw: str) -> str:
    s = normalize_text(raw).strip().strip("`'\"")
    if not s:
        return ""
    s = s.strip("`'\"")
    if not s:
        return ""
    if s.lower() in _TEST_PLACEHOLDERS:
        return ""
    return s


def _extract_inline_test_items(s: str) -> list[str]:
    if not s:
        return []
    parts = [p.strip() for p in re.split(r"[,\u3001\uFF0C;；]+", s)]
    out: list[str] = []
    for part in parts:
        item = _normalize_test_item(part)
        if item:
            out.append(item)
    return out


def extract_test_names(verification_lines: list[str]) -> list[str]:
    """Extract test names/commands under Verification > Tests."""
    out: list[str] = []
    in_tests = False
    for ln in verification_lines:
        s = ln.strip()
        if not s:
            continue

        # Normalize common markdown bullets and heading markers.
        plain = re.sub(r"^\s*[-*]\s*", "", s).strip()
        plain = re.sub(r"^#{1,6}\s*", "", plain).strip()
        plain_lower = plain.lower()

        tests_heading = re.match(r"^tests?\s*:?\s*(.*)$", plain_lower)
        result_heading = re.match(r"^result\s*:?\s*(.*)$", plain_lower)

        if tests_heading is not None:
            in_tests = True
            rest_original = re.sub(r"^tests?\s*:?\s*", "", plain, flags=re.IGNORECASE).strip()
            out.extend(_extract_inline_test_items(rest_original))
            continue
        if result_heading is not None:
            in_tests = False
            continue

        if in_tests:
            candidate = re.sub(r"^\s*[-*]\s*", "", s).strip()
            out.extend(_extract_inline_test_items(candidate))
    return dedupe(out)[:30]


def extract_errors(md: str) -> list[str]:
    out = []
    for pat in ERROR_PATTERNS:
        for m in re.finditer(pat, md):
            tok = m.group(0)
            # trim too common numbers (e.g., 200, 201)
            if tok.isdigit() and tok in {"200", "201", "202", "204"}:
                continue
            if len(tok) < 4 and tok.isdigit():
                continue
            out.append(tok)
    # keep somewhat unique + short list
    return dedupe(out)[:40]


def extract_skill_candidates(lines: list[str]) -> list[str]:
    out = []
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        if "SKILL:" in s.upper():
            # strip leading bullet, keep after SKILL:
            s2 = re.sub(r"^-?\s*SKILL:\s*", "", s, flags=re.IGNORECASE)
            s2 = s2.split("\u2014", 1)[0].strip()
            if s2 and s2.lower() != "none":
                out.append(s2)
    return dedupe(out)


def extract_skill_feedback(lines: list[str]) -> list[dict]:
    """Parse SIGFB lines into structured feedback entries.

    Format: SIGFB: <skill_path> | <signal_type> | <description>
    Validates signal_type against known types; warns on stderr for unknown types.
    """
    valid_types = set(signals.SIGNAL_TYPES)
    out = []
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        if "SIGFB:" in s.upper():
            s2 = re.sub(r"^-?\s*SIGFB:\s*", "", s, flags=re.IGNORECASE)
            if s2.lower() in ("none", ""):
                continue
            parts = [p.strip() for p in s2.split("|")]
            if len(parts) >= 3:
                signal_type = parts[1]
                if signal_type not in valid_types:
                    print(f"Warning: unknown SIGFB type '{signal_type}' in: {s}", file=sys.stderr)
                out.append(
                    {
                        "skill": parts[0],
                        "type": parts[1],
                        "desc": parts[2],
                    }
                )
            elif len(parts) == 2:
                signal_type = parts[1]
                if signal_type not in valid_types:
                    print(f"Warning: unknown SIGFB type '{signal_type}' in: {s}", file=sys.stderr)
                out.append(
                    {
                        "skill": parts[0],
                        "type": parts[1],
                        "desc": "",
                    }
                )
    return out


def summary_from_sections(secs: dict[str, list[str]], max_chars: int) -> str:
    preferred = ["成果", "目標", "判断", "次のアクション", "注意点・残課題"]
    for key in preferred:
        lines = [ln.strip() for ln in sections.get_section(secs, key) if ln.strip()]
        # take first 2 non-empty lines (bullets or text)
        take = []
        for ln in lines:
            if ln.startswith("-"):
                take.append(ln.lstrip("-").strip())
            else:
                take.append(ln)
            if len(take) >= 2:
                break
        if take:
            s = " | ".join(take)
            s = re.sub(r"\s+", " ", s).strip()
            return (s[:max_chars] + "\u2026") if len(s) > max_chars else s
    return ""


def split_tokens(s: str) -> list[str]:
    return tokenizer.tokenize(s, stopwords=STOPWORDS, min_length=2)


def auto_keywords(
    title: str,
    tags: list[str],
    keywords: list[str],
    files: list[str],
    errors: list[str],
    skills: list[str],
    work_log_keywords: list[str] | None = None,
    plan_keywords: list[str] | None = None,
    test_names: list[str] | None = None,
) -> list[str]:
    seed = []
    seed.extend(split_tokens(title))
    seed.extend(tags)
    seed.extend(keywords)
    seed.extend(files)
    seed.extend(errors)
    seed.extend(skills)
    if work_log_keywords:
        seed.extend(work_log_keywords)
    if plan_keywords:
        seed.extend(plan_keywords)
    if test_names:
        seed.extend(test_names)
    # normalize, keep unique
    seed_norm = []
    for t in seed:
        if not t:
            continue
        # keep both original and lower for search friendliness
        seed_norm.append(t)
        seed_norm.append(t.lower())
    return dedupe(seed_norm)[:40]


def dedupe(xs: list[str]) -> list[str]:
    seen = set()
    out = []
    for x in xs:
        k = re.sub(r"\s+", " ", normalize_text(x).strip())
        if not k:
            continue
        key = k.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(k)
    return out


def _index_lock_path(index_path: Path) -> Path:
    return Path(f"{index_path}.lock")


def _acquire_index_lock(index_path: Path, timeout_seconds: float = 5.0) -> TextIO:
    lock_path = _index_lock_path(index_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = open(lock_path, "w", encoding="utf-8")
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return lock_file
        except BlockingIOError as exc:
            if time.monotonic() >= deadline:
                lock_file.close()
                raise TimeoutError("Could not acquire index lock within 5s") from exc
            time.sleep(0.1)


def _read_index_rows(index_path: Path) -> list[dict]:
    rows: list[dict] = []
    if not index_path.exists():
        return rows
    for line in index_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def _write_index_rows(index_path: Path, rows: list[dict]) -> None:
    payload = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
    if payload:
        payload += "\n"
    _atomic_write_text(index_path, payload)


def upsert(index_path: Path, entry: dict):
    index_path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = _acquire_index_lock(index_path)
    try:
        rows = _read_index_rows(index_path)
        out = []
        replaced = False
        for r in rows:
            if r.get("path") == entry["path"]:
                out.append(entry)
                replaced = True
            else:
                out.append(r)
        if not replaced:
            out.append(entry)
        _write_index_rows(index_path, out)
    finally:
        fcntl.flock(lock_file, fcntl.LOCK_UN)
        lock_file.close()


def _replace_all(index_path: Path, rows: list[dict]) -> None:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = _acquire_index_lock(index_path)
    try:
        _write_index_rows(index_path, rows)
    finally:
        fcntl.flock(lock_file, fcntl.LOCK_UN)
        lock_file.close()


def _normalize_agent_id(value: str | None) -> str | None:
    return _normalize_optional_text(value)


def _normalize_relay_session_id(value: str | None) -> str | None:
    return _normalize_optional_text(value)


def upsert_dense(index_path: Path, entry: dict) -> bool:
    """Incrementally update dense index for a single upserted entry."""
    if not dense.is_dense_available():
        return False

    path = str(entry.get("path", "")).strip()
    if not path:
        return False

    model = dense._get_model()
    if model is None:
        return False

    try:
        import numpy as np
    except Exception:
        return False

    index_dir = index_path.parent
    dense_path = index_dir / dense.DENSE_FILE_NAME
    dense_paths_path = index_dir / dense.DENSE_PATHS_FILE_NAME

    try:
        vector = model.encode(
            [dense._entry_to_text(entry)],
            convert_to_numpy=True,
            show_progress_bar=False,
            normalize_embeddings=False,
        )
    except Exception as exc:
        print(f"[dn_index] Dense encode failed: {exc}", file=sys.stderr)
        return False

    vec = np.asarray(vector, dtype=np.float32)
    if vec.ndim == 2:
        vec = vec[0]
    if vec.ndim != 1:
        print("[dn_index] Dense vector has invalid shape.", file=sys.stderr)
        return False

    vector_dim = int(vec.shape[0])
    dense_matrix = np.zeros((0, vector_dim), dtype=np.float32)
    paths: list[str] = []

    if dense_paths_path.exists():
        try:
            loaded_paths = json.loads(dense_paths_path.read_text(encoding="utf-8"))
            if isinstance(loaded_paths, list):
                paths = [str(p) for p in loaded_paths]
        except Exception:
            paths = []

    if dense_path.exists():
        try:
            loaded_dense = np.asarray(np.load(dense_path), dtype=np.float32)
            if loaded_dense.ndim == 1:
                if loaded_dense.size == 0:
                    loaded_dense = np.zeros((0, vector_dim), dtype=np.float32)
                else:
                    loaded_dense = loaded_dense.reshape(1, -1)
            if loaded_dense.ndim == 2:
                dense_matrix = loaded_dense
        except Exception:
            dense_matrix = np.zeros((0, vector_dim), dtype=np.float32)

    if dense_matrix.shape[0] > 0 and dense_matrix.shape[1] != vector_dim:
        print(
            "[dn_index] Dense vector dimension mismatch. Reinitializing dense index incrementally.",
            file=sys.stderr,
        )
        dense_matrix = np.zeros((0, vector_dim), dtype=np.float32)
        paths = []

    usable = min(len(paths), int(dense_matrix.shape[0]))
    if usable != int(dense_matrix.shape[0]):
        dense_matrix = dense_matrix[:usable]
    if usable != len(paths):
        paths = paths[:usable]

    if path in paths:
        idx = paths.index(path)
        dense_matrix[idx] = vec
    else:
        dense_matrix = np.vstack([dense_matrix, vec.reshape(1, -1)])
        paths.append(path)

    index_dir.mkdir(parents=True, exist_ok=True)
    try:
        np.save(dense_path, dense_matrix.astype(np.float32, copy=False))
        _atomic_write_text(dense_paths_path, json.dumps(paths, ensure_ascii=False))
    except OSError as exc:
        print(f"[dn_index] Failed to save dense upsert artifacts: {exc}", file=sys.stderr)
        return False
    return True


def detect_sigfb_status(sigfb_lines: list[str]) -> str:
    """Detect SIGFB section status.

    Returns:
        'recorded' — at least one valid SIGFB entry exists
        'explicit_none' — 'SIGFB: none' is explicitly recorded
        'missing' — section absent, empty, or template default unchanged
    """
    has_content = False
    for ln in sigfb_lines:
        s = ln.strip()
        if not s:
            continue
        if "SIGFB:" in s.upper():
            s2 = re.sub(r"^-?\s*SIGFB:\s*", "", s, flags=re.IGNORECASE)
            if s2.lower().strip() == "none":
                return "explicit_none"
            if s2.strip():
                has_content = True
    return "recorded" if has_content else "missing"


def build_entry(
    note_path: Path,
    max_summary_chars: int,
    dailynote_dir: Path,
    task_id: str | None = None,
    agent_id: str | None = None,
    relay_session_id: str | None = None,
) -> dict:
    md = read_text(note_path)
    title = first_h1(md)
    date = header_field(md, "Date")
    time = header_field(md, "Time")
    context = header_field(md, "Context")
    resolved_task_id = _resolve_task_id(task_id, md)
    resolved_agent_id = (
        _normalize_agent_id(agent_id)
        if agent_id is not None
        else _normalize_agent_id(header_field(md, "Agent-ID"))
    )
    resolved_relay_session_id = (
        _normalize_relay_session_id(relay_session_id)
        if relay_session_id is not None
        else _normalize_relay_session_id(header_field(md, "Relay-Session-ID"))
    )
    tags = parse_list_field(header_field(md, "Tags"))
    keywords = parse_list_field(header_field(md, "Keywords"))

    secs = parse_sections(md)

    files = extract_files(sections.get_section(secs, "変更点"))
    cmds = extract_commands(sections.get_section(secs, "コマンド"))
    work_log_lines = sections.get_section(secs, "作業ログ")
    work_log_tokens = split_tokens(" ".join(work_log_lines))
    work_log_kw = dedupe(work_log_tokens)[:30]
    plan_kw = extract_plan_keywords(sections.get_section(secs, "計画"))
    test_names = extract_test_names(sections.get_section(secs, "検証"))
    errs = extract_errors(md)
    skc = extract_skill_candidates(sections.get_section(secs, "スキル候補"))
    skfb = extract_skill_feedback(sections.get_section(secs, "スキルフィードバック"))
    sigfb_status = detect_sigfb_status(sections.get_section(secs, "スキルフィードバック"))

    decisions_text = "\n".join(bullets(sections.get_section(secs, "判断"))[:12])
    next_text = "\n".join(bullets(sections.get_section(secs, "次のアクション"))[:12])
    pitfalls_text = "\n".join(bullets(sections.get_section(secs, "注意点・残課題"))[:12])

    summ = summary_from_sections(secs, max_summary_chars)

    auto_kw = auto_keywords(
        title, tags, keywords, files, errs, skc, work_log_kw, plan_kw, test_names
    )

    return {
        "path": _normalize_note_path(note_path, dailynote_dir),
        "task_id": resolved_task_id,
        "agent_id": resolved_agent_id,
        "relay_session_id": resolved_relay_session_id,
        "title": title,
        "date": date,
        "time": time,
        "context": context,
        "tags": tags,
        "keywords": keywords,
        "auto_keywords": auto_kw,
        "files": files,
        "errors": errs,
        "skills": skc,
        "skill_feedback": skfb,
        "sigfb_status": sigfb_status,
        "decisions": decisions_text,
        "next": next_text,
        "pitfalls": pitfalls_text,
        "commands": cmds,
        "summary": summ,
        "work_log_keywords": work_log_kw,
        "plan_keywords": plan_kw,
        "test_names": test_names,
        "indexed_at": now_iso(),
    }


def build_vocab_cache(entries: list[dict], vocab_path: Path) -> int:
    """Build vocabulary cache from index entries for fuzzy matching support."""
    tokens: set[str] = set()
    for entry in entries:
        for field in (
            "tags",
            "keywords",
            "auto_keywords",
            "files",
            "errors",
            "skills",
            "plan_keywords",
            "test_names",
        ):
            values = entry.get(field) or []
            if isinstance(values, list):
                for v in values:
                    v_norm = normalize_text(str(v)).strip()
                    if v_norm:
                        tokens.add(v_norm)
    vocab = sorted(tokens)
    vocab_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(
        vocab_path,
        json.dumps({"vocab": vocab, "built_at": now_iso()}, ensure_ascii=False, indent=2) + "\n",
    )
    return len(vocab)


def update_vocab_cache_incremental(entry: dict, vocab_path: Path) -> None:
    """Add new tokens from a single entry to the existing vocab cache."""
    existing: set[str] = set()
    if vocab_path.exists():
        try:
            data = json.loads(vocab_path.read_text(encoding="utf-8"))
            existing = set(data.get("vocab") or [])
        except Exception:
            pass
    for field in (
        "tags",
        "keywords",
        "auto_keywords",
        "files",
        "errors",
        "skills",
        "plan_keywords",
        "test_names",
    ):
        values = entry.get(field) or []
        if isinstance(values, list):
            for v in values:
                v_norm = normalize_text(str(v)).strip()
                if v_norm:
                    existing.add(v_norm)
    vocab = sorted(existing)
    vocab_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(
        vocab_path,
        json.dumps({"vocab": vocab, "built_at": now_iso()}, ensure_ascii=False, indent=2) + "\n",
    )


def _vocab_is_stale(vocab_path: Path, index_path: Path) -> bool:
    """Check if vocab cache is stale (older than index)."""
    if not vocab_path.exists():
        return True
    if not index_path.exists():
        return False
    try:
        return vocab_path.stat().st_mtime < index_path.stat().st_mtime
    except OSError:
        return False


def list_notes(dailynote_dir: Path) -> list[Path]:
    if not dailynote_dir.exists():
        return []
    notes = []
    for p in dailynote_dir.rglob("*.md"):
        if not p.is_file():
            continue
        if p.name.startswith("_"):
            continue
        notes.append(p)
    return sorted(notes)


def rebuild_index(
    *,
    index_path: Path,
    dailynote_dir: Path,
    max_summary_chars: int = 280,
    no_dense: bool = False,
    since: str | None = None,
) -> list[dict]:
    """Rebuild the entire memory index from note files."""
    notes = list_notes(dailynote_dir)
    since_date = None
    if since:
        try:
            since_date = _dt.date.fromisoformat(since)
        except ValueError as exc:
            raise ValueError(f"Invalid since date: {since}") from exc

    entries: list[dict] = []
    for note_path in notes:
        # Apply since filter by checking directory date structure
        if since_date is not None:
            try:
                dir_date = _dt.date.fromisoformat(note_path.parent.name)
                if dir_date < since_date:
                    continue
            except ValueError:
                pass  # Non-date directory, include anyway
        entries.append(build_entry(note_path, max_summary_chars, dailynote_dir=dailynote_dir))

    _replace_all(index_path, entries)

    vocab_path = index_path.parent / "_vocab.json"
    build_vocab_cache(entries, vocab_path)

    if not no_dense:
        dense_ok = dense.build_embeddings(entries, index_path.parent)
        if not dense_ok:
            print("Warning: Dense embedding generation skipped or failed.", file=sys.stderr)
    return entries


def index_note(
    *,
    note_path: Path,
    index_path: Path,
    dailynote_dir: Path,
    task_id: str | None = None,
    agent_id: str | None = None,
    relay_session_id: str | None = None,
    max_summary_chars: int = 280,
    no_dense: bool = False,
) -> dict:
    """Upsert one note into the memory index and refresh auxiliary caches."""
    if not note_path.exists():
        raise FileNotFoundError(f"Note not found: {note_path}")

    entry = build_entry(
        note_path,
        max_summary_chars,
        dailynote_dir=dailynote_dir,
        task_id=task_id,
        agent_id=agent_id,
        relay_session_id=relay_session_id,
    )
    upsert(index_path, entry)

    vocab_path = index_path.parent / "_vocab.json"
    if _vocab_is_stale(vocab_path, index_path):
        rows: list[dict] = []
        if index_path.exists():
            rows = [
                json.loads(line)
                for line in index_path.read_text(encoding="utf-8", errors="ignore").splitlines()
                if line.strip()
            ]
        build_vocab_cache(rows, vocab_path)
    else:
        update_vocab_cache_incremental(entry, vocab_path)

    if not no_dense:
        dense_ok = upsert_dense(index_path, entry)
        if not dense_ok:
            print("Warning: Dense embedding upsert skipped or failed.", file=sys.stderr)

    return entry
