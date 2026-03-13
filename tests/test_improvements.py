"""Tests for v0.3.0 usability improvements (Bug1/2, H1-H3, M1-M3, L1-L3)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentic_memory.core import evidence, index, note, sections, state, tokenizer
from agentic_memory.core.query import expand_terms, parse_query
from agentic_memory.core.search import (
    COMPACT_EXCLUDE_FIELDS,
    search,
)

# ---------- Bug 1 / M4: Case-insensitive section lookup ----------


def test_get_section_case_insensitive_skill_feedback() -> None:
    """English template uses 'Skill Feedback' (capital F) but alias is 'Skill feedback'."""
    secs = {"Skill Feedback": ["- SIGFB: tool | friction | description"]}
    result = sections.get_section(secs, "スキルフィードバック")
    assert len(result) == 1
    assert "SIGFB" in result[0]


def test_get_section_exact_match_still_works() -> None:
    secs = {"スキルフィードバック": ["- SIGFB: tool | success | ok"]}
    result = sections.get_section(secs, "スキルフィードバック")
    assert len(result) == 1


def test_get_section_english_lowercase_alias() -> None:
    secs = {"Skill feedback": ["- line"]}
    result = sections.get_section(secs, "スキルフィードバック")
    assert len(result) == 1


def test_sigfb_status_english_template(tmp_memory_dir: Path) -> None:
    """sigfb_status should detect SIGFB entries in English template notes."""
    note_dir = tmp_memory_dir / "2026-03-13"
    note_dir.mkdir(parents=True, exist_ok=True)
    note_path = note_dir / "1200_en-test.md"
    note_path.write_text(
        "# English Test\n\n"
        "- Date: 2026-03-13\n\n"
        "## Goals\n\n- test\n\n"
        "## Skill Feedback\n\n"
        "- SIGFB: tool_a | friction | test description\n",
        encoding="utf-8",
    )
    entry = index.build_entry(note_path, max_summary_chars=280, dailynote_dir=tmp_memory_dir)
    assert entry["sigfb_status"] == "recorded"


# ---------- Bug 2 / L2: Template placeholder exclusion in errors ----------


def test_extract_errors_excludes_sigfb_skill() -> None:
    """SIGFB and SKILL should not be detected as error tokens."""
    md = "- SIGFB: none\n- SKILL: none\nActual error: ECONNRESET"
    errors = index.extract_errors(md)
    assert "SIGFB" not in errors
    assert "SKILL" not in errors
    assert "ECONNRESET" in errors


def test_extract_errors_keeps_real_errors() -> None:
    md = "ValueError raised due to HTTP 500"
    errors = index.extract_errors(md)
    assert "ValueError" in errors
    assert "HTTP 500" in errors


# ---------- H1: compact mode for memory_search ----------


def test_search_compact_flag(tmp_memory_dir: Path) -> None:
    result = search(
        query="test",
        memory_dir=tmp_memory_dir,
        engine="python",
        compact=True,
    )
    assert result["compact"] is True


def test_search_compact_false_by_default(tmp_memory_dir: Path) -> None:
    result = search(
        query="test",
        memory_dir=tmp_memory_dir,
        engine="python",
    )
    assert result["compact"] is False


def test_compact_exclude_fields_defined() -> None:
    expected = {
        "auto_keywords",
        "work_log_keywords",
        "plan_keywords",
        "errors",
        "skills",
        "commands",
        "test_names",
        "skill_feedback",
    }
    assert expected == COMPACT_EXCLUDE_FIELDS


# ---------- H2: Preset modes (tested at server layer via mode parameter) ----------


def test_search_mode_quick_sets_compact(tmp_memory_dir: Path) -> None:
    """mode='quick' should enable compact and disable explain."""
    from agentic_memory.server import memory_search

    raw = memory_search(query="test", mode="quick", memory_dir=str(tmp_memory_dir))
    payload = json.loads(raw)
    assert payload.get("compact") is True


def test_search_mode_debug_sets_explain(tmp_memory_dir: Path) -> None:
    from agentic_memory.server import memory_search

    raw = memory_search(query="test", mode="debug", memory_dir=str(tmp_memory_dir))
    # debug mode: compact=False, no error means explain was enabled
    payload = json.loads(raw)
    assert payload.get("compact") is False


# ---------- H3: State return summary ----------


def test_cmd_add_returns_json_summary(tmp_memory_dir: Path) -> None:
    import io
    from contextlib import redirect_stderr, redirect_stdout

    state_path = tmp_memory_dir / "_state.md"
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = state.cmd_add(state_path, section="focus", items=["New task"])
    assert code == 0
    result = json.loads(out.getvalue().strip())
    assert result["section"] == "現在のフォーカス"
    assert result["added"] == 1
    assert result["after"] >= 1


def test_cmd_add_returns_removed_count(tmp_memory_dir: Path) -> None:
    import io
    from contextlib import redirect_stderr, redirect_stdout

    state_path = tmp_memory_dir / "_state.md"
    # Add initial items
    out = io.StringIO()
    with redirect_stdout(out), redirect_stderr(io.StringIO()):
        state.cmd_add(state_path, section="focus", items=["Alpha task", "Beta task"])

    # Replace: remove items matching "Alpha", add "Gamma"
    out = io.StringIO()
    with redirect_stdout(out), redirect_stderr(io.StringIO()):
        code = state.cmd_add(state_path, section="focus", items=["Gamma task"], replace=["Alpha"])
    assert code == 0
    result = json.loads(out.getvalue().strip())
    assert result["removed"] == 1
    assert result["added"] == 1


def test_cmd_from_note_returns_json_summary(tmp_memory_dir: Path) -> None:
    import io
    from contextlib import redirect_stderr, redirect_stdout

    note_dir = tmp_memory_dir / "2026-01-20"
    note_dir.mkdir(parents=True, exist_ok=True)
    note_path = note_dir / "1000_test.md"
    note_path.write_text(
        "# Test Note\n\n- Date: 2026-01-20\n\n"
        "## 目標\n\n- goal item\n\n"
        "## 次のアクション\n\n- next item\n\n"
        "## 判断\n\n- decision item\n",
        encoding="utf-8",
    )
    state_path = tmp_memory_dir / "_state.md"
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = state.cmd_from_note(state_path, note_path, no_auto_improve=True)
    assert code == 0
    result = json.loads(out.getvalue().strip())
    assert result["path"].endswith("_state.md")
    assert isinstance(result["updated_sections"], list)
    assert isinstance(result["section_counts"], dict)


# ---------- M1: Japanese slug hash fallback ----------


def test_slugify_japanese_title() -> None:
    slug = note.slugify("日本語テスト")
    assert len(slug) == 8  # SHA1 hex[:8]
    assert slug.isalnum()


def test_slugify_mixed_title() -> None:
    slug = note.slugify("日本語 test")
    assert slug == "test"


def test_slugify_ascii_special_chars_still_session() -> None:
    assert note.slugify("!!!") == "session"
    assert note.slugify("") == "session"


def test_slugify_same_japanese_title_is_deterministic() -> None:
    slug1 = note.slugify("同じタイトル")
    slug2 = note.slugify("同じタイトル")
    assert slug1 == slug2


# ---------- M2: Evidence language-aware section names ----------


def test_evidence_english_note_uses_english_section_names() -> None:
    note_content = (
        "# English Session\n\n"
        "- Date: 2026-03-13\n\n"
        "## Goals\n\n- Build feature\n\n"
        "## Outcome\n\n- Feature built\n\n"
        "## Decisions\n\n- Use library X\n"
    )
    parsed = evidence.parse_sections(note_content)
    lang = evidence._detect_note_language(parsed)
    assert lang == "en"


def test_evidence_japanese_note_uses_japanese_section_names() -> None:
    note_content = "# 日本語セッション\n\n## 目標\n\n- 機能構築\n\n## 成果\n\n- 構築完了\n"
    parsed = evidence.parse_sections(note_content)
    lang = evidence._detect_note_language(parsed)
    assert lang == "ja"


def test_evidence_pack_english_sections(tmp_path: Path) -> None:
    # Use section names that match NOTE_SECTION_ALIASES values
    note_path = tmp_path / "en_note.md"
    note_path.write_text(
        "# English Session\n\n"
        "- Date: 2026-03-13\n\n"
        "## Goal\n\n- Build feature X\n\n"
        "## Outcome\n\n- Feature X built\n\n"
        "## Decisions\n\n- Use library Y\n",
        encoding="utf-8",
    )
    pack = evidence.generate_evidence_pack("feature", [note_path])
    assert "### Goal" in pack
    assert "### Outcome" in pack
    assert "### Decisions" in pack
    assert "### 目標" not in pack


def test_evidence_pack_japanese_sections(tmp_path: Path) -> None:
    note_path = tmp_path / "ja_note.md"
    note_path.write_text(
        "# 日本語セッション\n\n## 目標\n\n- 機能構築\n\n## 成果\n\n- 構築完了\n",
        encoding="utf-8",
    )
    pack = evidence.generate_evidence_pack("機能", [note_path])
    assert "### 目標" in pack
    assert "### 成果" in pack


# ---------- L1: n-gram expansion cap ----------


def test_tokenize_max_cjk_terms_respected() -> None:
    """max_cjk_terms caps n-gram expansion (ngram backend only)."""
    long_text = "日本語のテストで非常に長いテキストを生成する"
    ngram_cfg = {"tokenizer": {"backend": "ngram"}}
    tokens_default = tokenizer.tokenize(long_text, config=ngram_cfg, max_cjk_terms=120)
    tokens_capped = tokenizer.tokenize(long_text, config=ngram_cfg, max_cjk_terms=5)
    cjk_capped = [t for t in tokens_capped if not t.isascii()]
    assert len(cjk_capped) <= 5
    assert len(tokens_capped) <= len(tokens_default)


def test_expand_terms_limits_cjk_expansion() -> None:
    qterms = parse_query("検索テスト")
    config = {"query_expansion": {"enabled_default": True}}
    expanded = expand_terms(qterms, config, enable=True)
    # Should not generate more than ~20 CJK terms per original term
    cjk_terms = [qt for qt in expanded if qt.term and not qt.term.isascii()]
    assert len(cjk_terms) <= 40  # reasonable cap for a 2-token query


# ---------- L3: expire_stale stale_days=0 validation ----------


def test_expire_stale_rejects_zero_days(tmp_memory_dir: Path) -> None:
    state_path = tmp_memory_dir / "_state.md"
    with pytest.raises(ValueError, match="stale_days must be >= 1"):
        state.expire_stale_items(state_path, stale_days=0)


def test_expire_stale_rejects_negative_days(tmp_memory_dir: Path) -> None:
    state_path = tmp_memory_dir / "_state.md"
    with pytest.raises(ValueError, match="stale_days must be >= 1"):
        state.expire_stale_items(state_path, stale_days=-1)


def test_expire_stale_accepts_one_day(tmp_memory_dir: Path) -> None:
    state_path = tmp_memory_dir / "_state.md"
    result = state.expire_stale_items(state_path, stale_days=1)
    assert isinstance(result, dict)
    assert "count" in result
