# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
