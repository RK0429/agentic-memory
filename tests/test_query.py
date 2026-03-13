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


def test_parse_metadata_field() -> None:
    terms = query.parse_query("task_id:TASK-001")
    assert terms[0].field == "task_id"
    assert terms[0].term == "TASK-001"


def test_parse_date_range() -> None:
    terms = query.parse_query("date:2026-01-01..2026-01-31")
    assert len(terms) == 1
    assert terms[0].field == "date"
    assert terms[0].date_range == (dt.date(2026, 1, 1), dt.date(2026, 1, 31))


def test_parse_field_alias_tag() -> None:
    """Singular alias 'tag' should resolve to 'tags'."""
    terms = query.parse_query("tag:usability")
    assert terms[0].field == "tags"
    assert terms[0].term == "usability"


def test_parse_field_alias_keyword() -> None:
    terms = query.parse_query("keyword:auth")
    assert terms[0].field == "keywords"
    assert terms[0].term == "auth"


def test_parse_field_alias_file() -> None:
    terms = query.parse_query("file:login.ts")
    assert terms[0].field == "files"
    assert terms[0].term == "login.ts"


def test_parse_field_unknown_not_resolved() -> None:
    """Unknown field prefix should be treated as a regular term."""
    terms = query.parse_query("unknown:value")
    assert terms[0].field is None
    assert terms[0].term == "unknown:value"


def test_expand_terms_no_cjk_expand() -> None:
    """no_cjk_expand=True should suppress CJK n-gram fragments."""
    terms = query.parse_query("検索テスト")
    cfg = {"query_expansion": {"decay": 0.4}}
    expanded = query.expand_terms(
        terms,
        cfg,
        enable=True,
        no_cjk_expand=True,
    )
    original = "検索テスト"
    cjk_fragments = [
        qt for qt in expanded if len(qt.term) < len(original) and not qt.term.isascii()
    ]
    assert len(cjk_fragments) == 0, f"Unexpected CJK fragments: {[qt.term for qt in cjk_fragments]}"


def test_expand_terms_cjk_expand_default() -> None:
    """Default behavior should include CJK n-gram fragments."""
    terms = query.parse_query("検索テスト")
    cfg = {"query_expansion": {"decay": 0.4}}
    expanded = query.expand_terms(
        terms,
        cfg,
        enable=True,
        no_cjk_expand=False,
    )
    original = "検索テスト"
    cjk_fragments = [
        qt for qt in expanded if len(qt.term) < len(original) and not qt.term.isascii()
    ]
    assert len(cjk_fragments) > 0


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
