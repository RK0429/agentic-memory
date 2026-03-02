"""Dense retrieval helpers for agentic-memory search."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

MODEL_NAME = "cl-nagoya/ruri-v3-70m"
DENSE_FILE_NAME = "_dense.npy"
DENSE_PATHS_FILE_NAME = "_dense_paths.json"
QUERY_PREFIX = "検索クエリ: "
EMBED_DIM = 384

_DENSE_AVAILABLE: bool | None = None
_MODEL: Any | None = None
_MODEL_NAME: str | None = None


def is_dense_available() -> bool:
    """Return True when optional dense-retrieval dependencies are available."""
    global _DENSE_AVAILABLE
    if _DENSE_AVAILABLE is not None:
        return _DENSE_AVAILABLE

    try:
        import numpy as _np  # noqa: F401
        from sentence_transformers import SentenceTransformer as _SentenceTransformer  # noqa: F401
    except Exception:
        _DENSE_AVAILABLE = False
    else:
        _DENSE_AVAILABLE = True

    return _DENSE_AVAILABLE


def _get_model(model_name: str = "cl-nagoya/ruri-v3-70m"):
    """Lazy-load and cache a SentenceTransformer model."""
    global _MODEL
    global _MODEL_NAME

    if not is_dense_available():
        return None

    if _MODEL is not None and model_name == _MODEL_NAME:
        return _MODEL

    try:
        from sentence_transformers import SentenceTransformer

        _MODEL = SentenceTransformer(model_name)
        _MODEL_NAME = model_name
    except Exception as exc:
        print(f"[dn_dense] Failed to load model '{model_name}': {exc}", file=sys.stderr)
        _MODEL = None
        _MODEL_NAME = None
        return None

    return _MODEL


def _stringify_join(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return " ".join(str(v).strip() for v in value if str(v).strip())
    return str(value).strip()


def _flatten_value(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, dict):
        dict_out: list[str] = []
        for v in value.values():
            dict_out.extend(_flatten_value(v))
        return dict_out
    if isinstance(value, list):
        list_out: list[str] = []
        for item in value:
            list_out.extend(_flatten_value(item))
        return list_out
    s = str(value).strip()
    return [s] if s else []


def _entry_to_text(entry: dict) -> str:
    """Build embedding text from index entry fields (all sections except metadata)."""
    excluded = {"path", "date", "time", "indexed_at"}
    priority_order = [
        "title",
        "summary",
        "context",
        "tags",
        "keywords",
        "auto_keywords",
        "work_log_keywords",
        "files",
        "errors",
        "skills",
        "decisions",
        "actions",
        "next",
        "next_actions",
        "pitfalls",
        "plan",
        "plan_keywords",
        "tests",
        "test_names",
        "commands",
    ]

    parts: list[str] = []
    seen = set()
    for key in priority_order:
        if key in excluded:
            continue
        if key in entry:
            parts.extend(_flatten_value(entry.get(key)))
            seen.add(key)

    for key, value in entry.items():
        if key in excluded or key in seen:
            continue
        parts.extend(_flatten_value(value))

    merged = " ".join(p for p in parts if p)
    merged = " ".join(merged.split())
    return merged[:4096]


def build_embeddings(entries: list[dict], index_dir: Path) -> bool:
    """Build and persist dense embeddings for index entries."""
    if not is_dense_available():
        print("[dn_dense] Dense dependencies are unavailable.", file=sys.stderr)
        return False

    model = _get_model()
    if model is None:
        return False

    try:
        import numpy as np
    except Exception:
        return False

    try:
        index_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"[dn_dense] Failed to create index directory: {exc}", file=sys.stderr)
        return False

    paths: list[str] = []
    texts: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        paths.append(str(entry.get("path", "")))
        texts.append(_entry_to_text(entry))

    print(f"[dn_dense] Building embeddings for {len(texts)} entries...", file=sys.stderr)

    try:
        if texts:
            vectors = model.encode(
                texts,
                convert_to_numpy=True,
                show_progress_bar=False,
                normalize_embeddings=False,
            )
            dense = np.asarray(vectors, dtype=np.float32)
            if dense.ndim == 1:
                dense = dense.reshape(1, -1)
        else:
            dense = np.zeros((0, EMBED_DIM), dtype=np.float32)
    except Exception as exc:
        print(f"[dn_dense] Failed to encode entries: {exc}", file=sys.stderr)
        return False

    dense_path = index_dir / DENSE_FILE_NAME
    dense_paths_path = index_dir / DENSE_PATHS_FILE_NAME

    try:
        np.save(dense_path, dense.astype(np.float32, copy=False))
        with dense_paths_path.open("w", encoding="utf-8") as fh:
            json.dump(paths, fh, ensure_ascii=False)
    except OSError as exc:
        print(f"[dn_dense] Failed to save dense artifacts: {exc}", file=sys.stderr)
        return False

    print(f"[dn_dense] Saved dense vectors to {dense_path}", file=sys.stderr)
    print(f"[dn_dense] Saved dense paths to {dense_paths_path}", file=sys.stderr)
    return True


def _cosine_similarity(query_vec, doc_vecs):
    """Brute-force cosine similarity using numpy."""
    import numpy as np

    query_norm = query_vec / (np.linalg.norm(query_vec) + 1e-10)
    doc_norms = doc_vecs / (np.linalg.norm(doc_vecs, axis=1, keepdims=True) + 1e-10)
    return doc_norms @ query_norm


def search_dense(query: str, index_dir: Path, top_k: int = 20) -> list[tuple[str, float]]:
    """Search index entries with dense cosine similarity."""
    if not query.strip() or top_k <= 0:
        return []
    if not is_dense_available():
        return []

    model = _get_model()
    if model is None:
        return []

    try:
        import numpy as np
    except Exception:
        return []

    dense_path = index_dir / DENSE_FILE_NAME
    dense_paths_path = index_dir / DENSE_PATHS_FILE_NAME
    if not dense_path.exists() or not dense_paths_path.exists():
        return []

    try:
        doc_vecs = np.load(dense_path)
        with dense_paths_path.open("r", encoding="utf-8") as fh:
            paths = json.load(fh)
    except (OSError, ValueError, json.JSONDecodeError):
        return []

    if not isinstance(paths, list):
        return []

    query_text = query.strip()
    if not query_text.startswith(QUERY_PREFIX):
        query_text = f"{QUERY_PREFIX}{query_text}"

    try:
        query_vec = model.encode(
            [query_text],
            convert_to_numpy=True,
            show_progress_bar=False,
            normalize_embeddings=False,
        )
    except Exception:
        return []

    query_vec = np.asarray(query_vec, dtype=np.float32)
    if query_vec.ndim == 2:
        query_vec = query_vec[0]

    doc_vecs = np.asarray(doc_vecs, dtype=np.float32)
    if doc_vecs.ndim == 1:
        doc_vecs = doc_vecs.reshape(1, -1)

    usable = min(len(paths), int(doc_vecs.shape[0]))
    if usable <= 0:
        return []

    doc_vecs = doc_vecs[:usable]
    norm_paths = [str(p) for p in paths[:usable]]

    try:
        scores = _cosine_similarity(query_vec, doc_vecs)
    except Exception:
        return []

    order = np.argsort(scores)[::-1][:top_k]
    return [(norm_paths[int(i)], float(scores[int(i)])) for i in order]


def rrf_merge(
    bm25_ranking: list[tuple[str, float]],
    dense_ranking: list[tuple[str, float]],
    k: int = 60,
) -> list[tuple[str, float]]:
    """Merge sparse and dense rankings with Reciprocal Rank Fusion."""
    scores: dict[str, float] = {}

    for rank, (path, _) in enumerate(bm25_ranking, start=1):
        scores[path] = scores.get(path, 0.0) + (1.0 / (k + rank))

    for rank, (path, _) in enumerate(dense_ranking, start=1):
        scores[path] = scores.get(path, 0.0) + (1.0 / (k + rank))

    return sorted(scores.items(), key=lambda x: x[1], reverse=True)
