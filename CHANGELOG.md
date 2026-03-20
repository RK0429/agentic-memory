# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.7.0] - 2026-03-20

### Changed

- **Breaking**: SIGFB signals now require `id` field in `_index.jsonl`; existing indices must be rebuilt via `memory_health_check(fix=True)` or `memory_index_upsert`
- **Breaking**: Replaced `_improvement_backlog_resolved.json` with three new sidecars: `_sigfb_resolved.json`, `_backlog_contributors.json`, `_trigger_cooldown.json`
- `aggregate_signals()` accepts `resolved_ids` parameter to exclude resolved signals from aggregation
- `analyze_signals()` now includes `contributor_ids` in each candidate for signal-level tracking
- `cmd_remove()` on improvements section now marks contributor signals as resolved via `_sigfb_resolved.json`
- `_auto_improve_from_signals()` filters resolved signals before aggregation, preventing re-generation of resolved backlog items
- Trigger cooldown (e.g. `periodic_review`) is now managed via `_trigger_cooldown.json` instead of text-based resolution records

### Added

- `_signal_event_id()` generates deterministic 12-char IDs for each SIGFB signal based on note path, skill, type, description, and ordinal
- `build_entry()` assigns `id` to each `skill_feedback` entry during indexing

### Removed

- `_improvement_backlog_resolved.json` sidecar and all associated functions (`_load_improvement_resolutions`, `_save_improvement_resolutions`, `_remember_resolved_improvements`, `_forget_resolved_improvements`, `_resolved_improvement_key_set`, `_has_recently_resolved_periodic_review`)

## [0.6.7] - 2026-03-19

### Fixed

- `memory_evidence(task_id=...)` now raises a recovery-guided error when the `task_id` format is valid but no indexed notes match, instead of returning an ambiguous empty evidence pack

## [0.6.6] - 2026-03-19

### Fixed

- `memory_search` now rejects malformed query filters such as `task_id:not-a-task-id` with the same format hint used for explicit `task_id` parameters, avoiding false-positive matches

## [0.6.5] - 2026-03-19

### Fixed

- `memory_search` no longer crashes on metadata-only queries such as `task_id:TASK-123` or `task_id:<relay-uuid>`; `total_found` is now populated correctly for index-backed filter-only results

### Changed

- `memory_search` tool description now documents that `task_id`, `agent_id`, and `relay_session_id` can be passed either as explicit parameters or as query filters, and clarifies accepted `task_id` formats

## [0.6.4] - 2026-03-19

### Fixed

- `memory_note_new`, `memory_search`, and `memory_evidence` now accept relay task UUIDs as `task_id`, in addition to legacy `TASK-123` / `GOAL-123` identifiers
- Invalid `task_id` errors now explain the accepted formats, making recovery faster when a caller passes a relay task UUID or a malformed identifier

## [0.6.3] - 2026-03-19

### Fixed

- `memory_evidence` now accepts `paths` as either a list of note paths or a single path string, matching common MCP client call patterns and avoiding avoidable validation friction.
- `memory_state_from_note(auto_improve_add=True)` no longer re-adds improvement backlog items that were explicitly resolved and removed. Resolved entries are tracked separately, and `periodic_review` now respects a 14-day cooldown after closure.

## [0.6.2] - 2026-03-16

### Changed

- `memory_state_add` now accepts common state section aliases such as `open_actions` and `current_focus`, reducing friction when callers use descriptive names instead of short keys
- `memory_state_add` now accepts a single string for `replace` and treats it as a one-item pattern list, removing the need for callers to wrap simple replacements in an array
- Unknown state section key errors now include representative accepted keys and aliases, making recovery faster when a caller supplies an invalid section name

## [0.6.1] - 2026-03-15

### Changed

- `memory_search_global`: `memory_dirs` parameter is now optional (defaults to `None`). At least one of `memory_dirs` or `memory_dir` must be provided. Empty strings in `memory_dirs` are filtered out
- `memory_evidence`: `max_lines` default increased from 8 to 12, reducing information loss for sections with longer content
- `memory_state_from_note`: docstring now documents auto-improve behavior (`no_auto_improve`, `auto_improve_add`) and response fields (`updated_sections`, `section_counts`, `stale_count`, `warnings`)
- `memory_auto_restore`: docstring now documents response structure fields (`project_state`, `agent_state`, `active_tasks`, etc.)

## [0.6.0] - 2026-03-15

### Added

- Search results are now returned as flat objects (`{"score": 77.9, "path": "...", ...}`) instead of `[score, entry]` tuples in MCP tool responses, improving agent ergonomics. Internal APIs retain tuple format for backward compatibility
- `memory_search_global` now accepts `memory_dir` as a convenience fallback — if provided, it is appended to `memory_dirs`, allowing single-directory search without wrapping in a list
- `memory_state_from_note` now includes a `warnings` field in JSON responses for cap-exceeded, auto-prune, auto-improve, and stale-item notifications

### Changed

- **Breaking (internal API)**: `enforce_cap()` now returns a `(kept, dropped)` tuple instead of just the kept list. All internal callers updated
- `_auto_prune()` now returns a list of dropped items instead of printing to stderr
- `memory_state_from_note` no longer emits warnings to stderr; all diagnostics (cap exceeded, auto-prune, auto-improve candidates, stale items) are included in the structured JSON response
- Quick mode (`mode="quick"`) now strips `None` and empty-string (`""`) fields from each search result entry, further reducing context consumption
- Fallback search (triggered when index returns 0 results) now uses original query terms instead of expanded terms, reducing noise from CJK n-gram fragment matches

## [0.5.11] - 2026-03-15

### Added

- `boundary` CJK tokenizer backend — splits Japanese text at script boundaries (kanji/hiragana/katakana transitions) instead of pure n-gram expansion, producing ~3-5x fewer tokens while maintaining search recall. Now the default backend when `sudachipy` is not installed
- `fix` parameter for `memory_health_check` — when `True`, automatically re-indexes stale/unindexed notes and removes orphan index entries
- `DETAILED_EXCLUDE_FIELDS` constant — `auto_keywords` and `work_log_keywords` are now excluded from `mode="detailed"` search results (kept in `mode="debug"`)

### Changed

- `memory_search` docstring now documents mode→behavior mapping (`quick`/`detailed`/`debug` presets and their effect on compact, feedback expansion, and explain settings)
- `memory_state_add` docstring now includes `replace` parameter usage example and type clarification (`replace` must be a list, not a single string)
- `memory_evidence` error message when both `paths` and `task_id` are omitted now suggests correct usage
- `memory_health_check` annotation changed from `READONLY` to `IDEMPOTENT` to reflect the new `fix` parameter

## [0.5.10] - 2026-03-15

### Changed

- Compact mode (`mode="quick"`) now omits empty `warnings` list from search results, reducing response size
- `expanded` field (verbose QueryTerm objects) is now only included in `mode="debug"` responses; `mode="detailed"` retains the lightweight `expanded_terms` string list. This reduces `detailed` mode response size by ~120 lines for a typical query

## [0.5.9] - 2026-03-15

### Added

- MCP tool annotations (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`) on all 19 tools for machine-readable safety classification
- Usage/non-usage conditions in tool descriptions (e.g., "Use this to...", "Do not use for...")

### Changed

- **Breaking**: `memory_note_new` now returns JSON `{"path", "title", "date"}` instead of a plain path string
- **Breaking**: `memory_search` removes 6 parameters: `prf`, `no_prf`, `rerank`, `compact`, `explain`, `no_feedback_expand` — use `mode` presets instead. `no_rerank` is retained for disabling auto-enabled reranking
- **Breaking**: `memory_search_global` removes 3 parameters: `compact`, `explain`, `no_feedback_expand` — use `mode` presets instead
- `engine` parameter in `memory_search` now uses `Literal["auto", "index", "hybrid", "rg", "python"]` enum constraint
- `fmt` parameter in `memory_export` now uses `Literal["json", "zip"]` enum constraint
- `lang` parameter in `memory_note_new` now uses `Literal["ja", "en"]` enum constraint
- Compact mode (`mode="quick"`) now strips settings echo-back fields (`expand_enabled`, `feedback_expand`, `top`, `snippets`, `rerank_enabled`, `rerank_auto_enabled`, `compact`) from search results
- Compact mode now omits empty detail dict from result tuples (2-element `[score, entry]` instead of 3-element `[score, entry, {}]`)

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
