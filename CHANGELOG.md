# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
