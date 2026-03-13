"""Query parsing and expansion helpers for agentic-memory search."""

from __future__ import annotations

import dataclasses
import datetime as _dt
import difflib
import shlex
from collections.abc import Sequence
from typing import TYPE_CHECKING

from agentic_memory.core import tokenizer

if TYPE_CHECKING:
    from agentic_memory.core.scorer import IndexEntry

_normalize_text = tokenizer._normalize_text


def _parse_date(s: str) -> _dt.date | None:
    s = (s or "").strip()
    try:
        return _dt.date.fromisoformat(s)
    except Exception:
        return None


def _safe_lower(s: str) -> str:
    return _normalize_text(s).lower()


def _tokenize_for_match(s: str, max_cjk_terms: int = 120) -> list[str]:
    return tokenizer.tokenize(s, max_cjk_terms=max_cjk_terms)


def _get_nested(d: dict, path: Sequence[str], default=None):
    cur = d
    for p in path:
        if not isinstance(cur, dict) or p not in cur:
            return default
        cur = cur[p]
    return cur


def _dedupe_keep_order(items: Sequence[str], casefold: bool = True) -> list[str]:
    out: list[str] = []
    seen = set()
    for item in items:
        norm = _normalize_text(item).strip()
        if not norm:
            continue
        key = norm.casefold() if casefold else norm
        if key in seen:
            continue
        seen.add(key)
        out.append(norm)
    return out


@dataclasses.dataclass
class QueryTerm:
    raw: str
    term: str
    is_phrase: bool = False
    must: bool = False
    exclude: bool = False
    field: str | None = None
    weight: float = 1.0
    date_range: tuple[_dt.date | None, _dt.date | None] | None = None


class QueryParseError(ValueError):
    """Raised when a query cannot be parsed."""


# Canonical field names accepted in field:term syntax.
_FIELD_NAMES = {
    "task_id",
    "agent_id",
    "relay_session_id",
    "title",
    "tags",
    "keywords",
    "auto_keywords",
    "context",
    "files",
    "errors",
    "skills",
    "decisions",
    "next",
    "pitfalls",
    "commands",
    "summary",
}

# Singular → plural aliases for convenience (e.g., tag:foo → tags:foo).
_FIELD_ALIASES: dict[str, str] = {
    "tag": "tags",
    "keyword": "keywords",
    "file": "files",
    "error": "errors",
    "skill": "skills",
    "decision": "decisions",
    "pitfall": "pitfalls",
    "command": "commands",
}


def parse_query(query: str) -> list[QueryTerm]:
    """
    Supports:
      - quoted phrases via shlex.split
      - +term (must)
      - -term (exclude)
      - field:term (restrict to a field; e.g., title:auth, files:login.ts)
        Singular aliases are accepted: tag:foo → tags:foo
    """
    try:
        tokens = shlex.split(query)
    except ValueError as exc:
        raise QueryParseError(str(exc)) from exc

    out: list[QueryTerm] = []
    for tok in tokens:
        must = tok.startswith("+")
        exclude = tok.startswith("-")
        t = tok[1:] if (must or exclude) else tok

        field = None
        date_range = None
        if ":" in t and not t.startswith("http"):
            maybe_field, rest = t.split(":", 1)
            if maybe_field == "date" and ".." in rest:
                lo_s, hi_s = rest.split("..", 1)
                lo = _parse_date(lo_s) if lo_s.strip() else None
                hi = _parse_date(hi_s) if hi_s.strip() else None
                if (not lo_s.strip() and not hi_s.strip()) or (lo is not None or hi is not None):
                    date_range = (lo, hi)
                    out.append(
                        QueryTerm(
                            raw=tok,
                            term="",
                            is_phrase=False,
                            must=False,
                            exclude=exclude,
                            field="date",
                            date_range=date_range,
                        )
                    )
                    continue
            else:
                resolved = _FIELD_ALIASES.get(maybe_field, maybe_field)
                if resolved in _FIELD_NAMES:
                    field, t = resolved, rest

        is_phrase = (" " in tok) or (" " in t)
        out.append(
            QueryTerm(raw=tok, term=t, is_phrase=is_phrase, must=must, exclude=exclude, field=field)
        )
    return out


def expand_terms(
    terms: list[QueryTerm],
    config: dict,
    enable: bool,
    no_cjk_expand: bool = False,
) -> list[QueryTerm]:
    """
    Optional helper: expands terms with simple heuristics + synonym map (config).
    This does NOT replace agent judgment; it's an optional assist.

    When ``no_cjk_expand`` is True, CJK n-gram expansion is suppressed to reduce
    context window consumption. Only ASCII-based tokenization is applied.
    """
    if not enable:
        return terms

    decay = float(_get_nested(config, ["query_expansion", "decay"], 0.4) or 0.4)
    syn_map = _get_nested(config, ["query_expansion", "synonyms"], {}) or {}
    expanded: list[QueryTerm] = []
    seen = set()

    def add(qt: QueryTerm) -> None:
        key = (qt.term, qt.must, qt.exclude, qt.field, qt.is_phrase)
        if key in seen:
            return
        seen.add(key)
        expanded.append(qt)

    for qt in terms:
        add(qt)

    for qt in terms:
        if qt.exclude or not qt.term:
            continue

        base = qt.term
        variants = {base, base.lower(), base.upper()}
        if "/" in base:
            variants.add(base.split("/")[-1])
        if "\\" in base:
            variants.add(base.split("\\")[-1])

        for tk in _tokenize_for_match(base, max_cjk_terms=20):
            if no_cjk_expand and not tk.isascii():
                continue
            variants.add(tk)
            variants.add(tk.lower())

        key = base.lower()
        if key in syn_map and isinstance(syn_map[key], list):
            for v in syn_map[key]:
                if isinstance(v, str) and v.strip():
                    variants.add(v.strip())

        for v in sorted(variants):
            if v == base:
                continue
            add(
                QueryTerm(
                    raw=v,
                    term=v,
                    is_phrase=(" " in v),
                    must=False,
                    exclude=False,
                    field=qt.field,
                    weight=decay,
                )
            )

    return expanded


def expand_with_fuzzy(
    terms: list[QueryTerm],
    vocab: set,
    config: dict,
    min_length: int = 4,
) -> list[QueryTerm]:
    """Expand query terms with fuzzy-matched vocabulary tokens using difflib."""
    if not vocab:
        return terms

    cutoff = float(_get_nested(config, ["query_expansion", "fuzzy_cutoff"], 0.75) or 0.75)
    decay = float(_get_nested(config, ["query_expansion", "fuzzy_decay"], 0.6) or 0.6)
    vocab_list = sorted(vocab)

    expanded = list(terms)
    seen = {
        (
            _safe_lower(qt.term),
            qt.must,
            qt.exclude,
            qt.field,
            qt.is_phrase,
        )
        for qt in expanded
    }

    for qt in terms:
        if qt.exclude or not qt.term or qt.date_range is not None:
            continue
        if len(qt.term) < min_length:
            continue

        matches = difflib.get_close_matches(qt.term, vocab_list, n=3, cutoff=cutoff)
        if not matches:
            matches = difflib.get_close_matches(qt.term.lower(), vocab_list, n=3, cutoff=cutoff)

        for m in matches:
            key = (_safe_lower(m), False, False, qt.field, (" " in m))
            if key in seen:
                continue
            seen.add(key)
            expanded.append(
                QueryTerm(
                    raw=f"fuzzy:{m}",
                    term=m,
                    is_phrase=(" " in m),
                    must=False,
                    exclude=False,
                    field=qt.field,
                    weight=decay,
                )
            )
    return expanded


def expand_with_feedback(
    terms: list[QueryTerm],
    feedback_terms: Sequence[str],
    feedback_decay: float,
    max_new_terms: int = 12,
) -> list[QueryTerm]:
    if not feedback_terms:
        return terms

    expanded = list(terms)
    seen = {
        (
            _safe_lower(qt.term),
            qt.must,
            qt.exclude,
            qt.field,
            qt.is_phrase,
        )
        for qt in expanded
    }

    added = 0
    for term in feedback_terms:
        t = _normalize_text(term).strip()
        if len(t) < 2:
            continue
        key = (_safe_lower(t), False, False, None, (" " in t))
        if key in seen:
            continue
        expanded.append(
            QueryTerm(
                raw=f"feedback:{t}",
                term=t,
                is_phrase=(" " in t),
                must=False,
                exclude=False,
                field=None,
                weight=feedback_decay,
            )
        )
        seen.add(key)
        added += 1
        if added >= max_new_terms:
            break
    return expanded


def pseudo_relevance_feedback(
    initial_results: list[tuple[float, IndexEntry, dict]],
    qterms: list[QueryTerm],
    idf_cache: dict[str, float],
    top_k: int = 3,
    top_m: int = 5,
    prf_weight: float = 0.35,
) -> list[QueryTerm]:
    """Extract high-IDF terms from top-K results and add them as expanded query terms."""
    if not initial_results:
        return qterms

    existing_terms = {_safe_lower(qt.term) for qt in qterms if qt.term}

    candidate_tokens: dict[str, float] = {}
    for _, entry, _ in initial_results[:top_k]:
        fields = entry.field_text()
        all_text = " ".join(fields.values())
        tokens = _tokenize_for_match(all_text)
        for tok in tokens:
            tok_lower = _safe_lower(tok)
            if not tok_lower or len(tok_lower) < 2:
                continue
            if tok_lower in existing_terms:
                continue
            idf = idf_cache.get(tok_lower, 1.0)
            if idf > candidate_tokens.get(tok_lower, 0.0):
                candidate_tokens[tok_lower] = idf

    ranked = sorted(candidate_tokens.items(), key=lambda x: x[1], reverse=True)
    prf_terms: list[QueryTerm] = []
    seen = set()
    for tok, _ in ranked:
        if tok in seen:
            continue
        seen.add(tok)
        prf_terms.append(
            QueryTerm(
                raw=f"prf:{tok}",
                term=tok,
                is_phrase=False,
                must=False,
                exclude=False,
                field=None,
                weight=prf_weight,
            )
        )
        if len(prf_terms) >= top_m:
            break

    return list(qterms) + prf_terms


__all__ = [
    "QueryTerm",
    "QueryParseError",
    "parse_query",
    "expand_terms",
    "expand_with_fuzzy",
    "expand_with_feedback",
    "pseudo_relevance_feedback",
]
