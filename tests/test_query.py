from __future__ import annotations

import datetime as dt

from agentic_memory.core import query


def test_parse_simple() -> None:
    terms = query.parse_query("auth")
    assert len(terms) == 1
    assert terms[0].term == "auth"
    assert terms[0].must is False
    assert terms[0].exclude is False


def test_parse_phrase() -> None:
    terms = query.parse_query('"auth bug"')
    assert len(terms) == 1
    assert terms[0].term == "auth bug"
    assert terms[0].is_phrase is True


def test_parse_must() -> None:
    terms = query.parse_query("+auth")
    assert terms[0].must is True
    assert terms[0].term == "auth"


def test_parse_exclude() -> None:
    terms = query.parse_query("-legacy")
    assert terms[0].exclude is True
    assert terms[0].term == "legacy"


def test_parse_field() -> None:
    terms = query.parse_query("title:auth")
    assert terms[0].field == "title"
    assert terms[0].term == "auth"


def test_parse_date_range() -> None:
    terms = query.parse_query("date:2026-01-01..2026-01-31")
    assert len(terms) == 1
    assert terms[0].field == "date"
    assert terms[0].date_range == (dt.date(2026, 1, 1), dt.date(2026, 1, 31))


def test_expand_terms() -> None:
    terms = query.parse_query("auth")
    config = {
        "query_expansion": {
            "decay": 0.4,
            "synonyms": {
                "auth": ["authentication"],
            },
        }
    }

    expanded = query.expand_terms(terms, config, enable=True)

    assert any(term.term == "auth" and term.weight == 1.0 for term in expanded)
    assert any(term.term == "authentication" and term.weight == 0.4 for term in expanded)
