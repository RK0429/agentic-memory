"""Shared tokenization utilities for agentic-memory retrieval.

This module centralizes ASCII/CJK tokenization logic that was previously
duplicated in multiple scripts. It provides a single ``tokenize()`` entry point
with optional Sudachi-based Japanese morphological analysis.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

CJK_CHUNK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]+")
ASCII_TOKEN_RE = re.compile(r"[A-Za-z0-9_\./\-]+")

_SUDACHI_AVAILABLE: bool | None = None
_SUDACHI_TOKENIZER: Any | None = None
_SUDACHI_MODE_C: Any | None = None


def _normalize_text(text: str) -> str:
    return unicodedata.normalize("NFKC", text or "")


def normalize_text(text: str) -> str:
    """NFKC-normalize text. Public API for cross-module use."""
    return _normalize_text(text)


def _split_camel(token: str) -> list[str]:
    return re.findall(r"[A-Z]+(?=[A-Z][a-z]|[0-9]|$)|[A-Z]?[a-z]+|[0-9]+", token)


def is_sudachi_available() -> bool:
    """Return whether ``sudachipy`` and ``sudachidict_core`` are importable."""
    global _SUDACHI_AVAILABLE
    if _SUDACHI_AVAILABLE is not None:
        return _SUDACHI_AVAILABLE

    try:
        import sudachidict_core  # noqa: F401
        from sudachipy import dictionary  # noqa: F401
        from sudachipy import tokenizer as sudachi_tokenizer  # noqa: F401
    except Exception:
        _SUDACHI_AVAILABLE = False
    else:
        _SUDACHI_AVAILABLE = True

    return _SUDACHI_AVAILABLE


def _init_sudachi() -> tuple[Any, Any] | None:
    global _SUDACHI_AVAILABLE, _SUDACHI_MODE_C, _SUDACHI_TOKENIZER
    if _SUDACHI_TOKENIZER is not None and _SUDACHI_MODE_C is not None:
        return _SUDACHI_TOKENIZER, _SUDACHI_MODE_C

    if not is_sudachi_available():
        return None

    try:
        from sudachipy import dictionary
        from sudachipy import tokenizer as sudachi_tokenizer

        _SUDACHI_TOKENIZER = dictionary.Dictionary().create()
        _SUDACHI_MODE_C = sudachi_tokenizer.Tokenizer.SplitMode.C
    except Exception:
        _SUDACHI_AVAILABLE = False
        _SUDACHI_TOKENIZER = None
        _SUDACHI_MODE_C = None
        return None

    return _SUDACHI_TOKENIZER, _SUDACHI_MODE_C


def _get_tokenizer_backend(config: dict) -> str:
    backend = "auto"
    tokenizer_cfg = config.get("tokenizer", {}) if isinstance(config, dict) else {}
    if isinstance(tokenizer_cfg, dict):
        raw_backend = tokenizer_cfg.get("backend", "auto")
        if isinstance(raw_backend, str):
            backend = raw_backend.strip().lower() or "auto"

    if backend not in {"sudachi", "ngram", "auto"}:
        backend = "auto"

    if backend == "auto":
        return "sudachi" if is_sudachi_available() else "ngram"

    if backend == "sudachi" and not is_sudachi_available():
        return "ngram"

    return backend


def _cjk_ngrams(
    text: str, min_n: int = 2, max_n: int = 3, max_terms: int = 120
) -> list[str]:
    out: list[str] = []
    for match in CJK_CHUNK_RE.finditer(text):
        chunk = match.group(0)
        if not chunk:
            continue
        if len(chunk) >= 2:
            out.append(chunk)
        for n_size in range(min_n, max_n + 1):
            if len(chunk) < n_size:
                continue
            for index in range(len(chunk) - n_size + 1):
                out.append(chunk[index : index + n_size])
                if len(out) >= max_terms:
                    return out
    return out


def _sudachi_tokenize(text: str) -> list[str]:
    backend = _init_sudachi()
    if backend is None:
        return _cjk_ngrams(text)

    tokenizer, mode_c = backend
    out: list[str] = []
    for match in CJK_CHUNK_RE.finditer(text):
        chunk = match.group(0)
        if not chunk:
            continue
        try:
            morphemes = tokenizer.tokenize(chunk, mode_c)
        except Exception:
            out.extend(_cjk_ngrams(chunk))
            continue

        for morpheme in morphemes:
            surface = _normalize_text(morpheme.surface()).strip()
            normalized = _normalize_text(morpheme.normalized_form()).strip()
            pos = morpheme.part_of_speech() or ()
            pos_head = pos[0] if pos else ""
            if pos_head in {"助詞", "補助記号"} and len(surface) <= 1:
                continue
            if surface:
                out.append(surface)
            if normalized:
                out.append(normalized)
    return out


def _split_ascii(text: str) -> list[str]:
    raw_tokens = re.split(r"[^A-Za-z0-9_\-/\.]+", text)
    out: list[str] = []
    for token in raw_tokens:
        token = token.strip()
        if not token:
            continue
        out.append(token)
        if "/" in token:
            out.extend([part for part in token.split("/") if part])
        if "\\" in token:
            out.extend([part for part in token.split("\\") if part])
        if "_" in token:
            out.extend([part for part in token.split("_") if part])
        if "-" in token:
            out.extend([part for part in token.split("-") if part])
        if re.search(r"[A-Z][a-z]", token):
            out.extend(_split_camel(token))
    normalized: list[str] = []
    for token in out:
        token = _normalize_text(token).strip()
        if token:
            normalized.append(token)
    return normalized


def tokenize(
    text: str,
    *,
    config: dict | None = None,
    stopwords: set[str] | None = None,
    min_length: int = 0,
) -> list[str]:
    """Tokenize text for retrieval with configurable CJK backend selection.

    Behavior:
    - NFKC-normalize input text.
    - Extract ASCII-oriented tokens (path/snake/kebab/camel splits).
    - Extract CJK tokens via Sudachi or n-gram backend.
    - Apply optional stopword and minimum-length filters.
    - Preserve token order and duplicates for downstream term-frequency counting.
    """
    text_norm = _normalize_text(text)
    tokens: list[str] = []
    tokens.extend(_split_ascii(text_norm))

    backend = _get_tokenizer_backend(config or {})
    if backend == "sudachi":
        tokens.extend(_sudachi_tokenize(text_norm))
    else:
        tokens.extend(_cjk_ngrams(text_norm))

    normalized_stopwords: set[str] | None = None
    if stopwords is not None:
        normalized_stopwords = {
            _normalize_text(word).strip().casefold()
            for word in stopwords
            if isinstance(word, str) and _normalize_text(word).strip()
        }

    out: list[str] = []
    min_len = max(0, int(min_length))
    for token in tokens:
        token_norm = _normalize_text(token).strip()
        if not token_norm:
            continue
        if normalized_stopwords is not None and token_norm.casefold() in normalized_stopwords:
            continue
        if min_len > 0 and len(token_norm) < min_len:
            continue
        out.append(token_norm)
    return out
