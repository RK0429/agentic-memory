"""
search.py — Memory search orchestration helper.

Design goals:
- Do NOT replace the agent's strategy. Provide evidence-based candidates quickly.
- Prefer index (`_index.jsonl`) when available. Fallback to full scan if needed.
- Explainability: optionally print score contributions per field/term.
- Configurable: loads `_rag_config.json` if present.
"""

from __future__ import annotations

import dataclasses
import datetime as _dt
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path

from agentic_memory.core import (
    dense,
    sections,
    tokenizer,
)
from agentic_memory.core import (
    index as memory_index,
)
from agentic_memory.core import (
    rerank as rerank_module,
)
from agentic_memory.core.fallback import fallback_search_files, rg_available, search_python
from agentic_memory.core.query import (
    QueryTerm,
    expand_terms,
    expand_with_feedback,
    expand_with_fuzzy,
    parse_query,
    pseudo_relevance_feedback,
)
from agentic_memory.core.scorer import (
    DELTA,
    IndexEntry,
    _compute_avg_field_lengths,
    build_idf_cache,
    load_index,
    score_entry,
)

CJK_CHUNK_RE = tokenizer.CJK_CHUNK_RE
TASK_ID_PATTERN = re.compile(r"^(TASK|GOAL)-\d{3,}$")
TASK_ID_EXTRACT_PATTERN = re.compile(r"\b((?:TASK|GOAL)-\d{3,})\b")
METADATA_FIELD_NAMES = {"task_id", "agent_id", "relay_session_id"}

DEFAULT_WEIGHTS = {
    "task_id": 8.0,
    "agent_id": 2.0,
    "relay_session_id": 1.5,
    "title": 6.0,
    "tags": 5.0,
    "keywords": 4.0,
    "auto_keywords": 3.5,
    "context": 3.0,
    "files": 6.0,
    "errors": 7.0,
    "skills": 4.0,
    "decisions": 3.0,
    "next": 2.5,
    "pitfalls": 2.5,
    "commands": 2.0,
    "summary": 2.0,
    "work_log_keywords": 2.5,
}
DEFAULT_RERANK_AUTO_THRESHOLD = 50
DEFAULT_HYBRID_RRF_K = 60
DEFAULT_HYBRID_DENSE_WEIGHT = 1.0


# ---------- Utilities ----------
def _now_local() -> _dt.datetime:
    return _dt.datetime.now()


_normalize_text = tokenizer._normalize_text


def _safe_lower(s: str) -> str:
    return _normalize_text(s).lower()


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = _normalize_text(value).strip()
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


def _normalize_metadata_filter(field: str, value: str | None) -> str | None:
    if field == "task_id":
        return _normalize_task_id(value)
    return _normalize_optional_text(value)


def _extract_query_metadata_filters(
    qterms: list[QueryTerm],
) -> tuple[list[QueryTerm], dict[str, str | None]]:
    remaining: list[QueryTerm] = []
    extracted: dict[str, str | None] = {
        "task_id": None,
        "agent_id": None,
        "relay_session_id": None,
    }

    for qt in qterms:
        if qt.field in METADATA_FIELD_NAMES and qt.term and not qt.exclude:
            extracted[qt.field] = _normalize_metadata_filter(qt.field, qt.term)
            continue
        remaining.append(qt)
    return remaining, extracted


def _resolve_metadata_filter(
    *,
    field: str,
    explicit: str | None,
    query_value: str | None,
    warnings: list[str],
) -> str | None:
    if explicit is not None:
        normalized = _normalize_metadata_filter(field, explicit)
        if normalized is None:
            raise ValueError(f"Invalid {field}: {explicit!r}")
        if query_value is not None and query_value != normalized:
            warnings.append(
                f"Query {field} filter is ignored because explicit {field} is provided."
            )
        return normalized
    return query_value


def _entry_matches_metadata(
    entry: IndexEntry,
    *,
    task_id: str | None,
    agent_id: str | None,
    relay_session_id: str | None,
) -> bool:
    if task_id is not None and _normalize_task_id(entry.task_id) != task_id:
        return False
    if agent_id is not None:
        entry_agent = _normalize_optional_text(entry.agent_id)
        if entry_agent is None or entry_agent.casefold() != agent_id.casefold():
            return False
    if relay_session_id is not None:
        entry_session = _normalize_optional_text(entry.relay_session_id)
        if entry_session is None or entry_session.casefold() != relay_session_id.casefold():
            return False
    return True


def _split_camel(s: str) -> list[str]:
    return tokenizer._split_camel(s)


def _extract_cjk_ngrams(s: str, min_n: int = 2, max_n: int = 3, max_terms: int = 120) -> list[str]:
    return tokenizer._cjk_ngrams(s, min_n=min_n, max_n=max_n, max_terms=max_terms)


def _tokenize_for_match(s: str) -> list[str]:
    return tokenizer.tokenize(s)


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


def _validate_config(config: dict) -> tuple[dict, list[str]]:
    """Validate critical config fields and apply safe defaults when invalid."""
    warnings: list[str] = []

    if not isinstance(config, dict):
        warnings.append("_rag_config.json root must be an object; defaults are used.")
        config = {}

    validated = dict(config)

    # weights: dict[str, float]
    merged_weights = dict(DEFAULT_WEIGHTS)
    raw_weights = config.get("weights")
    if raw_weights is None:
        pass
    elif not isinstance(raw_weights, dict):
        warnings.append("config.weights must be an object; default weights are used.")
    else:
        for k, v in raw_weights.items():
            if isinstance(k, str) and isinstance(v, (int, float)) and not isinstance(v, bool):
                merged_weights[k] = float(v)
            else:
                warnings.append(f"config.weights[{k!r}] must be a number; entry is ignored.")
    validated["weights"] = merged_weights

    # rerank.auto_threshold: int
    rerank_cfg_raw = config.get("rerank")
    rerank_cfg = dict(rerank_cfg_raw) if isinstance(rerank_cfg_raw, dict) else {}
    if rerank_cfg_raw is not None and not isinstance(rerank_cfg_raw, dict):
        warnings.append("config.rerank must be an object; defaults are used.")

    auto_threshold = _get_nested(
        config, ["rerank", "auto_threshold"], DEFAULT_RERANK_AUTO_THRESHOLD
    )
    if isinstance(auto_threshold, int) and not isinstance(auto_threshold, bool):
        rerank_cfg["auto_threshold"] = auto_threshold
    else:
        warnings.append("config.rerank.auto_threshold must be an integer; default 50 is used.")
        rerank_cfg["auto_threshold"] = DEFAULT_RERANK_AUTO_THRESHOLD
    validated["rerank"] = rerank_cfg

    # hybrid.rrf_k: int / hybrid.dense_weight: float
    hybrid_cfg_raw = config.get("hybrid")
    hybrid_cfg = dict(hybrid_cfg_raw) if isinstance(hybrid_cfg_raw, dict) else {}
    if hybrid_cfg_raw is not None and not isinstance(hybrid_cfg_raw, dict):
        warnings.append("config.hybrid must be an object; defaults are used.")

    rrf_k = _get_nested(config, ["hybrid", "rrf_k"], DEFAULT_HYBRID_RRF_K)
    if isinstance(rrf_k, int) and not isinstance(rrf_k, bool):
        hybrid_cfg["rrf_k"] = rrf_k
    else:
        warnings.append("config.hybrid.rrf_k must be an integer; default 60 is used.")
        hybrid_cfg["rrf_k"] = DEFAULT_HYBRID_RRF_K

    dense_weight = _get_nested(config, ["hybrid", "dense_weight"], DEFAULT_HYBRID_DENSE_WEIGHT)
    if isinstance(dense_weight, (int, float)) and not isinstance(dense_weight, bool):
        hybrid_cfg["dense_weight"] = float(dense_weight)
    else:
        warnings.append("config.hybrid.dense_weight must be a float; default 1.0 is used.")
        hybrid_cfg["dense_weight"] = DEFAULT_HYBRID_DENSE_WEIGHT
    validated["hybrid"] = hybrid_cfg

    return validated, warnings


def _load_config(path: Path) -> tuple[dict, list[str]]:
    warnings: list[str] = []
    raw: dict = {}

    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            raw = loaded if isinstance(loaded, dict) else {}
            if not isinstance(loaded, dict):
                warnings.append("_rag_config.json must contain an object; defaults are used.")
        except Exception as exc:
            warnings.append(f"Failed to parse _rag_config.json: {exc}")

    validated, v_warnings = _validate_config(raw)
    warnings.extend(v_warnings)

    for msg in warnings:
        print(f"[dn_search] Warning: {msg}", file=sys.stderr)

    return validated, warnings


# ---------- Recall-feedback / vocab helpers ----------
def _latest_note_path(memory_dir: Path) -> Path | None:
    if not memory_dir.exists():
        return None
    latest: tuple[float, Path] | None = None
    for p in memory_dir.rglob("*.md"):
        if not p.is_file() or p.name.startswith("_"):
            continue
        try:
            ts = p.stat().st_mtime
        except OSError:
            continue
        if latest is None or ts > latest[0]:
            latest = (ts, p)
    return latest[1] if latest else None


def _extract_recall_feedback_terms(note_path: Path, max_terms: int = 30) -> list[str]:
    try:
        lines = note_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return []

    in_feedback = False
    recall_feedback_alias = sections.NOTE_SECTION_ALIASES.get(
        "想起フィードバック（任意）",
        "Recall feedback (optional)",
    )
    recall_feedback_en_prefix = recall_feedback_alias.lower().split("(", 1)[0].strip()
    raw_values: list[str] = []

    for ln in lines:
        heading = re.match(r"^##\s+(.*)\s*$", ln)
        if heading:
            sec = heading.group(1).strip().lower()
            if sec.startswith(recall_feedback_en_prefix) or sec.startswith("想起フィードバック"):
                in_feedback = True
                continue
            if in_feedback:
                break
        if not in_feedback:
            continue

        m = re.match(r"^\s*-\s*([^:]+):\s*(.*)\s*$", ln)
        if not m:
            continue
        label = m.group(1).strip().lower()
        value = m.group(2).strip()
        if not value:
            continue
        if ("useful notes" in label) or ("missed notes" in label):
            raw_values.append(value)

    extracted: list[str] = []
    for value in raw_values:
        parts = re.split(r"[,\u3001\uFF0C;；|]+", value)
        for part in parts:
            part = _normalize_text(part).strip("`'\" \t")
            if not part:
                continue
            if " " in part and len(part) <= 80:
                extracted.append(part)
            extracted.extend(_tokenize_for_match(part))

    return _dedupe_keep_order(extracted)[:max_terms]


def _load_vocab(memory_dir: Path) -> set:
    """Load vocabulary from _vocab.json for fuzzy matching."""
    vocab_path = memory_dir / "_vocab.json"
    if not vocab_path.exists():
        return set()
    try:
        data = json.loads(vocab_path.read_text(encoding="utf-8"))
        return set(data.get("vocab") or [])
    except Exception:
        return set()


# ---------- Snippet extraction ----------
def extract_snippets(path: Path, query_terms: list[QueryTerm], top_snippets: int) -> list[str]:
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return []

    positives = [qt.term for qt in query_terms if qt.term and not qt.exclude]
    if not positives:
        return [f"L{i + 1}: {lines[i]}" for i in range(min(top_snippets, len(lines)))]

    positives = sorted(set(positives), key=lambda s: (-len(s), s))
    pats = [re.escape(p) for p in positives if p.strip()]
    if not pats:
        return []

    rx = re.compile("|".join(pats), re.IGNORECASE)

    hits = []
    for i, ln in enumerate(lines, start=1):
        if rx.search(ln):
            hits.append(f"L{i}: {ln.strip()}")
            if len(hits) >= top_snippets:
                break
    return hits


# ---------- Fallback adaptation ----------
def _ranked_to_results(
    ranked: list[tuple[str, int]], top: int, explain: bool
) -> list[tuple[float, IndexEntry, dict]]:
    out: list[tuple[float, IndexEntry, dict]] = []
    for p, hitcount in ranked[:top]:
        e = IndexEntry(path=p, title="", date="", time="")
        detail = {"hitcount": hitcount} if explain else {}
        out.append((float(hitcount), e, detail))
    return out


def _search_with_engine(
    engine: str,
    query_terms: list[QueryTerm],
    memory_dir: Path,
    top: int,
    explain: bool,
    has_rg: bool,
) -> list[tuple[float, IndexEntry, dict]]:
    if engine == "rg":
        ranked = fallback_search_files(query_terms, memory_dir)
        return _ranked_to_results(ranked, top, explain)

    if engine != "python":
        return []

    if has_rg:
        ranked = fallback_search_files(query_terms, memory_dir)
    else:
        ranked = search_python(query_terms, memory_dir)
    return _ranked_to_results(ranked, top, explain)


# ---------- Index staleness ----------
def _latest_note_mtime(memory_dir: Path) -> float | None:
    if not memory_dir.exists():
        return None
    latest = None
    for p in memory_dir.rglob("*.md"):
        if not p.is_file() or p.name.startswith("_"):
            continue
        try:
            ts = p.stat().st_mtime
        except OSError:
            continue
        latest = ts if latest is None else max(latest, ts)
    return latest


def _index_is_stale(index_path: Path, memory_dir: Path) -> bool:
    if not index_path.exists():
        return False
    latest_note = _latest_note_mtime(memory_dir)
    if latest_note is None:
        return False
    try:
        index_mtime = index_path.stat().st_mtime
    except OSError:
        return False
    return index_mtime < latest_note


def _sync_index(memory_dir: Path, index_path: Path) -> tuple[bool, str]:
    try:
        memory_index.rebuild_index(
            index_path=index_path,
            dailynote_dir=memory_dir,
        )
    except Exception as exc:
        return False, str(exc)
    return True, str(index_path)


def _weighted_rrf_merge(
    bm25_ranking: list[tuple[str, float]],
    dense_ranking: list[tuple[str, float]],
    k: int,
    dense_weight: float,
) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}

    for rank, (path, _) in enumerate(bm25_ranking, start=1):
        scores[path] = scores.get(path, 0.0) + (1.0 / (k + rank))

    for rank, (path, _) in enumerate(dense_ranking, start=1):
        scores[path] = scores.get(path, 0.0) + (dense_weight / (k + rank))

    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


def _format_score(value: float) -> str:
    return f"{value:.1f}"


def human_readable_explain(explain_data: dict) -> str:
    field_scores_raw = explain_data.get("field_scores", {})
    field_scores: list[tuple[str, float]] = []
    if isinstance(field_scores_raw, dict):
        for field, score in field_scores_raw.items():
            if isinstance(score, (int, float)) and not isinstance(score, bool) and score > 0:
                field_scores.append((str(field), float(score)))

    field_scores.sort(key=lambda item: (-item[1], item[0]))
    parts = [f"{field}一致: +{_format_score(score)}" for field, score in field_scores]

    recency_raw = explain_data.get("recency", {})
    recency_add = 0.0
    if isinstance(recency_raw, dict):
        add = recency_raw.get("add")
        if isinstance(add, (int, float)) and not isinstance(add, bool) and add > 0:
            recency_add = float(add)
            parts.append(f"鮮度補正: +{_format_score(recency_add)}")

    hitcount = explain_data.get("hitcount")
    if not parts and isinstance(hitcount, (int, float)) and not isinstance(hitcount, bool):
        hitcount_f = float(hitcount)
        parts.append(f"ヒット数: +{_format_score(hitcount_f)}")
        total = hitcount_f
    else:
        total_raw = explain_data.get("total")
        if isinstance(total_raw, (int, float)) and not isinstance(total_raw, bool):
            total = float(total_raw)
        else:
            total = sum(score for _, score in field_scores) + recency_add

    if not parts:
        reason = explain_data.get("filtered_by") or explain_data.get("excluded_by")
        if isinstance(reason, str) and reason.strip():
            return reason
        missing_must = explain_data.get("missing_must")
        if isinstance(missing_must, str) and missing_must.strip():
            return f"必須条件未一致: {missing_must}"
        return f"合計: {_format_score(total)}"

    return f"{', '.join(parts)} → 合計: {_format_score(total)}"


def _attach_explain_summaries(
    results: list[tuple[float, IndexEntry, dict]],
) -> list[tuple[float, IndexEntry, dict]]:
    summarized: list[tuple[float, IndexEntry, dict]] = []
    for score, entry, detail in results:
        entry.explain_summary = human_readable_explain(detail)
        summarized.append((score, entry, detail))
    return summarized


def _dedupe_query_terms(terms: list[QueryTerm]) -> list[QueryTerm]:
    deduped: list[QueryTerm] = []
    seen: set[tuple[object, ...]] = set()
    for qt in terms:
        key = (
            qt.raw,
            qt.term,
            qt.is_phrase,
            qt.must,
            qt.exclude,
            qt.field,
            qt.weight,
            qt.date_range,
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(qt)
    return deduped


# ---------- Orchestration ----------
def search(
    *,
    query: str,
    memory_dir: Path,
    task_id: str | None = None,
    agent_id: str | None = None,
    relay_session_id: str | None = None,
    engine: str = "auto",
    top: int | None = None,
    snippets: int | None = None,
    prefer_recent: bool = False,
    half_life_days: float | None = None,
    explain: bool = False,
    suggest: bool = False,
    no_expand: bool = False,
    no_feedback_expand: bool = False,
    no_fuzzy: bool = False,
    sync_stale_index: bool = False,
    use_rerank: bool = False,
    no_use_rerank: bool = False,
    prf: bool = False,
    no_prf: bool = False,
    default_date_range: int | None = None,
) -> dict:
    dn_dir = memory_dir
    index_path = dn_dir / "_index.jsonl"
    config_path = dn_dir / "_rag_config.json"

    config, config_warnings = _load_config(config_path)
    warnings: list[str] = list(config_warnings)

    weights = _get_nested(config, ["weights"], {}) or {}
    merged_weights = {
        **DEFAULT_WEIGHTS,
        **{
            k: float(v)
            for k, v in weights.items()
            if isinstance(v, (int, float)) and not isinstance(v, bool)
        },
    }

    prefer_recent_default = bool(_get_nested(config, ["search", "prefer_recent_default"], False))
    prefer_recent_effective = prefer_recent or prefer_recent_default

    half_life_days_effective = (
        half_life_days
        if half_life_days is not None
        else float(_get_nested(config, ["search", "recency_half_life_days"], 120))
    )
    recency_boost_max = float(_get_nested(config, ["search", "recency_boost_max"], 0.50))
    bm25_delta = float(_get_nested(config, ["search", "bm25_delta"], DELTA))

    top_n = top if top is not None else int(_get_nested(config, ["search", "top_default"], 10))
    snippets_n = (
        snippets
        if snippets is not None
        else int(_get_nested(config, ["search", "snippets_default"], 3))
    )

    qterms = parse_query(query)
    qterms, query_filters = _extract_query_metadata_filters(qterms)
    resolved_task_id = _resolve_metadata_filter(
        field="task_id",
        explicit=task_id,
        query_value=query_filters["task_id"],
        warnings=warnings,
    )
    resolved_agent_id = _resolve_metadata_filter(
        field="agent_id",
        explicit=agent_id,
        query_value=query_filters["agent_id"],
        warnings=warnings,
    )
    resolved_relay_session_id = _resolve_metadata_filter(
        field="relay_session_id",
        explicit=relay_session_id,
        query_value=query_filters["relay_session_id"],
        warnings=warnings,
    )

    # Apply default date range if no explicit date filter
    default_range = default_date_range
    if default_range is None:
        default_range = int(_get_nested(config, ["search", "default_date_range_days"], 0) or 0)
    if default_range > 0:
        has_date_filter = any(qt.date_range is not None for qt in qterms)
        if not has_date_filter:
            since = _now_local().date() - _dt.timedelta(days=default_range)
            qterms.append(
                QueryTerm(
                    raw=f"date:{since.isoformat()}..",
                    term="",
                    is_phrase=False,
                    must=False,
                    exclude=False,
                    field="date",
                    date_range=(since, None),
                )
            )

    # Query expansion
    expand_enabled_default = bool(_get_nested(config, ["query_expansion", "enabled_default"], True))
    expand_enabled = expand_enabled_default and (not no_expand)
    expanded = expand_terms(qterms, config, enable=expand_enabled)

    if not no_fuzzy:
        vocab = _load_vocab(dn_dir)
        if vocab:
            expanded = expand_with_fuzzy(expanded, vocab, config)

    feedback_expand_default = bool(
        _get_nested(config, ["query_expansion", "feedback_enabled_default"], True)
    )
    feedback_expand = feedback_expand_default and (not no_feedback_expand)
    feedback_decay = float(_get_nested(config, ["query_expansion", "feedback_decay"], 0.25))
    feedback_terms: list[str] = []
    feedback_note_path: Path | None = None
    if feedback_expand:
        feedback_note_path = _latest_note_path(dn_dir)
        if feedback_note_path is not None:
            feedback_terms = _extract_recall_feedback_terms(feedback_note_path)
            expanded = expand_with_feedback(expanded, feedback_terms, feedback_decay=feedback_decay)

    if suggest:
        suggestions = [
            qt.term for qt in expanded if qt.term and qt.term not in {t.term for t in qterms}
        ]
        uniq: list[str] = []
        seen: set[str] = set()
        for suggested_term in suggestions:
            key = suggested_term.lower()
            if key in seen:
                continue
            seen.add(key)
            if len(uniq) >= 20:
                break
            uniq.append(suggested_term)

        return {
            "engine": None,
            "query": query,
            "expanded": expanded,
            "expanded_terms": [qt.term for qt in expanded],
            "feedback_source_note": str(feedback_note_path)
            if feedback_terms and feedback_note_path
            else None,
            "feedback_terms_used": feedback_terms,
            "warnings": warnings,
            "results": [],
            "suggestions": uniq,
            "expand_enabled": expand_enabled,
            "feedback_expand": feedback_expand,
            "top": top_n,
            "snippets": snippets_n,
            "filters": {
                "task_id": resolved_task_id,
                "agent_id": resolved_agent_id,
                "relay_session_id": resolved_relay_session_id,
            },
        }

    has_metadata_filters = any(
        value is not None
        for value in (resolved_task_id, resolved_agent_id, resolved_relay_session_id)
    )

    # Engine selection
    entries: list[IndexEntry] = []
    used_engine: str
    has_rg = rg_available()
    index_exists = index_path.exists()
    stale_index = (
        _index_is_stale(index_path, dn_dir) if (engine == "auto" and index_exists) else False
    )

    if engine == "index" and index_exists:
        entries = load_index(index_path)
        used_engine = "index"
    elif engine == "index":
        used_engine = "rg" if has_rg else "python"
        warnings.append("Index file was not found. Falling back to non-index engine.")
    elif engine == "hybrid" and index_exists:
        entries = load_index(index_path)
        used_engine = "index"
    elif engine == "hybrid":
        used_engine = "rg" if has_rg else "python"
        warnings.append(
            "Index file was not found. Falling back to non-index engine (hybrid needs index)."
        )
    elif engine == "auto" and index_exists and not stale_index:
        entries = load_index(index_path)
        used_engine = "index"
    elif engine == "auto" and index_exists and stale_index:
        if sync_stale_index:
            ok, msg = _sync_index(dn_dir, index_path)
            if ok:
                entries = load_index(index_path)
                used_engine = "index"
                warnings.append(f"Index was stale and has been re-synced: {msg}")
            else:
                used_engine = "rg" if has_rg else "python"
                warnings.append(f"Index is stale and sync failed: {msg}")
                warnings.append("Falling back to non-index engine.")
        else:
            used_engine = "rg" if has_rg else "python"
            warnings.append(
                "Index is older than the latest note. Falling back to non-index engine."
            )
    elif engine in ("auto", "rg") and has_rg:
        used_engine = "rg"
    else:
        used_engine = "python"

    if has_metadata_filters:
        if index_exists:
            if used_engine != "index":
                warnings.append(
                    "Metadata filters require index metadata. Switching engine to index."
                )
                used_engine = "index"
            if not entries:
                entries = load_index(index_path)
        else:
            warnings.append("Metadata filters were requested but _index.jsonl was not found.")

    if used_engine == "index" and has_metadata_filters:
        entries = [
            entry
            for entry in entries
            if _entry_matches_metadata(
                entry,
                task_id=resolved_task_id,
                agent_id=resolved_agent_id,
                relay_session_id=resolved_relay_session_id,
            )
        ]

    results: list[tuple[float, IndexEntry, dict]] = []
    has_scoring_terms = any(qt.term and not qt.exclude for qt in expanded)

    if used_engine == "index" and not has_scoring_terms:
        results = [(1.0, entry, {}) for entry in entries[:top_n]]

    elif used_engine == "index" and engine == "hybrid":
        docs_field_texts = [entry.field_text() for entry in entries]
        idf_cache = build_idf_cache(expanded, docs_field_texts)
        avg_fl = _compute_avg_field_lengths(entries)

        bm25_results: list[tuple[float, IndexEntry, dict]] = []
        for entry, field_text in zip(entries, docs_field_texts, strict=False):
            score_value, detail = score_entry(
                entry,
                expanded,
                merged_weights,
                idf_cache,
                prefer_recent=prefer_recent_effective,
                half_life_days=half_life_days_effective,
                recency_boost_max=recency_boost_max,
                explain=explain,
                avg_field_lengths=avg_fl,
                delta=bm25_delta,
                precomputed_fields=field_text,
            )
            if score_value > 0:
                bm25_results.append((score_value, entry, detail))
        bm25_results.sort(key=lambda x: x[0], reverse=True)
        bm25_ranking = [(r[1].path, r[0]) for r in bm25_results]

        hybrid_rrf_k = int(_get_nested(config, ["hybrid", "rrf_k"], DEFAULT_HYBRID_RRF_K))
        hybrid_dense_weight = float(
            _get_nested(config, ["hybrid", "dense_weight"], DEFAULT_HYBRID_DENSE_WEIGHT)
        )

        dense_ranking = dense.search_dense(query, dn_dir, top_k=top_n * 2)
        if dense_ranking:
            merged = _weighted_rrf_merge(
                bm25_ranking,
                dense_ranking,
                k=hybrid_rrf_k,
                dense_weight=hybrid_dense_weight,
            )
            entry_map = {entry.path: entry for entry in entries}
            detail_map = {r[1].path: r[2] for r in bm25_results}
            for path, rrf_score in merged[:top_n]:
                merged_entry = entry_map.get(path)
                if merged_entry is None:
                    merged_entry = IndexEntry(path=path)
                detail_dict = detail_map.get(path, {})
                results.append((rrf_score, merged_entry, detail_dict))
        else:
            warnings.append("Dense search unavailable. Using BM25 only.")
            results = bm25_results[:top_n]

    elif used_engine == "index":
        docs_field_texts = [entry.field_text() for entry in entries]
        idf_cache = build_idf_cache(expanded, docs_field_texts)
        avg_fl = _compute_avg_field_lengths(entries)

        for entry, field_text in zip(entries, docs_field_texts, strict=False):
            score_value, detail = score_entry(
                entry,
                expanded,
                merged_weights,
                idf_cache,
                prefer_recent=prefer_recent_effective,
                half_life_days=half_life_days_effective,
                recency_boost_max=recency_boost_max,
                explain=explain,
                avg_field_lengths=avg_fl,
                delta=bm25_delta,
                precomputed_fields=field_text,
            )
            if score_value > 0:
                results.append((score_value, entry, detail))
        results.sort(key=lambda x: x[0], reverse=True)

        if prf and not no_prf and results:
            prf_expanded = pseudo_relevance_feedback(results, expanded, idf_cache)
            if len(prf_expanded) > len(expanded):
                expanded = prf_expanded
                idf_cache = build_idf_cache(expanded, docs_field_texts)
                results = []
                for entry, field_text in zip(entries, docs_field_texts, strict=False):
                    score_value, detail = score_entry(
                        entry,
                        expanded,
                        merged_weights,
                        idf_cache,
                        prefer_recent=prefer_recent_effective,
                        half_life_days=half_life_days_effective,
                        recency_boost_max=recency_boost_max,
                        explain=explain,
                        avg_field_lengths=avg_fl,
                        delta=bm25_delta,
                        precomputed_fields=field_text,
                    )
                    if score_value > 0:
                        results.append((score_value, entry, detail))
                results.sort(key=lambda x: x[0], reverse=True)

        results = results[:top_n]

    elif has_metadata_filters and not index_exists:
        results = []
    else:
        results = _search_with_engine(used_engine, expanded, dn_dir, top_n, explain, has_rg)

    if (
        engine == "auto"
        and used_engine == "index"
        and not results
        and not has_metadata_filters
    ):
        fallback_engine = "rg" if has_rg else "python"
        warnings.append(f"Index returned 0 results. Retrying with {fallback_engine} engine.")
        used_engine = fallback_engine
        results = _search_with_engine(used_engine, expanded, dn_dir, top_n, explain, has_rg)

    # W38: rerank auto-enable based on index size
    rerank_auto_threshold = int(
        _get_nested(config, ["rerank", "auto_threshold"], DEFAULT_RERANK_AUTO_THRESHOLD)
    )
    rerank_auto_enabled = used_engine == "index" and len(entries) > rerank_auto_threshold
    rerank_enabled = (not no_use_rerank) and (use_rerank or rerank_auto_enabled)

    if rerank_auto_enabled and not use_rerank and not no_use_rerank:
        warnings.append(
            "Rerank auto-enabled: "
            f"index entries ({len(entries)}) exceed "
            f"rerank.auto_threshold ({rerank_auto_threshold})."
        )

    if rerank_enabled and results:
        results = rerank_module.rerank(query, results, top_n=top_n)

    if explain:
        results = _attach_explain_summaries(results)

    return {
        "engine": used_engine,
        "query": query,
        "expanded": expanded,
        "expanded_terms": [qt.term for qt in expanded],
        "feedback_source_note": str(feedback_note_path)
        if feedback_terms and feedback_note_path
        else None,
        "feedback_terms_used": feedback_terms,
        "warnings": warnings,
        "results": results,
        "suggestions": [],
        "expand_enabled": expand_enabled,
        "feedback_expand": feedback_expand,
        "top": top_n,
        "snippets": snippets_n,
        "rerank_enabled": rerank_enabled,
        "rerank_auto_enabled": rerank_auto_enabled,
        "filters": {
            "task_id": resolved_task_id,
            "agent_id": resolved_agent_id,
            "relay_session_id": resolved_relay_session_id,
        },
    }


def search_global(query: str, memory_dirs: list[Path], **kwargs) -> dict:
    combined_results: list[tuple[float, IndexEntry, dict]] = []
    combined_expanded: list[QueryTerm] = []
    combined_feedback_terms: list[str] = []
    combined_suggestions: list[str] = []
    warnings: list[str] = []
    feedback_sources: list[str] = []
    source_engines: dict[str, str | None] = {}
    top_n: int | None = None
    snippets_n: int | None = None
    filters: dict[str, str | None] = {}
    expand_enabled = False
    feedback_expand = False
    rerank_enabled = False
    rerank_auto_enabled = False

    for memory_dir in memory_dirs:
        payload = search(query=query, memory_dir=memory_dir, **kwargs)
        source_dir = str(memory_dir)
        source_engines[source_dir] = payload.get("engine")

        if top_n is None:
            top_n = int(payload.get("top", 10))
        if snippets_n is None:
            snippets_n = int(payload.get("snippets", 3))
        if not filters:
            payload_filters = payload.get("filters", {})
            if isinstance(payload_filters, dict):
                filters = {
                    "task_id": payload_filters.get("task_id"),
                    "agent_id": payload_filters.get("agent_id"),
                    "relay_session_id": payload_filters.get("relay_session_id"),
                }

        expand_enabled = expand_enabled or bool(payload.get("expand_enabled", False))
        feedback_expand = feedback_expand or bool(payload.get("feedback_expand", False))
        rerank_enabled = rerank_enabled or bool(payload.get("rerank_enabled", False))
        rerank_auto_enabled = rerank_auto_enabled or bool(payload.get("rerank_auto_enabled", False))

        combined_expanded.extend(payload.get("expanded", []))
        combined_feedback_terms.extend(payload.get("feedback_terms_used", []))
        combined_suggestions.extend(payload.get("suggestions", []))

        feedback_source = payload.get("feedback_source_note")
        if isinstance(feedback_source, str) and feedback_source:
            feedback_sources.append(feedback_source)

        for warning in payload.get("warnings", []):
            warnings.append(f"[{source_dir}] {warning}")

        for score, entry, detail in payload.get("results", []):
            combined_results.append(
                (score, dataclasses.replace(entry, source_dir=source_dir), detail)
            )

    combined_results.sort(key=lambda item: item[0], reverse=True)
    if top_n is not None:
        combined_results = combined_results[:top_n]

    return {
        "engine": "global",
        "query": query,
        "expanded": _dedupe_query_terms(combined_expanded),
        "expanded_terms": _dedupe_keep_order(
            [qt.term for qt in combined_expanded if isinstance(qt.term, str) and qt.term]
        ),
        "feedback_source_note": _dedupe_keep_order(feedback_sources),
        "feedback_terms_used": _dedupe_keep_order(combined_feedback_terms),
        "warnings": warnings,
        "results": combined_results,
        "suggestions": _dedupe_keep_order(combined_suggestions),
        "expand_enabled": expand_enabled,
        "feedback_expand": feedback_expand,
        "top": top_n if top_n is not None else kwargs.get("top", 10),
        "snippets": snippets_n if snippets_n is not None else kwargs.get("snippets", 3),
        "rerank_enabled": rerank_enabled,
        "rerank_auto_enabled": rerank_auto_enabled,
        "filters": filters,
        "source_engines": source_engines,
    }
