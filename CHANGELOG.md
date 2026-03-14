# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.5.8] - 2026-03-15

### Changed

- **Breaking**: `memory_search` and `memory_search_global` now default to `mode="quick"` (previously `None`, equivalent to `detailed`). This reduces context consumption for agent callers. To restore previous behavior, pass `mode="detailed"` explicitly
- Compact mode (`mode="quick"` or `compact=True`) now omits `expanded_terms` from search results, further reducing response size

### Fixed

- `build_entry` now filters out markdown section headers (e.g., `## Goals`) from extracted `keywords` field, preventing index pollution when Keywords header is empty
- ZIP export (`memory_export` with `fmt="zip"`) no longer includes `.lock` files (`_index.jsonl.lock`, `_state.md.lock`)

## [0.5.7] - 2026-03-14

### Added

- `total_found` field in `memory_search` and `memory_search_global` results — indicates how many entries matched before `top` truncation (index engine only; non-index engines return post-truncation count)

### Fixed

- Path doubling in `memory_evidence` and related tools: paths from search results (e.g., `memory/2026-03-14/...`) no longer produce `memory/memory/...` when passed to `memory_evidence` or `memory_state_from_note`

### Improved

- `memory_search` docstring clarifies that `no_feedback_expand` is overridden when `mode` is set (not independently combinable)

## [0.5.6] - 2026-03-14

### Changed

- `memory_init` no longer returns `state_content` when status is `already_exists`, reducing context consumption; use `memory_state_show` to read current state

### Improved

- `memory_search_global` docstring now documents that `mode` and `no_cjk_expand` are independent — combine `mode="quick"` with `no_cjk_expand=True` for minimal context
- `memory_search` docstring corrected: `no_feedback_expand` is controlled by `mode` presets (not independent)
- README: added "Upgrading" section documenting the need to reconnect the MCP server after package updates

## [0.5.5] - 2026-03-14

### Added

- `mode` parameter for `memory_search_global` (`quick`/`detailed`/`debug` presets), matching `memory_search` API
- `no_feedback_expand` parameter for `memory_search_global`
- `Literal["quick", "detailed", "debug"]` type constraint on `mode` parameter for both `memory_search` and `memory_search_global`, providing enum hints in MCP tool schemas

### Fixed

- `search_global` now returns populated `expanded_terms` in compact mode (previously returned empty array because QueryTerm objects are excluded in compact mode; now falls back to string-based expanded terms from sub-searches)

## [0.5.4] - 2026-03-14

### Fixed

- `_extract_recall_feedback_terms` now strips embedded note filenames from phrases (e.g., `2157_xxx.md が v0.3.0 の比較基準として有用`) before tokenization, preventing slug fragments from leaking into `feedback_terms_used`
- `mode:quick` now defaults `no_feedback_expand=True` to reduce context consumption
- `_strip_compact_fields` now omits empty/null metadata fields (`feedback_source_note`, `feedback_terms_used`, `suggestions`, all-null `filters`) in compact mode

## [0.5.3] - 2026-03-14

### Fixed

- `_extract_recall_feedback_terms` now filters out note filename patterns (e.g., `2157_agentic-memory-v0-3-0.md`) from feedback terms, preventing slug fragments from polluting `feedback_terms_used` in search results
- `memory_search` docstring now documents all 6 boolean negation parameters (`no_expand`, `no_cjk_expand`, `no_fuzzy`, `no_feedback_expand`, `no_prf`, `no_rerank`) and their independence from `mode` presets

## [0.5.2] - 2026-03-14

### Added

- `date:YYYY-MM-DD` single-date filter syntax as shorthand for `date:YYYY-MM-DD..YYYY-MM-DD`
- `compact` parameter for `memory_index_upsert` to omit verbose fields (auto_keywords, work_log_keywords, etc.) from the response

### Fixed

- `no_cjk_expand` now also suppresses CJK n-gram tokens in feedback expansion (previously only affected query expansion)
- `memory_state_remove` now returns structured JSON (`{"path", "section", "removed", "items"}`) consistent with other state commands (previously returned plain count)
- `memory_state_from_note` no longer copies "next actions" into the "focus" section; focus is derived only from goals
- `deduplicate` now detects substring-level near-duplicates (e.g., "X has room for improvement" vs "X is inconsistent with other tools") and keeps the more detailed version
- `memory_evidence` more aggressively skips template placeholder lines and empty bullets, preventing noise in evidence packs
- `expand_terms` no longer generates redundant ALLCAPS variants (e.g., `AGENTIC-MEMORY`) in query expansion; search scoring is already case-insensitive

## [0.5.1] - 2026-03-14

### Added

- `no_cjk_expand` parameter for `memory_search_global` to suppress CJK n-gram expansion across cross-project searches

### Fixed

- `memory_search` / `memory_search_global` in compact mode (`compact=True` or `mode: quick`) now omit the verbose `expanded` field (full QueryTerm objects), keeping only the lightweight `expanded_terms` string list
- `memory_evidence` now skips template placeholder lines (`-`, `- ## Files:`, `- ## Tests:`, etc.) instead of including them as noise in the evidence pack
- `extract_errors` no longer captures common ALLCAPS abbreviations (`CHANGELOG`, `JSON`, `CSV`, `README`, etc.) as error identifiers; only genuine error tokens (`ECONNRESET`, `TimeoutException`, etc.) are extracted

## [0.5.0] - 2026-03-14

### Added

- `no_cjk_expand` parameter for `memory_search` to suppress CJK n-gram expansion and reduce context window consumption
- Field alias support in `field:term` query syntax — singular forms (`tag:`, `keyword:`, `file:`, `error:`, `skill:`, `decision:`, `pitfall:`, `command:`) are automatically resolved to their plural canonical names

### Fixed

- CJK characters in note titles now preserved in filenames instead of falling back to SHA1 hash (e.g., `0751_動作テスト用ノート.md` instead of `0751_53f9eb68.md`)
- `rg`/`python` fallback search engine now enriches results with metadata from the index when available, instead of returning empty title/date/tags fields
- `memory_init` now returns 3-level status: `created` (new directory), `initialized` (existing directory with missing files), `already_exists` (all files present)
- `memory_auto_restore` no longer emits a warning when `include_agent_state=True` but `agent_id` is not provided; agent state is silently skipped

## [0.4.2] - 2026-03-14

### Fixed

- `memory_update_weights` not returning warnings for unknown field keys (`warnings.warn` was invisible to MCP clients; now included in response as `{"weights": {...}, "warnings": [...]}`)
- `memory_state_set` returning only file path instead of JSON summary with `set`/`before`/`after` counts (now consistent with `memory_state_add`)
- Template placeholders (`\<comma,separated,keywords or empty>` etc.) remaining in notes when `context`, `tags`, or `keywords` are omitted

### Improved

- `memory_health_check` now returns `config_invalid_reason` field when `config_valid` is false
- `memory_evidence` description now explicitly states that either `paths` or `task_id` must be provided
- `memory_expire_stale` description now explicitly states the default (30) and minimum (1) for `stale_days`

## [0.4.1] - 2026-03-13

### Fixed

- `__init__.py` version string not updated to match `pyproject.toml` in v0.4.0 release

## [0.4.0] - 2026-03-13

### Added

- `compact` parameter for `memory_search` and `memory_search_global` to reduce response size by excluding verbose index fields (auto_keywords, work_log_keywords, plan_keywords, errors, skills, commands, test_names, skill_feedback)
- `mode` parameter for `memory_search` with presets: `quick` (compact + no explain), `detailed` (default), `debug` (explain + all fields)
- JSON summary return from `memory_state_add` and `memory_state_from_note` including added/removed counts and section details
- `max_cjk_terms` cap for CJK n-gram tokenization to prevent excessive expansion

### Fixed

- English template section name "Skill Feedback" not recognized by section parser, causing `sigfb_status` to report `"missing"` for English notes
- Template placeholder tokens (`SIGFB`, `SKILL`) incorrectly extracted as error strings from `- SIGFB: none` / `- SKILL: none` lines
- Japanese-only note titles producing empty slugs; now falls back to short SHA1 hash
- `expire_stale` accepting `stale_days=0` which would expire all items; now validates minimum of 1

### Changed

- Evidence pack now detects note language and uses matching section display names (English sections for English notes, Japanese for Japanese)

## [0.3.0] - 2026-03-13

### Added

- **A1: Dense retrieval auto-config** — `memory_init` gains `enable_dense` parameter to auto-configure dense embeddings on initialization
- **A2: Human-readable explain** — `memory_search` returns `explain_summary` with human-readable score breakdowns when `explain=True`
- **A3: Auto-index on note creation** — `create_note()` automatically calls `index_note()` after creation (opt-out via `auto_index=False`)
- **B1: Response size control** — `memory_auto_restore` gains `max_total_lines` parameter with priority-based truncation
- **B2: Note lifecycle management** — New `memory_list_stale_notes` and `memory_cleanup_notes` MCP tools for lightweight note cleanup
- **B3: State item auto-expiry** — New `memory_expire_stale` MCP tool to archive items not referenced within a configurable period
- **C1: Multi-project search** — New `memory_search_global` MCP tool for cross-project memory search
- **C2: Note template customization** — `memory_note_new` gains `lang` parameter supporting English (`en`) and Japanese (`ja`) templates
- **C3: Dynamic field weight tuning** — New `memory_update_weights` MCP tool to adjust search field weights based on feedback
- **D1: Storage statistics** — New `memory_stats` MCP tool for storage statistics and SIGFB signal summary
- **D2: Index integrity check** — New `memory_health_check` MCP tool to detect orphan entries, unindexed notes, and stale entries
- **D3: Backup/export** — New `memory_export` MCP tool supporting JSON and ZIP export formats

### Changed

- MCP tool count increased from 11 to 19

## [0.2.1] - 2026-03-06

### Added

- **`replace` parameter for `memory_state_add`**: Enables upsert semantics — removes existing items matching any of the given substring patterns before adding new items. This replaces the previous 2-step workflow (`memory_state_remove` + `memory_state_add`) with a single atomic operation.

## [0.2.0] - 2026-03-05

### Removed

- MCP tools: `memory_cleanup`, `memory_state_prune`, `memory_index_build`, `memory_agent_state_show`, `memory_agent_state_set`, `memory_agent_state_add`, `memory_agent_state_remove`
  - `memory_cleanup`/`memory_state_prune`/`memory_index_build`: maintenance operations, use CLI instead
  - `memory_agent_state_*`: not used in current architecture, agent state managed via hooks

### Improved

- MCP tool descriptions for `memory_state_add`, `memory_state_set`, `memory_state_remove` (clarify low-level nature, recommend `memory_state_from_note`)
- MCP tool description for `memory_auto_restore` (clarify as convenience wrapper)

## [0.1.3] - 2026-03-05

### Added

- `task_id` parameter to `memory_evidence` for automatic path resolution
- `dry_run` parameter to `memory_index_build` MCP tool

### Changed

- `memory_evidence`: `paths` parameter changed from required to optional

## [0.1.2] - 2026-03-05

### Added

- `memory_cleanup` MCP tool for agent state file TTL/generation cleanup with dry-run support

## [0.1.1] - 2026-03-02

### Fixed

- Fix `UnboundLocalError` in `upsert_dense()` where local variable `dense` shadowed the module import
- Resolve mypy type errors (rename shadowing variables in search.py and index.py)
- Fix all ruff linting and formatting errors

## [0.1.0] - 2026-03-02

### Added

- Initial package structure
- Core memory modules (config, state, note, search, index, evidence)
- CLI with `memory` command (init, note, state, search, index, evidence, serve, version)
- MCP server with FastMCP (12 tools)
- BM25+ scoring with field-level weighting
- Query parser with phrases, +must, -exclude, field:term, date ranges
- Optional Japanese tokenization (sudachipy)
- Optional dense embedding search (sentence-transformers)
- CI/CD with GitHub Actions
