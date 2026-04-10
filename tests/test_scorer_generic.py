from __future__ import annotations

from agentic_memory.core.query import parse_query
from agentic_memory.core.scorer import build_idf_cache, score_generic_entry


def test_score_generic_entry_scores_matching_document_higher() -> None:
    docs = [
        {
            "title": "Rust ownership rules",
            "content_preview": "borrow checker and ownership",
            "date": "2026-04-10",
        },
        {
            "title": "Python generators",
            "content_preview": "yield from examples",
            "date": "2026-04-10",
        },
    ]
    qterms = parse_query("rust ownership")
    idf_cache = build_idf_cache(qterms, docs)
    weights = {"title": 3.0, "content_preview": 1.5}

    rust_score, _ = score_generic_entry(
        docs[0],
        qterms,
        weights,
        idf_cache,
        prefer_recent=False,
        half_life_days=30.0,
        recency_boost_max=0.0,
    )
    python_score, _ = score_generic_entry(
        docs[1],
        qterms,
        weights,
        idf_cache,
        prefer_recent=False,
        half_life_days=30.0,
        recency_boost_max=0.0,
    )

    assert rust_score > python_score


def test_score_generic_entry_respects_must_and_exclude_terms() -> None:
    doc = {
        "title": "Rust ownership rules",
        "content_preview": "borrow checker",
        "date": "2026-04-10",
    }
    qterms = parse_query("+rust -python")
    idf_cache = build_idf_cache(qterms, [doc])

    score, detail = score_generic_entry(
        doc,
        qterms,
        {"title": 3.0, "content_preview": 1.0},
        idf_cache,
        prefer_recent=False,
        half_life_days=30.0,
        recency_boost_max=0.0,
    )

    assert score > 0
    assert detail == {}
