"""Tests for v0.3.0 usability improvements (Bug1/2, H1-H3, M1-M3, L1-L3)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentic_memory.core import evidence, index, note, sections, state, tokenizer
from agentic_memory.core.query import expand_terms, parse_query
from agentic_memory.core.search import (
    COMPACT_EXCLUDE_FIELDS,
    _extract_recall_feedback_terms,
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
    """mode='quick' should enable compact — settings echo-back fields are stripped."""
    from agentic_memory.server import memory_search

    raw = memory_search(query="test", mode="quick", memory_dir=str(tmp_memory_dir))
    payload = json.loads(raw)
    # Settings echo-back fields should be stripped in compact mode
    assert "compact" not in payload
    assert "expand_enabled" not in payload
    assert "rerank_enabled" not in payload


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


# ---------- M1: Japanese slug — CJK characters preserved ----------


def test_slugify_japanese_title() -> None:
    slug = note.slugify("日本語テスト")
    assert slug == "日本語テスト"


def test_slugify_mixed_title() -> None:
    slug = note.slugify("日本語 test")
    assert slug == "日本語-test"


def test_slugify_ascii_special_chars_still_session() -> None:
    assert note.slugify("!!!") == "session"
    assert note.slugify("") == "session"


def test_slugify_same_japanese_title_is_deterministic() -> None:
    slug1 = note.slugify("同じタイトル")
    slug2 = note.slugify("同じタイトル")
    assert slug1 == slug2


def test_slugify_ascii_unchanged() -> None:
    assert note.slugify("Hello World") == "hello-world"


def test_slugify_truncation() -> None:
    long_title = "あ" * 60
    slug = note.slugify(long_title)
    assert len(slug) <= 50


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


def test_evidence_skip_placeholder_lines(tmp_path: Path) -> None:
    note_path = tmp_path / "placeholder_note.md"
    note_path.write_text(
        "# Placeholder Session\n\n"
        "- Date: 2026-03-14\n\n"
        "## 成果\n\n"
        "-\n\n"
        "## 検証\n\n"
        "- ## Tests:\n"
        "- ## Result:\n\n"
        "## 判断\n\n"
        "- Query used:\n"
        "- Useful notes:\n"
        "- Missed notes / gaps:\n"
        "- Retrieval improvements:\n\n"
        "## 次のアクション\n\n"
        "- Ship fix\n",
        encoding="utf-8",
    )

    pack = evidence.generate_evidence_pack("unmatched-query", [note_path])

    assert "### 成果" not in pack
    assert "### 検証" not in pack
    assert "### 判断" not in pack
    assert "## Tests:" not in pack
    assert "Query used:" not in pack
    assert "### 次のアクション" in pack
    assert "- Ship fix" in pack


# ---------- Improvement: rg fallback metadata enrichment ----------


def test_rg_fallback_enriches_metadata_from_index(tmp_memory_dir: Path) -> None:
    """When rg/python fallback is used, results should have metadata from the index."""
    note_dir = tmp_memory_dir / "2026-03-14"
    note_dir.mkdir(parents=True, exist_ok=True)
    note_path = note_dir / "1200_rg-test.md"
    note_path.write_text(
        "# RG Fallback Test\n\n"
        "- Date: 2026-03-14\n"
        "- Tags: rg_test, fallback\n\n"
        "## 目標\n\n- Test rg fallback metadata enrichment\n",
        encoding="utf-8",
    )
    index.index_note(
        note_path=note_path,
        index_path=tmp_memory_dir / "_index.jsonl",
        dailynote_dir=tmp_memory_dir,
    )

    result = search(
        query="fallback",
        memory_dir=tmp_memory_dir,
        engine="python",
    )

    assert len(result["results"]) >= 1
    _, entry, _ = result["results"][0]
    # Metadata should be populated from index, not empty
    assert entry.title == "RG Fallback Test"
    assert entry.date == "2026-03-14"


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


# ---------- Improvement: memory_init 3-level status ----------


def test_init_status_created(tmp_path: Path) -> None:
    """New directory should return status 'created'."""
    from agentic_memory.core.config import init_memory_dir

    new_dir = tmp_path / "brand_new"
    result = init_memory_dir(new_dir)
    assert result["status"] == "created"


def test_init_status_initialized(tmp_path: Path) -> None:
    """Existing directory with missing files should return status 'initialized'."""
    from agentic_memory.core.config import init_memory_dir

    existing_dir = tmp_path / "partial"
    existing_dir.mkdir(parents=True)
    result = init_memory_dir(existing_dir)
    assert result["status"] == "initialized"


def test_init_status_already_exists(tmp_path: Path) -> None:
    """Existing directory with all files should return status 'already_exists'."""
    from agentic_memory.core.config import init_memory_dir

    full_dir = tmp_path / "complete"
    init_memory_dir(full_dir)  # first call creates everything
    result = init_memory_dir(full_dir)  # second call
    assert result["status"] == "already_exists"


# ---------- Improvement: auto_restore agent_id auto-skip ----------


def test_auto_restore_no_agent_id_no_warning(tmp_memory_dir: Path) -> None:
    """auto_restore with no agent_id should skip agent_state without warning."""
    result = state.auto_restore(
        memory_dir=tmp_memory_dir,
        agent_id=None,
        include_agent_state=True,  # explicitly True, but should auto-skip
    )
    assert result["agent_state"] is None
    # Should NOT contain the old warning about agent_id being required
    for w in result.get("warnings", []):
        assert "agent_id" not in w.lower()


def test_auto_restore_with_agent_id_includes_state(tmp_memory_dir: Path) -> None:
    """auto_restore with agent_id should include agent_state."""
    result = state.auto_restore(
        memory_dir=tmp_memory_dir,
        agent_id="test-agent",
        include_agent_state=True,
    )
    assert result["agent_id"] == "test-agent"
    # agent_state should be populated (even if empty sections)
    assert result["agent_state"] is not None


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


# ---------- Feedback terms: note filename filtering ----------


def test_feedback_terms_skip_note_filenames(tmp_path: Path) -> None:
    """Note filenames in 'Useful notes' should be filtered out."""
    note_path = tmp_path / "test_note.md"
    note_path.write_text(
        "# Test\n\n"
        "## 想起フィードバック（任意）\n\n"
        "- Query used: 動作テスト\n"
        "- Useful notes: 2157_agentic-memory-v0-3-0.md, 2349_agentic-memory-v0-4-1\n"
        "- Missed notes / gaps:\n"
        "- Retrieval improvements:\n",
        encoding="utf-8",
    )
    terms = _extract_recall_feedback_terms(note_path)
    # Filename prefix and slug fragments should NOT appear
    assert "2157" not in terms
    assert "2349" not in terms
    assert "v0" not in terms
    assert "agentic" not in terms


def test_feedback_terms_skip_path_prefixed_filenames(tmp_path: Path) -> None:
    """Path-prefixed filenames like '2026-03-14/2157_slug' should also be filtered."""
    note_path = tmp_path / "test_note.md"
    note_path.write_text(
        "# Test\n\n"
        "## 想起フィードバック（任意）\n\n"
        "- Query used: test\n"
        "- Useful notes: 2026-03-14/2157_agentic-memory-v0-3-0.md\n"
        "- Missed notes / gaps:\n",
        encoding="utf-8",
    )
    terms = _extract_recall_feedback_terms(note_path)
    assert "2157" not in terms
    assert "2026-03-14" not in terms


def test_feedback_terms_keep_descriptive_text(tmp_path: Path) -> None:
    """Descriptive text in 'Useful notes' should be kept."""
    note_path = tmp_path / "test_note.md"
    note_path.write_text(
        "# Test\n\n"
        "## Recall feedback (optional)\n\n"
        "- Query used: search test\n"
        "- Useful notes: memory search optimization\n"
        "- Missed notes / gaps:\n",
        encoding="utf-8",
    )
    terms = _extract_recall_feedback_terms(note_path)
    assert "memory search optimization" in terms
    assert "memory" in terms
    assert "search" in terms


def test_feedback_terms_skip_embedded_filenames_in_phrases(tmp_path: Path) -> None:
    """Filenames embedded in descriptive phrases should be stripped before tokenization."""
    note_path = tmp_path / "test_note.md"
    note_path.write_text(
        "# Test\n\n"
        "## 想起フィードバック（任意）\n\n"
        "- Query used: テスト\n"
        "- Useful notes: 2157_agentic-memory-v0-3-0.md が v0.3.0 の比較基準として有用、"
        "2349_agentic-memory-v0-4-1.md が v0.4.1 の比較基準として有用\n"
        "- Missed notes / gaps: なし\n",
        encoding="utf-8",
    )
    terms = _extract_recall_feedback_terms(note_path)
    # Filename fragments should NOT appear
    assert "2157" not in terms
    assert "2349" not in terms
    assert "2157_agentic-memory-v0-3-0.md" not in terms
    assert "agentic-memory-v0-3-0.md" not in terms
    assert "0.md" not in terms
    # Descriptive text should be preserved
    assert any("v0.3.0" in t for t in terms)


# ---------- Quick mode: no_feedback_expand and compact metadata ----------


def test_search_mode_quick_disables_feedback_expand(tmp_memory_dir: Path) -> None:
    """mode='quick' strips feedback_expand from output (settings echo-back removed)."""
    from agentic_memory.server import memory_search

    raw = memory_search(query="test", mode="quick", memory_dir=str(tmp_memory_dir))
    payload = json.loads(raw)
    # feedback_expand is stripped in compact mode along with other settings
    assert "feedback_expand" not in payload


def test_search_mode_quick_strips_empty_metadata(tmp_memory_dir: Path) -> None:
    """mode='quick' should omit empty feedback_source_note, feedback_terms_used, etc."""
    from agentic_memory.server import memory_search

    raw = memory_search(query="test", mode="quick", memory_dir=str(tmp_memory_dir))
    payload = json.loads(raw)
    # Empty/null fields should be stripped
    assert "feedback_source_note" not in payload
    assert "feedback_terms_used" not in payload
    assert "suggestions" not in payload
    # All-null filters should be stripped
    assert "filters" not in payload


# ---------- v0.5.5: search_global mode parameter and expanded_terms fix ----------


def test_search_global_mode_quick(tmp_memory_dir: Path) -> None:
    """memory_search_global with mode='quick' strips settings echo-back fields."""
    from agentic_memory.server import memory_search_global

    raw = memory_search_global(query="test", memory_dirs=[str(tmp_memory_dir)], mode="quick")
    payload = json.loads(raw)
    # Settings echo-back fields should be stripped in compact mode
    assert "compact" not in payload
    assert "feedback_expand" not in payload
    assert "expand_enabled" not in payload


def test_search_global_mode_debug(tmp_memory_dir: Path) -> None:
    """memory_search_global with mode='debug' should enable explain and disable compact."""
    from agentic_memory.server import memory_search_global

    raw = memory_search_global(query="test", memory_dirs=[str(tmp_memory_dir)], mode="debug")
    payload = json.loads(raw)
    assert payload.get("compact") is False
    # debug mode should include full expanded QueryTerm objects
    assert "expanded" in payload


def test_search_global_compact_omits_expanded_terms(tmp_memory_dir: Path) -> None:
    """search_global compact mode should omit expanded_terms."""
    from agentic_memory.core.search import search_global

    result = search_global(
        query="動作テスト",
        memory_dirs=[tmp_memory_dir],
        compact=True,
    )
    assert "expanded_terms" not in result


def test_search_global_no_feedback_expand_kwarg(tmp_memory_dir: Path) -> None:
    """search_global should forward no_feedback_expand to sub-searches."""
    from agentic_memory.core.search import search_global

    result = search_global(
        query="test",
        memory_dirs=[tmp_memory_dir],
        compact=True,
        no_feedback_expand=True,
    )
    assert result["feedback_expand"] is False


def test_compact_mode_omits_expanded_terms(tmp_memory_dir: Path) -> None:
    """Compact mode should omit expanded_terms to save context."""
    note_file = note.create_note(tmp_memory_dir, title="テスト")
    note_path = Path(str(note_file))
    note_path.write_text(
        "# テスト\n\n- Tags: testing\n- Keywords: テスト\n\n## 作業ログ\n\n- テスト entry\n",
        encoding="utf-8",
    )
    index.index_note(
        note_path=note_path,
        index_path=tmp_memory_dir / "_index.jsonl",
        dailynote_dir=tmp_memory_dir,
    )
    result = search(query="テスト", memory_dir=tmp_memory_dir, compact=True)
    assert "expanded_terms" not in result, "expanded_terms should be omitted in compact mode"
    result_full = search(query="テスト", memory_dir=tmp_memory_dir, compact=False)
    assert "expanded_terms" in result_full


# ---------- v0.5.7: path doubling fix ----------


def test_resolve_paths_no_doubling_for_memory_prefixed_path() -> None:
    """Paths starting with memory_dir name should not get double-prefixed."""
    from agentic_memory.server import _resolve_paths

    memory_dir = Path("memory")
    # Path that looks like a search result (relative to project root)
    paths = ["memory/2026-03-14/nonexistent-test-file.md"]
    resolved = _resolve_paths(paths, memory_dir)
    # Should NOT produce memory/memory/...
    assert "memory/memory" not in str(resolved[0])
    assert str(resolved[0]) == "memory/2026-03-14/nonexistent-test-file.md"


def test_resolve_note_path_no_doubling() -> None:
    """_resolve_note_path should not double the memory_dir prefix."""
    from agentic_memory.server import _resolve_note_path

    memory_dir = Path("memory")
    result = _resolve_note_path("memory/2026-03-14/nonexistent.md", memory_dir)
    assert "memory/memory" not in str(result)


def test_resolve_paths_still_prepends_for_relative_to_memdir() -> None:
    """Paths relative to memory_dir (no memory/ prefix) should still be resolved."""
    from agentic_memory.server import _resolve_paths

    memory_dir = Path("memory")
    paths = ["2026-03-14/some-note.md"]
    resolved = _resolve_paths(paths, memory_dir)
    assert str(resolved[0]) == "memory/2026-03-14/some-note.md"


# ---------- v0.5.7: total_found in search results ----------


def test_search_total_found(tmp_memory_dir: Path) -> None:
    """Search results should include total_found count."""
    result = search(query="test", memory_dir=tmp_memory_dir)
    assert "total_found" in result
    assert isinstance(result["total_found"], int)
    assert result["total_found"] >= 0


def test_search_total_found_with_notes(tmp_memory_dir: Path) -> None:
    """total_found should reflect actual matches before top truncation."""
    # Create test notes
    for i in range(5):
        note_file = note.create_note(tmp_memory_dir, title=f"test note {i}")
        note_path = Path(str(note_file))
        content = (
            f"# test note {i}\n\n- Tags: testing\n- Keywords: test\n\n"
            f"## 作業ログ\n\n- test entry {i}\n"
        )
        note_path.write_text(content)
        index.index_note(
            note_path=note_path,
            index_path=tmp_memory_dir / "_index.jsonl",
            dailynote_dir=tmp_memory_dir,
        )

    result = search(query="test", memory_dir=tmp_memory_dir, top=2)
    assert result["total_found"] >= 2
    assert len(result["results"]) <= 2


def test_search_global_total_found(tmp_memory_dir: Path) -> None:
    """search_global results should include total_found."""
    from agentic_memory.core.search import search_global

    result = search_global(query="test", memory_dirs=[tmp_memory_dir])
    assert "total_found" in result
    assert isinstance(result["total_found"], int)


def test_keywords_exclude_markdown_headers(tmp_path: Path) -> None:
    """Keywords extraction should exclude markdown section headers."""
    note = tmp_path / "2026-03-14" / "2200_test.md"
    note.parent.mkdir(parents=True)
    note.write_text(
        "# Test Note\n- Date: 2026-03-14\n- Keywords: ## Goals\n\n## Goals\n- goal1\n",
        encoding="utf-8",
    )

    entry = index.build_entry(note, max_summary_chars=200, dailynote_dir=tmp_path)

    for kw in entry["keywords"]:
        assert not kw.startswith("#"), f"Markdown header in keywords: {kw}"


# ---------- v0.5.10: compact empty warnings strip, expanded debug-only ----------


def _create_indexed_note(tmp_memory_dir: Path) -> None:
    """Helper: create and index a note so the index engine is used (avoids rg fallback)."""
    note_file = note.create_note(tmp_memory_dir, title="test note")
    note_path = Path(str(note_file))
    note_path.write_text(
        "# test note\n\n- Tags: testing\n- Keywords: test\n\n## 作業ログ\n\n- test entry\n",
        encoding="utf-8",
    )
    index.index_note(
        note_path=note_path,
        index_path=tmp_memory_dir / "_index.jsonl",
        dailynote_dir=tmp_memory_dir,
    )


def test_search_quick_strips_empty_warnings(tmp_memory_dir: Path) -> None:
    """mode='quick' should omit empty warnings list to save context."""
    from agentic_memory.server import memory_search

    _create_indexed_note(tmp_memory_dir)
    raw = memory_search(query="test", mode="quick", memory_dir=str(tmp_memory_dir))
    payload = json.loads(raw)
    assert "warnings" not in payload


def test_search_detailed_omits_expanded(tmp_memory_dir: Path) -> None:
    """mode='detailed' should include expanded_terms but NOT verbose expanded QueryTerm objects."""
    from agentic_memory.server import memory_search

    _create_indexed_note(tmp_memory_dir)
    raw = memory_search(query="test", mode="detailed", memory_dir=str(tmp_memory_dir))
    payload = json.loads(raw)
    assert "expanded" not in payload
    assert "expanded_terms" in payload


def test_search_debug_includes_expanded(tmp_memory_dir: Path) -> None:
    """mode='debug' should include both expanded and expanded_terms."""
    from agentic_memory.server import memory_search

    _create_indexed_note(tmp_memory_dir)
    raw = memory_search(query="test", mode="debug", memory_dir=str(tmp_memory_dir))
    payload = json.loads(raw)
    assert "expanded" in payload
    assert "expanded_terms" in payload


def test_search_global_quick_strips_empty_warnings(tmp_memory_dir: Path) -> None:
    """search_global mode='quick' should omit empty warnings list."""
    from agentic_memory.server import memory_search_global

    _create_indexed_note(tmp_memory_dir)
    raw = memory_search_global(query="test", memory_dirs=[str(tmp_memory_dir)], mode="quick")
    payload = json.loads(raw)
    assert "warnings" not in payload


def test_search_global_detailed_omits_expanded(tmp_memory_dir: Path) -> None:
    """search_global mode='detailed' should NOT include verbose expanded QueryTerm objects."""
    from agentic_memory.server import memory_search_global

    _create_indexed_note(tmp_memory_dir)
    raw = memory_search_global(query="test", memory_dirs=[str(tmp_memory_dir)], mode="detailed")
    payload = json.loads(raw)
    assert "expanded" not in payload


# ---------- v0.5.11: detailed mode strips auto_keywords/work_log_keywords ----------


def test_search_detailed_strips_auto_keywords(tmp_memory_dir: Path) -> None:
    """mode='detailed' should strip auto_keywords and work_log_keywords."""
    from agentic_memory.server import memory_search

    _create_indexed_note(tmp_memory_dir)
    raw = memory_search(query="test", mode="detailed", memory_dir=str(tmp_memory_dir))
    payload = json.loads(raw)
    for result_item in payload.get("results", []):
        if isinstance(result_item, list) and len(result_item) >= 2:
            entry = result_item[1]
            assert "auto_keywords" not in entry
            assert "work_log_keywords" not in entry


def test_search_debug_keeps_auto_keywords(tmp_memory_dir: Path) -> None:
    """mode='debug' should keep auto_keywords and work_log_keywords."""
    from agentic_memory.server import memory_search

    _create_indexed_note(tmp_memory_dir)
    raw = memory_search(query="test", mode="debug", memory_dir=str(tmp_memory_dir))
    payload = json.loads(raw)
    for result_item in payload.get("results", []):
        if isinstance(result_item, list) and len(result_item) >= 2:
            entry = result_item[1]
            assert "auto_keywords" in entry


def test_search_global_detailed_strips_auto_keywords(tmp_memory_dir: Path) -> None:
    """search_global mode='detailed' should strip auto_keywords."""
    from agentic_memory.server import memory_search_global

    _create_indexed_note(tmp_memory_dir)
    raw = memory_search_global(query="test", memory_dirs=[str(tmp_memory_dir)], mode="detailed")
    payload = json.loads(raw)
    for result_item in payload.get("results", []):
        if isinstance(result_item, list) and len(result_item) >= 2:
            entry = result_item[1]
            assert "auto_keywords" not in entry


# ---------- v0.5.11: evidence error message improvement ----------


def test_evidence_missing_paths_and_task_id_error_message() -> None:
    """evidence should give a helpful error when both paths and task_id are omitted."""
    from agentic_memory.server import memory_evidence

    payload = json.loads(memory_evidence(query="test"))
    assert payload["error_type"] == "validation_error"
    assert "Either 'paths' or 'task_id' must be provided" in payload["message"]


# ---------- v0.5.11: health_check fix parameter ----------


def test_health_check_fix_reindexes_stale(tmp_memory_dir: Path) -> None:
    """fix=True should re-index stale notes."""
    from agentic_memory.core.health import fix_issues

    # Create a note and index it
    note_dir = tmp_memory_dir / "2026-03-15"
    note_dir.mkdir(parents=True, exist_ok=True)
    note_path = note_dir / "1200_fix-test.md"
    note_path.write_text(
        "# Fix Test\n\n- Date: 2026-03-15\n\n## 目標\n\n- test fix\n",
        encoding="utf-8",
    )
    index.index_note(
        note_path=note_path,
        index_path=tmp_memory_dir / "_index.jsonl",
        dailynote_dir=tmp_memory_dir,
    )
    # Touch the note to make it stale
    import time

    time.sleep(0.1)
    note_path.write_text(
        "# Fix Test Updated\n\n- Date: 2026-03-15\n\n## 目標\n\n- updated content\n",
        encoding="utf-8",
    )

    result = fix_issues(tmp_memory_dir)
    assert isinstance(result["reindexed"], list)
    assert result["post_fix_summary"].startswith("正常")


def test_health_check_fix_removes_orphans(tmp_memory_dir: Path) -> None:
    """fix=True should remove orphan index entries."""
    from agentic_memory.core.health import fix_issues

    # Add an orphan entry to the index
    index_path = tmp_memory_dir / "_index.jsonl"
    with index_path.open("a", encoding="utf-8") as f:
        f.write(
            json.dumps({"path": "nonexistent/orphan.md", "title": "orphan"}, ensure_ascii=False)
            + "\n"
        )

    result = fix_issues(tmp_memory_dir)
    assert result["orphans_removed"] >= 1
    assert result["post_fix_summary"].startswith("正常")


def test_health_check_force_reindex_rebuilds_all(tmp_memory_dir: Path) -> None:
    """force_reindex=True should rebuild the entire index from scratch."""
    from agentic_memory.core.health import fix_issues

    note_dir = tmp_memory_dir / "2026-03-20"
    note_dir.mkdir(parents=True, exist_ok=True)
    for i in range(3):
        note_path = note_dir / f"120{i}_force-test-{i}.md"
        note_path.write_text(
            f"# Force Test {i}\n\n- Date: 2026-03-20\n\n## 目標\n\n- item {i}\n",
            encoding="utf-8",
        )
        index.index_note(
            note_path=note_path,
            index_path=tmp_memory_dir / "_index.jsonl",
            dailynote_dir=tmp_memory_dir,
        )

    result = fix_issues(tmp_memory_dir, force_reindex=True)
    assert result["force_reindex"] is True
    assert result["total_entries"] == 3
    assert len(result["reindexed"]) == 3
    assert result["post_fix_summary"].startswith("正常")


def test_health_check_server_force_reindex(tmp_memory_dir: Path) -> None:
    """memory_health_check(force_reindex=True) should return full rebuild report."""
    from agentic_memory.server import memory_health_check

    raw = memory_health_check(force_reindex=True, memory_dir=str(tmp_memory_dir))
    payload = json.loads(raw)
    assert payload["force_reindex"] is True
    assert "total_entries" in payload
    assert "post_fix_summary" in payload


def test_health_check_server_fix_false_returns_check(tmp_memory_dir: Path) -> None:
    """memory_health_check(fix=False) should return the standard check report."""
    from agentic_memory.server import memory_health_check

    raw = memory_health_check(fix=False, memory_dir=str(tmp_memory_dir))
    payload = json.loads(raw)
    assert "summary" in payload
    assert "orphan_entries" in payload


def test_health_check_server_fix_true_returns_fix_report(tmp_memory_dir: Path) -> None:
    """memory_health_check(fix=True) should return the fix report."""
    from agentic_memory.server import memory_health_check

    raw = memory_health_check(fix=True, memory_dir=str(tmp_memory_dir))
    payload = json.loads(raw)
    assert "reindexed" in payload
    assert "post_fix_summary" in payload


# ---------- v0.5.11: boundary CJK tokenizer ----------


def test_boundary_cjk_tokens_basic() -> None:
    """boundary tokenizer should split at script boundaries."""
    from agentic_memory.core.tokenizer import _boundary_cjk_tokens

    tokens = _boundary_cjk_tokens("動作テスト")
    assert "動作" in tokens
    assert "テスト" in tokens
    # Should NOT have n-gram fragments like "作テ"
    assert "作テ" not in tokens


def test_boundary_cjk_tokens_fewer_than_ngrams() -> None:
    """boundary tokenizer should produce significantly fewer tokens than n-grams."""
    from agentic_memory.core.tokenizer import _boundary_cjk_tokens, _cjk_ngrams

    text = "動作テストとユーザビリティレビュー"
    boundary_tokens = _boundary_cjk_tokens(text)
    ngram_tokens = _cjk_ngrams(text)
    assert len(boundary_tokens) < len(ngram_tokens)


def test_boundary_cjk_tokens_skips_particles() -> None:
    """boundary tokenizer should skip single-char hiragana particles."""
    from agentic_memory.core.tokenizer import _boundary_cjk_tokens

    tokens = _boundary_cjk_tokens("検索と分析")
    assert "と" not in tokens
    assert "検索" in tokens
    assert "分析" in tokens


def test_tokenizer_boundary_backend_selected_by_default() -> None:
    """Without sudachipy, the boundary backend should be selected."""
    from agentic_memory.core.tokenizer import _get_tokenizer_backend, is_sudachi_available

    if not is_sudachi_available():
        assert _get_tokenizer_backend({}) == "boundary"


def test_tokenizer_boundary_backend_explicit() -> None:
    """Explicit boundary backend selection should work."""
    from agentic_memory.core.tokenizer import _get_tokenizer_backend

    assert _get_tokenizer_backend({"tokenizer": {"backend": "boundary"}}) == "boundary"


def test_tokenize_with_boundary_backend() -> None:
    """tokenize() with boundary backend should produce fewer CJK tokens."""
    boundary_cfg = {"tokenizer": {"backend": "boundary"}}
    ngram_cfg = {"tokenizer": {"backend": "ngram"}}
    text = "メモリ検索の最適化テスト"
    boundary_tokens = tokenizer.tokenize(text, config=boundary_cfg)
    ngram_tokens = tokenizer.tokenize(text, config=ngram_cfg)
    cjk_boundary = [t for t in boundary_tokens if not t.isascii()]
    cjk_ngram = [t for t in ngram_tokens if not t.isascii()]
    assert len(cjk_boundary) < len(cjk_ngram)


def test_detailed_exclude_fields_defined() -> None:
    """DETAILED_EXCLUDE_FIELDS should contain auto_keywords and work_log_keywords."""
    from agentic_memory.core.search import DETAILED_EXCLUDE_FIELDS

    assert "auto_keywords" in DETAILED_EXCLUDE_FIELDS
    assert "work_log_keywords" in DETAILED_EXCLUDE_FIELDS
