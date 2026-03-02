"""Index loading and scoring helpers for agentic-memory search."""
from __future__ import annotations

import dataclasses
import datetime as _dt
import json
import math
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from agentic_memory.core.query import QueryTerm
from agentic_memory.core import tokenizer

ASCII_WORD_CHARS = "A-Za-z0-9_"
ASCII_TOKEN_RE = re.compile(r"[A-Za-z0-9_\./\-]+")
K1 = 1.2
B = 0.75
DELTA = 1.0

_normalize_text = tokenizer._normalize_text


def _now_local() -> _dt.datetime:
    return _dt.datetime.now()


def _parse_date(s: str) -> Optional[_dt.date]:
    s = (s or "").strip()
    try:
        return _dt.date.fromisoformat(s)
    except Exception:
        return None


def _safe_lower(s: str) -> str:
    return _normalize_text(s).lower()


@dataclasses.dataclass
class IndexEntry:
    path: str
    title: str = ""
    date: str = ""
    time: str = ""
    context: str = ""
    tags: List[str] = dataclasses.field(default_factory=list)
    keywords: List[str] = dataclasses.field(default_factory=list)
    auto_keywords: List[str] = dataclasses.field(default_factory=list)
    files: List[str] = dataclasses.field(default_factory=list)
    errors: List[str] = dataclasses.field(default_factory=list)
    skills: List[str] = dataclasses.field(default_factory=list)
    decisions: str = ""
    next: str = ""
    pitfalls: str = ""
    commands: List[str] = dataclasses.field(default_factory=list)
    summary: str = ""
    work_log_keywords: List[str] = dataclasses.field(default_factory=list)

    def field_text(self) -> Dict[str, str]:
        return {
            "title": self.title or "",
            "context": self.context or "",
            "tags": " ".join(self.tags or []),
            "keywords": " ".join(self.keywords or []),
            "auto_keywords": " ".join(self.auto_keywords or []),
            "files": " ".join(self.files or []),
            "errors": " ".join(self.errors or []),
            "skills": " ".join(self.skills or []),
            "decisions": self.decisions or "",
            "next": self.next or "",
            "pitfalls": self.pitfalls or "",
            "commands": " ".join(self.commands or []),
            "summary": self.summary or "",
            "work_log_keywords": " ".join(self.work_log_keywords or []),
        }


def load_index(path: Path) -> List[IndexEntry]:
    entries: List[IndexEntry] = []
    if not path.exists():
        return entries

    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        entries.append(
            IndexEntry(
                path=str(obj.get("path", "")),
                title=str(obj.get("title", "") or ""),
                date=str(obj.get("date", "") or ""),
                time=str(obj.get("time", "") or ""),
                context=str(obj.get("context", "") or ""),
                tags=list(obj.get("tags") or []),
                keywords=list(obj.get("keywords") or []),
                auto_keywords=list(obj.get("auto_keywords") or []),
                files=list(obj.get("files") or []),
                errors=list(obj.get("errors") or []),
                skills=list(obj.get("skills") or []),
                decisions=str(obj.get("decisions", "") or ""),
                next=str(obj.get("next", "") or ""),
                pitfalls=str(obj.get("pitfalls", "") or ""),
                commands=list(obj.get("commands") or []),
                summary=str(obj.get("summary", "") or ""),
                work_log_keywords=list(obj.get("work_log_keywords") or []),
            )
        )
    return entries


def _build_doc_blobs(docs: List[Dict[str, str]]) -> List[str]:
    return [_safe_lower(" ".join(d.values())) for d in docs]


def _strict_term_match(haystack: str, needle: str, is_phrase: bool) -> bool:
    hs = _safe_lower(haystack)
    nd = _safe_lower(needle).strip()
    if not nd:
        return False
    if is_phrase or (" " in nd):
        return nd in hs
    if ASCII_TOKEN_RE.fullmatch(nd):
        pat = rf"(?<![{ASCII_WORD_CHARS}]){re.escape(nd)}(?![{ASCII_WORD_CHARS}])"
        return re.search(pat, hs) is not None
    return nd in hs


def build_idf_cache(qterms: List[QueryTerm], docs: List[Dict[str, str]]) -> Dict[str, float]:
    """Precompute IDF for query terms once per query."""
    term_flags: Dict[str, bool] = {}
    for qt in qterms:
        if not qt.term or qt.exclude:
            continue
        key = _safe_lower(qt.term)
        term_flags[key] = term_flags.get(key, False) or qt.is_phrase

    terms = sorted(term_flags.keys())
    if not term_flags:
        return {}

    blobs = _build_doc_blobs(docs)
    n_docs = len(blobs)
    if n_docs <= 0:
        return {t: 1.0 for t in terms}

    cache: Dict[str, float] = {}
    for t, is_phrase in term_flags.items():
        df = 0
        for blob in blobs:
            if _strict_term_match(blob, t, is_phrase=is_phrase):
                df += 1
        cache[t] = math.log((n_docs + 1) / (df + 1)) + 1.0
    return cache


def _count_matches(haystack: str, needle: str, is_phrase: bool) -> int:
    """Count occurrences of needle in haystack using word-boundary or substring matching."""
    hs = _safe_lower(haystack)
    nd = _safe_lower(needle).strip()
    if not nd:
        return 0
    if is_phrase or (" " in nd):
        return hs.count(nd)
    if ASCII_TOKEN_RE.fullmatch(nd):
        pat = rf"(?<![{ASCII_WORD_CHARS}]){re.escape(nd)}(?![{ASCII_WORD_CHARS}])"
        return len(re.findall(pat, hs))
    return hs.count(nd)


def _match_quality(haystack: str, needle: str, is_phrase: bool) -> float:
    """Return match quality: 1.0=whole word, 0.85=prefix, 0.80=suffix, 0.55=substring, 0.0=no match."""
    hs = _safe_lower(haystack)
    nd = _safe_lower(needle).strip()
    if not nd:
        return 0.0
    if is_phrase or (" " in nd):
        return 1.0 if nd in hs else 0.0
    if ASCII_TOKEN_RE.fullmatch(nd):
        pat = rf"(?<![{ASCII_WORD_CHARS}]){re.escape(nd)}(?![{ASCII_WORD_CHARS}])"
        if re.search(pat, hs):
            return 1.0
        prefix_pat = rf"(?<![{ASCII_WORD_CHARS}]){re.escape(nd)}"
        if re.search(prefix_pat, hs):
            return 0.85
        suffix_pat = rf"{re.escape(nd)}(?![{ASCII_WORD_CHARS}])"
        if re.search(suffix_pat, hs):
            return 0.80
    if nd in hs:
        return 0.55
    return 0.0


def _compute_avg_field_lengths(entries: List[IndexEntry]) -> Dict[str, float]:
    """Compute average field lengths (in whitespace-delimited tokens) across all entries."""
    if not entries:
        return {}
    sums: Dict[str, float] = {}
    for e in entries:
        for k, v in e.field_text().items():
            sums[k] = sums.get(k, 0.0) + len(v.split())
    return {k: v / len(entries) for k, v in sums.items()}


def score_entry(
    entry: IndexEntry,
    qterms: List[QueryTerm],
    weights: Dict[str, float],
    idf_cache: Dict[str, float],
    prefer_recent: bool,
    half_life_days: float,
    recency_boost_max: float,
    explain: bool = False,
    avg_field_lengths: Optional[Dict[str, float]] = None,
    delta: float = DELTA,
    precomputed_fields: Optional[Dict[str, str]] = None,
) -> Tuple[float, Dict]:
    fields = precomputed_fields if precomputed_fields is not None else entry.field_text()
    fields_l = {k: _safe_lower(v) for k, v in fields.items()}

    for qt in qterms:
        if qt.date_range is not None:
            d = _parse_date(entry.date)
            if d is None:
                return 0.0, {"filtered_by": "date_range (no date)"}
            lo, hi = qt.date_range
            if (lo and d < lo) or (hi and d > hi):
                return 0.0, {"filtered_by": f"date_range {qt.raw}"}

    for qt in qterms:
        if qt.exclude:
            target_fields = [qt.field] if qt.field else list(fields_l.keys())
            for f in target_fields:
                if _strict_term_match(fields_l.get(f, ""), qt.term, is_phrase=qt.is_phrase):
                    return 0.0, {"excluded_by": qt.raw}

    for qt in qterms:
        if qt.must:
            target_fields = [qt.field] if qt.field else list(fields_l.keys())
            ok = False
            for f in target_fields:
                if _strict_term_match(fields_l.get(f, ""), qt.term, is_phrase=qt.is_phrase):
                    ok = True
                    break
            if not ok:
                return 0.0, {"missing_must": qt.raw}

    total = 0.0
    details: Dict = {"terms": []} if explain else {}

    for qt in qterms:
        if qt.exclude or not qt.term:
            continue

        term_l = qt.term.lower()
        idf = idf_cache.get(term_l, 1.0)
        term_factor = 1.4 if qt.is_phrase else 1.0

        contribs = []
        target_fields = [qt.field] if qt.field else list(weights.keys())
        for f in target_fields:
            w = weights.get(f, 0.0)
            if w <= 0:
                continue
            hay = fields_l.get(f, "")
            quality = _match_quality(hay, term_l, is_phrase=qt.is_phrase)
            if quality <= 0:
                continue

            tf_raw = _count_matches(hay, term_l, is_phrase=qt.is_phrase)
            if tf_raw <= 0:
                continue

            norm = 1.0
            if avg_field_lengths is not None:
                field_len = len(hay.split()) if hay else 0
                avg_fl = avg_field_lengths.get(f, 1.0)
                norm = 1.0 - B + B * (field_len / max(avg_fl, 1.0))
            tf_bm25 = (tf_raw * (K1 + 1.0)) / (tf_raw + K1 * norm) + delta

            c = w * idf * tf_bm25 * term_factor * quality * qt.weight
            total += c
            if explain:
                contribs.append(
                    {
                        "field": f,
                        "add": round(c, 3),
                        "idf": round(idf, 3),
                        "tf": tf_raw,
                        "quality": quality,
                        "weight": qt.weight,
                    }
                )

        if explain:
            details["terms"].append({"term": qt.raw, "contribs": contribs, "term_factor": term_factor})

    if prefer_recent:
        d = _parse_date(entry.date)
        if d:
            age_days = max(0.0, (_now_local().date() - d).days)
            w = math.exp(-math.log(2) * age_days / max(1.0, half_life_days))
            total *= (1.0 + recency_boost_max * w)
            if explain:
                details["recency"] = {"age_days": age_days, "w": round(w, 3), "boost_max": recency_boost_max}

    return total, details


__all__ = [
    "IndexEntry",
    "load_index",
    "build_idf_cache",
    "score_entry",
    "_match_quality",
    "_compute_avg_field_lengths",
    "DELTA",
    "_strict_term_match",
]
