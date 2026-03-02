"""Cross-encoder reranking helpers for agentic-memory search results."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from typing import Any

MODEL_NAME = "hotchpotch/japanese-reranker-tiny-v2"

_RERANK_AVAILABLE: bool | None = None
_RERANKER: Any | None = None
_RERANK_MODEL_NAME: str | None = None


def is_rerank_available() -> bool:
    """Return True when optional reranking dependencies are available."""
    global _RERANK_AVAILABLE
    if _RERANK_AVAILABLE is not None:
        return _RERANK_AVAILABLE

    try:
        from sentence_transformers import CrossEncoder as _CrossEncoder  # noqa: F401
    except Exception as exc:
        print(f"[dn_rerank] sentence-transformers unavailable: {exc}", file=sys.stderr)
        _RERANK_AVAILABLE = False
    else:
        _RERANK_AVAILABLE = True

    return _RERANK_AVAILABLE


def _get_reranker(model_name: str = MODEL_NAME):
    """Lazy-load and cache the CrossEncoder model."""
    global _RERANKER
    global _RERANK_MODEL_NAME

    if not is_rerank_available():
        return None

    if _RERANKER is not None and model_name == _RERANK_MODEL_NAME:
        return _RERANKER

    try:
        from sentence_transformers import CrossEncoder

        _RERANKER = CrossEncoder(model_name)
        _RERANK_MODEL_NAME = model_name
    except Exception as exc:
        print(f"[dn_rerank] failed to load model '{model_name}': {exc}", file=sys.stderr)
        _RERANKER = None
        _RERANK_MODEL_NAME = None
        return None

    return _RERANKER


def _to_document_text(entry: object, doc_max_chars: int) -> str:
    """Build a reranking document string from an index entry-like object."""
    text = ""
    try:
        field_text = getattr(entry, "field_text", None)
        if callable(field_text):
            values = field_text()
            if isinstance(values, dict):
                text = " ".join(str(v).strip() for v in values.values() if str(v).strip())
    except Exception as exc:
        print(f"[dn_rerank] failed to build field text: {exc}", file=sys.stderr)
        text = ""

    if not text:
        try:
            text = str(entry).strip()
        except Exception:
            text = ""

    if doc_max_chars > 0:
        return text[:doc_max_chars]
    return text


def rerank[TEntry](
    query: str,
    candidates: Sequence[tuple[float, TEntry, dict[str, Any]]],
    top_n: int = 20,
    doc_max_chars: int = 2000,
) -> list[tuple[float, TEntry, dict[str, Any]]]:
    """Rerank search candidates with a CrossEncoder and return top results.

    Args:
        query: User query string.
        candidates: Search results in `(score, entry, detail_dict)` format.
        top_n: Number of reranked results to return.
        doc_max_chars: Maximum document characters used per candidate.

    Returns:
        Reranked results sorted by cross-encoder score (descending). If optional
        dependencies are unavailable, candidates are empty, or any error occurs,
        this function returns `candidates` unchanged.
    """
    candidate_list = list(candidates)
    if not candidate_list:
        return []

    if not is_rerank_available():
        return candidate_list

    if top_n <= 0:
        return []

    try:
        reranker = _get_reranker()
        if reranker is None:
            return candidate_list

        pairs: list[tuple[str, str]] = []
        for _, entry, _ in candidate_list:
            doc_text = _to_document_text(entry, doc_max_chars=doc_max_chars)
            pairs.append((query, doc_text))

        raw_scores = reranker.predict(pairs)
        scores = [float(score) for score in raw_scores]

        rescored: list[tuple[float, TEntry, dict[str, Any]]] = [
            (score, entry, detail)
            for score, (_, entry, detail) in zip(scores, candidate_list, strict=False)
        ]
        rescored.sort(key=lambda item: item[0], reverse=True)
        return rescored[:top_n]
    except Exception as exc:
        print(f"[dn_rerank] rerank failed, passthrough: {exc}", file=sys.stderr)
        return candidate_list
