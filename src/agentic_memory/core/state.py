"""State management utilities for agentic-memory."""

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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agentic_memory.core import sections, signals

resolve_short_key = sections.resolve_short_key
get_cap = sections.get_cap
STATE_SHORT_KEYS = sections.STATE_SHORT_KEYS
STATE_CAPS = sections.STATE_CAPS
STATE_SECTION_ALIASES = sections.STATE_SECTION_ALIASES
get_section = sections.get_section

SECTION_ORDER = list(sections.STATE_SHORT_KEYS.values())

_LIST_WITH_DATE_RE = re.compile(r"^\-\s*\[(\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2})?)\]\s*(.*)$")
_LIST_RE = re.compile(r"^\-\s*(.*)$")
_DATE_PREFIX_RE = re.compile(r"^\[(\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2})?)\]\s*(.*)$")
_HEADING_RE = re.compile(r"^##\s+(.*)\s*$")
_SPACE_RE = re.compile(r"\s+")
_NONE_SKILL_RE = re.compile(r"^\s*(?:skill|skil)\s*:\s*none\s*$", flags=re.IGNORECASE)
_PLACEHOLDER_TEXTS = {"", "(empty)", "なし"}
TASK_ID_EXTRACT_PATTERN = re.compile(r"\b((?:TASK|GOAL)-\d{3,})\b")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def now_stamp() -> str:
    """現在時刻を 'YYYY-MM-DD HH:MM' 形式で返す"""
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M")


def _parse_datetime(date_str: str) -> _dt.datetime | None:
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return _dt.datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None


def _is_placeholder(text: str) -> bool:
    norm = text.strip().lower()
    return norm in _PLACEHOLDER_TEXTS


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


@dataclass
class StateItem:
    date: str
    text: str

    def render(self) -> str:
        """'- [2026-02-22 19:30] text' 形式で返す"""
        return f"- [{self.date}] {self.text.strip()}"

    def normalize_key(self) -> str:
        """重複検出用キー。テキストを正規化（空白圧縮・小文字化）して返す"""
        return _SPACE_RE.sub(" ", self.text.strip()).lower()

    @classmethod
    def parse(cls, line: str) -> StateItem | None:
        """行をパースして StateItem を返す。
        - '- [YYYY-MM-DD HH:MM] text' 形式の場合はそのまま
        - '- text'（日付なし）の場合は今日の日付で補完
        - プレースホルダー（'- (empty)', '- なし', '- ')は None を返す
        - 空行やリスト項目でない行は None を返す
        """
        s = line.strip()
        if not s:
            return None

        m = _LIST_WITH_DATE_RE.match(s)
        if m:
            date = m.group(1).strip()
            text = m.group(2).strip()
            if _is_placeholder(text):
                return None
            return cls(date=date, text=text)

        m = _LIST_RE.match(s)
        if not m:
            return None
        text = m.group(1).strip()
        if _is_placeholder(text):
            return None
        return cls(date=now_stamp(), text=text)

    @classmethod
    def from_text(cls, text: str, date: str | None = None) -> StateItem:
        """テキストから StateItem を作成。日付未指定時は今日の日付。
        テキストが既に [YYYY-MM-DD HH:MM] で始まっている場合はそこから日付を抽出する。
        """
        raw = text.strip()
        if not raw:
            raise ValueError("item text is empty")

        if raw.startswith("-"):
            parsed = cls.parse(raw)
            if parsed is None:
                raise ValueError("invalid item text")
            return parsed

        m = _DATE_PREFIX_RE.match(raw)
        if m:
            d = m.group(1).strip()
            body = m.group(2).strip()
            if _is_placeholder(body):
                raise ValueError("item text is empty")
            return cls(date=d, text=body)

        if _is_placeholder(raw):
            raise ValueError("item text is empty")
        return cls(date=(date or now_stamp()), text=raw)


def parse_sections(md: str) -> dict[str, list[str]]:
    """Markdown を ## 見出しごとにパースして {見出し名: [行リスト]} を返す"""
    sections: dict[str, list[str]] = {}
    cur = None
    for line in md.splitlines():
        m = _HEADING_RE.match(line)
        if m:
            cur = m.group(1).strip()
            sections.setdefault(cur, [])
            continue
        if cur is not None:
            sections[cur].append(line.rstrip())
    return sections


def load_state(path: Path) -> dict[str, list[StateItem]]:
    """ステートファイルを読み込み、セクションごとの StateItem リストを返す。
    ファイルが存在しない場合は空のセクション辞書を返す。
    SECTION_ORDER に定義された全セクションが含まれるよう保証する。
    """
    out: dict[str, list[StateItem]] = {sec: [] for sec in SECTION_ORDER}
    if not path.exists():
        return out

    md = path.read_text(encoding="utf-8", errors="ignore")
    secs = parse_sections(md)
    for sec in SECTION_ORDER:
        parsed: list[StateItem] = []
        for line in get_section(secs, sec):
            item = StateItem.parse(line)
            if item is not None:
                parsed.append(item)
        out[sec] = parsed
    return out


def _empty_sections() -> dict[str, list[StateItem]]:
    return {sec: [] for sec in SECTION_ORDER}


def ensure_state_file(path: Path) -> Path:
    if path.exists():
        return path
    save_state(path, _empty_sections())
    return path


def _normalize_identifier(name: str, value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} is required")
    if not _IDENTIFIER_RE.fullmatch(normalized):
        raise ValueError(
            f"Invalid {name}: {value!r} (allowed characters: letters, digits, '_' and '-')"
        )
    return normalized


def resolve_agent_state_path(
    memory_dir: Path,
    agent_id: str,
    relay_session_id: str | None = None,
    *,
    for_write: bool = False,
) -> Path:
    normalized_agent_id = _normalize_identifier("agent_id", agent_id)
    if relay_session_id is None:
        return memory_dir / f"_state.{normalized_agent_id}.md"

    normalized_session = _normalize_identifier("relay_session_id", relay_session_id)
    session_specific = memory_dir / f"_state.{normalized_agent_id}.{normalized_session}.md"
    if for_write:
        return session_specific

    if session_specific.exists():
        return session_specific

    shared = memory_dir / f"_state.{normalized_agent_id}.md"
    if shared.exists():
        return shared
    return session_specific


def state_sections_to_payload(
    sections_data: dict[str, list[StateItem]],
    *,
    section: str | None = None,
    stale_days: int = 0,
) -> dict[str, list[dict[str, object]]]:
    targets = _target_sections(section)
    payload: dict[str, list[dict[str, object]]] = {}
    for sec in targets:
        rows: list[dict[str, object]] = []
        for item in sections_data.get(sec, []):
            stale = bool(stale_days and is_stale(item, stale_days))
            rows.append({"date": item.date, "text": item.text, "stale": stale})
        payload[sec] = rows
    return payload


def state_sections_to_rendered(
    sections_data: dict[str, list[StateItem]],
) -> dict[str, list[str]]:
    rendered: dict[str, list[str]] = {}
    for short_key, section_name in STATE_SHORT_KEYS.items():
        rendered[short_key] = [item.render() for item in sections_data.get(section_name, [])]
    return rendered


def extract_task_ids_from_focus(sections_data: dict[str, list[StateItem]]) -> list[str]:
    focus_section = STATE_SHORT_KEYS["focus"]
    task_ids: list[str] = []
    seen: set[str] = set()
    for item in sections_data.get(focus_section, []):
        for match in TASK_ID_EXTRACT_PATTERN.finditer(item.text):
            task_id = match.group(1).upper()
            if task_id in seen:
                continue
            seen.add(task_id)
            task_ids.append(task_id)
    return task_ids


def _resolve_note_path_for_evidence(raw_path: str, memory_dir: Path) -> Path:
    candidate = Path(raw_path)
    if candidate.is_absolute():
        return candidate

    memory_prefixed = memory_dir.parent / candidate
    if memory_prefixed.exists():
        return memory_prefixed

    direct = memory_dir / candidate
    if direct.exists():
        return direct

    return memory_prefixed


def save_state(path: Path, sections: dict[str, list[StateItem]]) -> None:
    """セクション辞書をステートファイルに書き込む。
    ヘッダー: '# 作業状態（ローリング）\n\nLast updated: {now_stamp()}'
    各セクション: '## {見出し名}\n\n' + アイテムのrender()結果（空なら見出しのみ）
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = Path(f"{path}.lock")
    with open(lock_path, "w") as lock_file:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                try:
                    fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    time.sleep(0.1)
            else:
                raise TimeoutError("Could not acquire state lock within 5s")
        try:
            lines: list[str] = []
            lines.append("# 作業状態（ローリング）")
            lines.append("")
            lines.append(f"Last updated: {now_stamp()}")
            lines.append("")
            for sec in SECTION_ORDER:
                lines.append(f"## {sec}")
                lines.append("")
                for item in sections.get(sec, []):
                    lines.append(item.render())
                lines.append("")
            _atomic_write_text(path, "\n".join(lines).rstrip() + "\n")
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)


def _is_newer(lhs: StateItem, rhs: StateItem) -> bool:
    ld = _parse_datetime(lhs.date)
    rd = _parse_datetime(rhs.date)
    if ld is None and rd is None:
        return False
    if ld is None:
        return False
    if rd is None:
        return True
    return ld > rd


def deduplicate(items: list[StateItem]) -> list[StateItem]:
    """重複排除。normalize_key() で比較し、同一テキストは新しい日付のものを残す。
    順序は入力順を維持する。"""
    out: list[StateItem] = []
    index: dict[str, int] = {}
    for item in items:
        key = item.normalize_key()
        if not key:
            continue
        if key not in index:
            index[key] = len(out)
            out.append(item)
            continue
        pos = index[key]
        if _is_newer(item, out[pos]):
            out[pos] = item
    return out


def enforce_cap(items: list[StateItem], cap: int) -> list[StateItem]:
    """cap を超過する場合は末尾（最古=リスト末尾）を切り捨て"""
    safe_cap = max(cap, 0)
    if len(items) > safe_cap:
        dropped = items[safe_cap:]
        for item in dropped:
            print(f"Cap exceeded, dropping: [{item.date}] {item.text}", file=sys.stderr)
    return items[:safe_cap]


def is_stale(item: StateItem, stale_days: int) -> bool:
    """アイテムの日付が today - stale_days 以前なら True。
    日付が不正な場合も stale 扱い（True）"""
    dt = _parse_datetime(item.date)
    if dt is None:
        return True
    cutoff = _dt.datetime.now() - _dt.timedelta(days=stale_days)
    return dt <= cutoff


def bullets(lines: list[str]) -> list[str]:
    """行リストからリスト項目のテキスト部分を抽出する。

    `- ` を除去し、空行やリスト項目でない行はスキップする。
    """
    out: list[str] = []
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        if s.startswith("-"):
            out.append(s.lstrip("-").strip())
    return out


def _resolve_section_or_raise(key: str) -> str:
    return resolve_short_key(key)


def _target_sections(section_arg: str | None) -> list[str]:
    if section_arg is None:
        return list(SECTION_ORDER)
    return [_resolve_section_or_raise(section_arg)]


def _parse_items_or_raise(texts: list[str]) -> list[StateItem]:
    items: list[StateItem] = []
    for text in texts:
        items.append(StateItem.from_text(text))
    return items


def _is_none_skill(text: str) -> bool:
    norm = _SPACE_RE.sub(" ", text.strip()).lower()
    if norm == "none":
        return True
    return _NONE_SKILL_RE.match(norm) is not None


def _validate_non_negative(name: str, value: int) -> None:
    if value < 0:
        raise ValueError(f"{name} must be >= 0")


def cmd_show(
    state_path: Path,
    section: str | None = None,
    stale_days: int = 0,
    as_json: bool = False,
) -> int:
    try:
        _validate_non_negative("stale-days", stale_days)
        targets = _target_sections(section)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    sections_data = load_state(state_path)

    if as_json:
        payload: dict[str, dict[str, list[dict[str, object]]]] = {
            "sections": state_sections_to_payload(
                sections_data,
                section=section,
                stale_days=stale_days,
            )
        }
        print(json.dumps(payload, ensure_ascii=False))
        return 0

    for sec in targets:
        cap = get_cap(sec)
        items = sections_data.get(sec, [])
        print(f"## {sec} ({len(items)}/{cap})")
        if not items:
            print("- (empty)")
            print("")
            continue
        for item in items:
            stale_mark = " [STALE]" if stale_days and is_stale(item, stale_days) else ""
            print(f"{item.render()}{stale_mark}")
        print("")
    return 0


def cmd_set(state_path: Path, section: str, items: list[str]) -> int:
    try:
        section_name = _resolve_section_or_raise(section)
        new_items = _parse_items_or_raise(items)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    sections = load_state(state_path)
    sections[section_name] = enforce_cap(deduplicate(new_items), get_cap(section_name))
    save_state(state_path, sections)
    print(str(state_path))
    return 0


def cmd_add(state_path: Path, section: str, items: list[str]) -> int:
    try:
        section_name = _resolve_section_or_raise(section)
        new_items = _parse_items_or_raise(items)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    sections = load_state(state_path)
    merged = deduplicate(new_items + sections.get(section_name, []))
    sections[section_name] = enforce_cap(merged, get_cap(section_name))
    save_state(state_path, sections)
    print(str(state_path))
    return 0


def cmd_remove(state_path: Path, section: str, pattern: str, regex: bool = False) -> int:
    try:
        section_name = _resolve_section_or_raise(section)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    matcher = None
    if regex:
        try:
            matcher = re.compile(pattern)
        except re.error as exc:
            print(f"Invalid regex: {exc}", file=sys.stderr)
            return 2

    sections = load_state(state_path)
    kept: list[StateItem] = []
    removed = 0
    for item in sections.get(section_name, []):
        matched = (
            bool(matcher.search(item.text))
            if matcher is not None
            else pattern.lower() in item.text.lower()
        )
        if matched:
            removed += 1
            print(f"Removed: [{item.date}] {item.text}", file=sys.stderr)
        else:
            kept.append(item)

    if removed > 0:
        sections[section_name] = kept
        save_state(state_path, sections)
    print(str(removed))
    return 0


def cmd_prune(
    state_path: Path,
    stale_days: int = 7,
    section: str | None = None,
    dry_run: bool = False,
) -> int:
    try:
        _validate_non_negative("stale-days", stale_days)
        targets = _target_sections(section)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    sections = load_state(state_path)
    removed = 0

    for sec in targets:
        kept: list[StateItem] = []
        for item in sections.get(sec, []):
            if is_stale(item, stale_days):
                removed += 1
                print(f"Prune target: [{item.date}] {item.text}", file=sys.stderr)
            else:
                kept.append(item)
        if not dry_run:
            sections[sec] = kept

    if not dry_run and removed > 0:
        save_state(state_path, sections)
    print(str(removed))
    return 0


def _auto_prune(sections: dict[str, list[StateItem]], max_entries: int = 20) -> None:
    """Trim each rolling section to max_entries by dropping the oldest timestamps."""
    safe_max = max(max_entries, 0)
    for sec in SECTION_ORDER:
        items = sections.get(sec, [])
        if len(items) <= safe_max:
            continue
        ranked = sorted(
            enumerate(items),
            key=lambda pair: (_parse_datetime(pair[1].date) or _dt.datetime.min, -pair[0]),
            reverse=True,
        )
        keep_indices = {idx for idx, _ in ranked[:safe_max]}
        dropped = [item for idx, item in enumerate(items) if idx not in keep_indices]
        for item in dropped:
            print(f"Auto-prune, dropping: [{item.date}] {item.text}", file=sys.stderr)
        sections[sec] = [item for idx, item in enumerate(items) if idx in keep_indices]


def _extract_from_note(note_text: str) -> dict[str, list[str]]:
    secs = parse_sections(note_text)
    goal = bullets(get_section(secs, "目標"))
    nxt = bullets(get_section(secs, "次のアクション"))
    decisions = bullets(get_section(secs, "判断"))
    pitfalls = (
        bullets(get_section(secs, "注意点・残課題"))
        or bullets(get_section(secs, "注意点"))
        or bullets(get_section(secs, "Pitfalls"))
    )
    skills = [s for s in bullets(get_section(secs, "スキル候補")) if not _is_none_skill(s)]
    focus = nxt[:3] if nxt else goal[:3]

    return {
        STATE_SHORT_KEYS["focus"]: focus,
        STATE_SHORT_KEYS["open"]: nxt,
        STATE_SHORT_KEYS["decisions"]: decisions,
        STATE_SHORT_KEYS["pitfalls"]: pitfalls,
        STATE_SHORT_KEYS["skills"]: skills,
    }


def _normalize_note_path_for_index(note_path: Path, dailynote_dir: Path) -> str:
    try:
        return str(note_path.resolve().relative_to(dailynote_dir.resolve().parent))
    except ValueError:
        return str(note_path)


def _ensure_note_index_entry(
    entries: list[dict],
    note_path: Path | None,
    index_path: Path,
    max_summary_chars: int = 280,
) -> list[dict]:
    if note_path is None:
        return entries
    expected_path = _normalize_note_path_for_index(note_path, index_path.parent)
    for entry in entries:
        if isinstance(entry, dict) and str(entry.get("path", "")) == expected_path:
            return entries
    try:
        from agentic_memory.core import index

        built_entry = index.build_entry(
            note_path,
            max_summary_chars,
            dailynote_dir=index_path.parent,
        )
    except Exception:
        return entries
    return entries + [built_entry]


def _auto_improve_from_signals(
    index_path: Path,
    sections: dict[str, list[StateItem]],
    threshold: int = 3,
    note_path: Path | None = None,
    max_summary_chars: int = 280,
) -> list[StateItem]:
    """Analyze skill signals and return improvement candidates as StateItems.

    Processes both high-severity candidates from analyze_signals() and
    additional triggers from check_improvement_triggers().
    Fail-safe: returns empty list on any error (missing index, parse error, etc.).
    """
    try:
        entries: list[dict] = []
        if index_path.exists():
            entries = signals.load_index(index_path)
        entries = _ensure_note_index_entry(
            entries,
            note_path=note_path,
            index_path=index_path,
            max_summary_chars=max_summary_chars,
        )
        aggregated = signals.aggregate_signals(entries)
        candidates = signals.analyze_signals(aggregated, threshold=threshold)
    except Exception:
        return []

    existing_keys = {
        item.normalize_key() for item in sections.get(STATE_SHORT_KEYS["improvements"], [])
    }

    new_items: list[StateItem] = []

    # High-severity candidates from analyze_signals
    for cand in candidates:
        if cand.get("severity") != "high":
            continue
        skill = cand.get("skill", "")
        score = cand.get("weighted_score", 0)
        suggestion = cand.get("suggestion", "")
        text = f"[severity:high] {skill} (score={score}) — {suggestion}"
        item = StateItem.from_text(text)
        if item.normalize_key() not in existing_keys:
            new_items.append(item)
            existing_keys.add(item.normalize_key())

    # Additional triggers (periodic_review, pattern_escalation, gap_expansion)
    existing_backlog_texts = [
        item.text.lower() for item in sections.get(STATE_SHORT_KEYS["improvements"], [])
    ]
    triggers = signals.check_improvement_triggers(entries, candidates, existing_backlog_texts)
    for trig in triggers:
        ttype = trig.get("type", "")
        skill = trig.get("skill", "")
        detail = trig.get("detail", "")
        severity = trig.get("severity", "medium")
        text = f"[severity:{severity}][{ttype}] {skill} — {detail}"
        item = StateItem.from_text(text)
        if item.normalize_key() not in existing_keys:
            new_items.append(item)
            existing_keys.add(item.normalize_key())

    return new_items


_FROM_NOTE_CAP_BY_SECTION = {
    STATE_SHORT_KEYS["focus"]: 3,
    STATE_SHORT_KEYS["open"]: 8,
    STATE_SHORT_KEYS["decisions"]: 8,
    STATE_SHORT_KEYS["pitfalls"]: 8,
    STATE_SHORT_KEYS["skills"]: 8,
    STATE_SHORT_KEYS["improvements"]: 8,
}

_FROM_NOTE_MERGE_TARGETS = (
    STATE_SHORT_KEYS["focus"],
    STATE_SHORT_KEYS["open"],
    STATE_SHORT_KEYS["decisions"],
    STATE_SHORT_KEYS["pitfalls"],
    STATE_SHORT_KEYS["skills"],
)


def _resolve_index_path_for_note(note_path: Path, state_path: Path) -> Path:
    note_index_path = note_path.parent.parent / "_index.jsonl"
    if note_index_path.exists():
        return note_index_path
    return state_path.resolve().parent / "_index.jsonl"


def _merge_from_note(
    state_path: Path,
    note_path: Path,
    no_auto_improve: bool = False,
    auto_improve_add: bool = False,
    max_entries: int = 20,
) -> tuple[dict[str, list[StateItem]], list[str], int]:
    note_text = note_path.read_text(encoding="utf-8", errors="ignore")
    sections = load_state(state_path)
    extracted = _extract_from_note(note_text)

    for sec in _FROM_NOTE_MERGE_TARGETS:
        new_items: list[StateItem] = []
        for text in extracted.get(sec, []):
            try:
                new_items.append(StateItem.from_text(text))
            except ValueError:
                continue
        merged = deduplicate(new_items + sections.get(sec, []))
        sections[sec] = enforce_cap(merged, _FROM_NOTE_CAP_BY_SECTION[sec])

    sections[STATE_SHORT_KEYS["improvements"]] = enforce_cap(
        deduplicate(sections.get(STATE_SHORT_KEYS["improvements"], [])),
        _FROM_NOTE_CAP_BY_SECTION[STATE_SHORT_KEYS["improvements"]],
    )

    # Auto-improve: analyze signals
    if not no_auto_improve:
        index_path = _resolve_index_path_for_note(note_path, state_path)
        auto_items = _auto_improve_from_signals(
            index_path,
            sections,
            note_path=note_path,
        )
        if auto_items:
            if auto_improve_add:
                # Explicitly requested: add to backlog
                merged = deduplicate(
                    auto_items + sections.get(STATE_SHORT_KEYS["improvements"], [])
                )
                sections[STATE_SHORT_KEYS["improvements"]] = enforce_cap(
                    merged, _FROM_NOTE_CAP_BY_SECTION[STATE_SHORT_KEYS["improvements"]]
                )
                print(
                    f"Auto-improve: {len(auto_items)} candidate(s) added to improvement backlog",
                    file=sys.stderr,
                )
            else:
                # Default: report candidates without adding
                print(
                    f"Auto-improve: {len(auto_items)} candidate(s) detected "
                    "(use --auto-improve-add to add):",
                    file=sys.stderr,
                )
                for item in auto_items:
                    print(f"  - {item.text}", file=sys.stderr)

    _auto_prune(sections, max_entries=max_entries)
    save_state(state_path, sections)

    stale_count = sum(
        1 for sec in SECTION_ORDER for item in sections.get(sec, []) if is_stale(item, 7)
    )
    updated_sections = list(extracted.keys())
    if STATE_SHORT_KEYS["improvements"] not in updated_sections:
        updated_sections.append(STATE_SHORT_KEYS["improvements"])
    return sections, updated_sections, stale_count


def cmd_from_note(
    state_path: Path,
    note_path: Path,
    no_auto_improve: bool = False,
    auto_improve_add: bool = False,
    max_entries: int = 20,
) -> int:
    if not note_path.exists():
        print(f"Note not found: {note_path}", file=sys.stderr)
        return 2

    try:
        _validate_non_negative("max-entries", max_entries)
        _, _, stale_count = _merge_from_note(
            state_path=state_path,
            note_path=note_path,
            no_auto_improve=no_auto_improve,
            auto_improve_add=auto_improve_add,
            max_entries=max_entries,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"Failed to read note: {exc}", file=sys.stderr)
        return 2

    if stale_count > 0:
        print(f"Warning: {stale_count} stale items found (7+ days old)", file=sys.stderr)

    print(str(state_path))
    return 0


def auto_restore(
    *,
    memory_dir: Path,
    agent_id: str | None = None,
    relay_session_id: str | None = None,
    max_evidence_notes: int = 3,
    max_lines: int = 6,
    include_project_state: bool = True,
    include_agent_state: bool = True,
) -> dict[str, Any]:
    from agentic_memory.core import evidence, search
    from agentic_memory.core.scorer import IndexEntry

    project_state_path = memory_dir / "_state.md"
    project_sections = load_state(project_state_path)

    warnings: list[str] = []
    agent_sections: dict[str, list[StateItem]] | None = None
    resolved_agent_state_path: Path | None = None

    if include_agent_state:
        if agent_id is None:
            warnings.append("include_agent_state=true requires agent_id.")
        else:
            resolved_agent_state_path = resolve_agent_state_path(
                memory_dir,
                agent_id,
                relay_session_id,
                for_write=False,
            )
            ensure_state_file(resolved_agent_state_path)
            agent_sections = load_state(resolved_agent_state_path)

    task_ids = extract_task_ids_from_focus(project_sections)
    if agent_sections is not None:
        for task_id in extract_task_ids_from_focus(agent_sections):
            if task_id not in task_ids:
                task_ids.append(task_id)

    active_tasks: list[dict[str, object]] = []
    referenced_paths: set[str] = set()

    for task_id in task_ids:
        try:
            search_result = search.search(
                query=task_id,
                memory_dir=memory_dir,
                task_id=task_id,
                agent_id=agent_id,
                relay_session_id=relay_session_id,
                top=max_evidence_notes,
                engine="auto",
            )
        except Exception as exc:
            warnings.append(f"{task_id}: search failed ({exc})")
            continue

        rows = search_result.get("results", [])
        resolved_paths: list[Path] = []
        related_notes: list[str] = []

        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, tuple) or len(row) < 2:
                    continue
                maybe_entry = row[1]
                if not isinstance(maybe_entry, IndexEntry):
                    continue
                note_path = _resolve_note_path_for_evidence(maybe_entry.path, memory_dir)
                if note_path in resolved_paths:
                    continue
                resolved_paths.append(note_path)
                related_notes.append(maybe_entry.path)
                referenced_paths.add(maybe_entry.path)
                if len(resolved_paths) >= max_evidence_notes:
                    break

        if not resolved_paths:
            warnings.append(f"{task_id}: no related notes found.")
            continue

        evidence_pack = ""
        try:
            evidence_pack = evidence.generate_evidence_pack(
                query=task_id,
                paths=resolved_paths,
                max_lines=max_lines,
            )
        except Exception as exc:
            warnings.append(f"{task_id}: evidence generation failed ({exc})")

        active_tasks.append(
            {
                "task_id": task_id,
                "related_notes": related_notes,
                "evidence_pack": evidence_pack,
            }
        )

    return {
        "agent_id": agent_id,
        "relay_session_id": relay_session_id,
        "project_state": (
            state_sections_to_rendered(project_sections)
            if include_project_state
            else None
        ),
        "agent_state": (
            state_sections_to_rendered(agent_sections)
            if (include_agent_state and agent_sections is not None)
            else None
        ),
        "agent_state_path": str(resolved_agent_state_path) if resolved_agent_state_path else None,
        "active_tasks": active_tasks,
        "restored_task_count": len(active_tasks),
        "total_notes_referenced": len(referenced_paths),
        "warnings": warnings,
        "restored_at": _dt.datetime.now().isoformat(timespec="seconds"),
    }
