# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.17.0] - 2026-04-11

### Breaking

> **Migration**:
> - `memory_knowledge_delete` now returns a preview by default. Pass `confirm=true` to perform the actual deletion; omitted `confirm` or `confirm=false` only returns the preview.
> - `memory_knowledge_add` and `memory_values_add` now reject secret-containing input with `validation_error` instead of returning warn-only success. Sanitize content before retrying.

### Added

- `memory_values_add` success payload now echoes the normalized `category`, matching Knowledge add's normalized `domain`

### Changed

- `KnowledgeService.update()` and `memory_knowledge_update` now enumerate valid update fields in the missing-field validation message

### Fixed

- `memory_knowledge_delete` now supports preview/confirm two-phase deletion before removing the entry and cleaning related backlinks
- MCP add wrappers for Knowledge and Values now reject secret-containing input with structured `validation_error`; service-layer direct usage remains warn-only
- `memory_values_add` now checks both `description` and `evidence[].summary` for secrets before creating the entry

### Documentation

- `memory_knowledge_add` docstring now documents the implicit defaults `accuracy="uncertain"` and `user_understanding="unknown"` when callers omit them

## [0.16.3] - 2026-04-11

### Fixed

- AGENTS.md edit lock is now placed inside the configured memory directory, so promote/demote/delete/health operations no longer leave an `AGENTS.md.lock` file in the workspace root.

## [0.16.2] - 2026-04-11

### Fixed

- Values evidence eviction now keeps the newest 10 entries by date when appended evidence would otherwise exceed the storage limit
- Similar-value warnings now compare entries only within the same category, reducing false positives across unrelated categories
- `memory_values_update` and `memory_values_promote` now return more actionable validation errors and recovery hints

### Documentation

- Documented kebab-case normalization for `domain` and `category` parameters in MCP tool docstrings

## [0.16.1] - 2026-04-11

### Changed

- Promotion/demotion/delete preview `entry_line` generation is now consolidated through `AgentsMdAdapter.format_entry_line`, matching AGENTS.md formatting (newline replacement, HTML comment stripping, 200-char truncation)
- Promotion eligibility threshold docstrings now reference `PromotionManager.CONFIDENCE_THRESHOLD` and `PromotionManager.EVIDENCE_THRESHOLD` constant names alongside literal values

### Fixed

- `memory_knowledge_search` docstring referred to "each result" instead of "each entry", inconsistent with v0.16.0 response key rename

### Removed

- Unused `ValuesService._existing_agents_entry` and `ValuesService._entry_line` methods (functionality exists in `PromotionService`)

## [0.16.0] - 2026-04-11

### Breaking

> **Migration**: `memory_knowledge_search` response key changed from `results` to `entries`. `memory_values_delete` now requires `confirm=true` for all deletions, including non-promoted entries. `memory_values_update.add_evidence` now accepts only `list[dict]`.

- `memory_knowledge_search` response key changed from `results` to `entries`, unifying with `memory_values_search` and `memory_values_list`
- `memory_values_delete` now returns a preview when `confirm=false` for both promoted and non-promoted entries. Pass `confirm=true` to execute deletion
- `memory_values_update` now accepts only `list[dict]` for `add_evidence`; single-dict input is no longer supported

### Added

- `memory_knowledge_add` responses now include the normalized `domain` field

### Fixed

- `memory_knowledge_update` now returns `error_type: "not_found"` for non-existent IDs
- `memory_values_search` now returns the same validation payload style as Knowledge search, with improved quoting, punctuation, and recovery hints
- Generic Values validation hints now use the clearer default wording `Verify the values parameters and retry.`

### Changed

- Promotion eligibility thresholds are documented consistently in `memory_values_add`, `memory_values_update`, and `memory_values_promote` docstrings as `confidence >= 0.8` and `evidence_count >= 5`

## [0.15.0] - 2026-04-11

### Breaking

> **Migration**: workspace 側の AGENTS.md で `memory_distill_knowledge` / `memory_distill_values` への参照を `memory_distill_prepare` / `memory_distill_commit` に更新する必要がある。`agentic-core/.agents/skills/agentic-setup/references/agents_md_template.md` も同期が必要。

- `memory_distill_knowledge` and `memory_distill_values` MCP tools replaced by `memory_distill_prepare` and `memory_distill_commit`. The new prepare/commit pattern delegates LLM extraction to the calling agent instead of using an internal extractor port
- `Source.type` field changed from `SourceType` to new `ReferenceType` enum. API parameter `sources[].type` now accepts `memory_note`, `web`, `user_direct`, `document`, `code`, `other` instead of the previous `SourceType` values

### Added

- `memory_distill_prepare` MCP tool: collects notes and returns snapshot with instructions and candidate schema for agent-side LLM extraction
- `memory_distill_commit` MCP tool: validates and persists knowledge/values candidates with dry_run support, duplicate detection, and secret warnings
- `ReferenceType` enum (`memory_note`, `web`, `user_direct`, `document`, `code`, `other`) for `Source.type` reference classification, distinct from entry-level `SourceType` provenance
- CJK false-positive suppression in Values similarity detection using topic overlap ratio check
- `add_evidence` in `memory_values_update` now accepts both a single dict and a list of dicts

### Fixed

- `memory_knowledge_add`, `memory_values_add`, and `memory_knowledge_update` now return structured `validation_error` with hint containing expected schema and missing field names instead of raw `KeyError`/`TypeError`
- Invalid `source_type` errors now include valid enum values in the error hint
- Values promote ineligibility message now includes current/threshold values and next-action hint

### Changed

- `memory_values_list` default `min_confidence` changed from 0.3 to 0.0, returning all entries by default
- `memory_knowledge_add` default `source_type` changed to `user_taught`
- Legacy `SourceType` values in `Source.type` are automatically mapped to `ReferenceType` equivalents on read for backward compatibility
- Improved MCP tool docstrings: nested dict schema and valid enum values for `evidence`/`sources` parameters, `promotion_candidate`/`demotion_candidate` notification fields, `_resolve_dir` path resolution order, `add_evidence` list support

### Removed

- `DistillationService`, `DistillationExtractorPort`, `MockExtractorPort`, `UnconfiguredExtractorPort`, `KnowledgeCandidate` (extractor), `ValuesCandidate` (extractor) classes
- `DistillationTrigger` class
- `DistillationReport` and `ReportEntry` classes

## [0.14.1] - 2026-04-11

### Fixed

- `_ensure_promoted_values_markers` and `AgentsMdAdapter._load_marked_lines` now recognize hand-annotated PROMOTED_VALUES markers such as `<!-- BEGIN:PROMOTED_VALUES (agentic-memory managed — do not edit manually) -->`. Previously the substring/equality check only matched the bare canonical form, causing `init_memory_dir` to silently append a duplicate bare-form marker block to AGENTS.md and leaving the adapter operating on the wrong block.

### Changed

- `_ensure_promoted_values_markers` now raises `ValueError` when AGENTS.md is in a half-open marker state (exactly one of BEGIN/END present) instead of appending a fresh bare-form block on top of the malformed file. This matches the existing strict behavior of `_load_marked_lines` and surfaces user errors instead of compounding them.
- Marker detection regex now relies on `re.fullmatch` instead of `re.match` with explicit `^`/`$` anchors, and `_ensure_promoted_values_markers` performs the existence check in a single pass over the file.

## [0.14.0] - 2026-04-10

### Added

- Introduced the Knowledge & Values extension: CRUD modules for Values and Knowledge entries, a distillation pipeline (`core/distillation/`), and new MCP tools for managing Values entries and triggering distillation.
- Added secret detection to Values and Knowledge services so that entries containing potential secrets cannot be promoted.
- Added benchmark tests for Knowledge / Values search with response-time thresholds, and registered a dedicated `benchmark` pytest marker.
- New health checks covering the Knowledge & Values storage surface.

### Changed

- `delete` operations on Values and Knowledge entries now accept an optional `reason` parameter and return relevant metadata. Existing callers that omit `reason` continue to work unchanged.

## [0.13.0] - 2026-04-08

### Added

- `memory_search_global` now supports `no_expand`, `no_fuzzy`, and `no_rerank` parameters, matching the fine-grained search control available in `memory_search`

## [0.12.3] - 2026-03-20

### Fixed

- `scripts/smoke_packaged_server.py` now reports invalid wheel arguments through concise argparse usage errors instead of raw Python tracebacks
- The smoke test CLI help text now documents that the default auto-selected artifact is the highest-version wheel under `dist/`

## [0.12.2] - 2026-03-20

### Added

- Added a packaged-runtime MCP smoke test that launches the built wheel, calls `tools/list`, and asserts the published `memory_search*` tool annotations from the installed artifact

## [0.12.1] - 2026-03-20

### Fixed

- `memory_note_new` now rolls back the created note file when immediate indexing fails, avoiding orphan notes on I/O errors

## [0.12.0] - 2026-03-20

### Changed

- `memory_search` and `memory_search_global` now declare `openWorldHint=true`, matching rerank auto-enable behavior that may lazy-load external models

### Fixed

- `memory_note_new` now validates invalid `task_id` before writing a note, returning a structured JSON validation error without leaving an orphaned note file
- `memory_evidence` now rejects simultaneous `paths` and `task_id` arguments instead of silently preferring `paths`
- `memory_state_show(as_json=False)` now returns rendered markdown without duplicating structured `sections` in the same payload

## [0.11.0] - 2026-03-20

### Changed

- **Breaking**: `memory_evidence` now returns a JSON success envelope with generated Markdown under `markdown`, aligning success and error payloads
- **Breaking**: `memory_state_show` now defaults to `as_json=True`, returning structured sections by default; pass `as_json=False` to include rendered markdown under `output`
- `memory_search_global` now applies a tighter compact projection in `quick` mode so cross-workspace searches return smaller default payloads

### Added

- Added end-to-end regression coverage for `memory_note_new` blank-header indexing and updated server tests for the new response contracts

### Fixed

- Blank `Context` / `Tags` / `Keywords` header lines in newly created notes no longer bleed into adjacent header fields during indexing or evidence header extraction

## [0.10.0] - 2026-03-20

### Changed

- JSON を返す MCP ツールの成功応答は `ok: true` を含む envelope に統一
- `memory_search_global` は `memory_dirs` に単一文字列も受け付けるようになった
- internal API の legacy auto-improve boolean パラメータを削除し、`auto_improve_mode` に統一

### Fixed

- `memory_state_from_note` は stale な既存 index entry を検出した場合に、その note の index を自動 refresh してから auto-improve を評価するようになった
- `_capture_state_cmd` は成功時に stderr warning が混在しても JSON envelope を壊さないようになった

## [0.9.0] - 2026-03-20

### Changed

- **Breaking**: `memory_state_show` now returns JSON on success as well as failure; default mode includes rendered markdown under `output`, and `as_json=True` returns structured sections only
- **Breaking**: `memory_state_from_note` MCP/CLI interfaces now accept only `auto_improve_mode=detect|add|skip`; legacy boolean aliases are no longer exposed
- `memory_state_from_note` now reports `auto_improve.candidates`, `cap_exceeded`, and `auto_pruned` as structured fields instead of relying on free-form warning strings
- `memory_state_from_note` is now marked as destructive in MCP annotations, matching its real side effects such as auto-prune and legacy sidecar migration
- `memory_index_upsert` now returns a specific recovery hint for invalid `task_id` values
- `memory_evidence` and `memory_search_global` now return structured JSON error payloads instead of raw `ValueError` exceptions
- `memory_state_show` now renders its `output` from the structured snapshot it already read, removing the second state read and avoiding TOCTOU drift

## [0.8.0] - 2026-03-20

### Changed

- **Breaking**: MCP error responses for all server tools that wrap `_capture_state_cmd` (`memory_state_show`, `memory_state_add`, `memory_state_set`, `memory_state_remove`, `memory_state_from_note`) plus `memory_index_upsert` now return structured JSON payloads with `error_type`, `message`, `hint`, and `exit_code`
- `memory_state_from_note` now accepts `auto_improve_mode=detect|add|skip`, reports `auto_improve` metadata in its JSON response, and includes legacy resolution migration summaries when `_improvement_backlog_resolved.json` is encountered
- `memory_index_upsert` and `memory_state_from_note` tool descriptions now document migration/recovery usage more explicitly

## [0.7.2] - 2026-03-20

### Fixed

- Upgrading from pre-0.7 improvement backlog resolution now migrates legacy `_improvement_backlog_resolved.json` entries into the 0.7.x sidecars during `auto_improve`, preventing previously resolved backlog items from resurfacing after upgrade

## [0.7.1] - 2026-03-20

### Added

- `memory_health_check(force_reindex=True)` rebuilds the entire index from scratch, useful after breaking schema changes that require all entries to be regenerated

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

[Unreleased]: https://github.com/RK0429/agentic-memory/compare/v0.17.0...HEAD
[0.17.0]: https://github.com/RK0429/agentic-memory/compare/v0.16.3...v0.17.0
[0.16.3]: https://github.com/RK0429/agentic-memory/compare/v0.16.2...v0.16.3
[0.16.2]: https://github.com/RK0429/agentic-memory/compare/v0.16.1...v0.16.2
[0.16.1]: https://github.com/RK0429/agentic-memory/compare/v0.16.0...v0.16.1
