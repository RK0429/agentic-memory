# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
