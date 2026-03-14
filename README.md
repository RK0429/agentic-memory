# agmemory

Persistent memory system for AI agents — session notes, rolling state, and RAG search.

## Features

- **Session notes**: Create structured markdown notes per session with metadata extraction
- **Rolling state**: Track focus, open items, decisions, pitfalls across sessions
- **RAG search**: BM25+ scoring with field-level weighting, query expansion, fuzzy matching
- **MCP server**: Expose all operations as MCP tools for AI agent integration
- **CLI**: Full-featured command-line interface

## Installation

```bash
pip install agmemory
```

With optional features:

```bash
# Japanese tokenization support
pip install agmemory[japanese]

# Dense embedding search
pip install agmemory[dense]

# All extras
pip install agmemory[all]
```

## Quick Start

### CLI

```bash
# Initialize memory directory
memory init

# Create a session note
memory note new --title "Fix authentication bug"

# Search notes
memory search --query "authentication timeout"

# Show current state
memory state show

# Update state from a note
memory state from-note memory/2026-03-02/1830_fix-authentication-bug.md
```

### MCP Server

Register in your `.mcp.json`:

```json
{
  "mcpServers": {
    "memory": {
      "command": "memory",
      "args": ["serve"]
    }
  }
}
```

Or with `uvx`:

```json
{
  "mcpServers": {
    "memory": {
      "command": "uvx",
      "args": ["agmemory", "serve"]
    }
  }
}
```

### Upgrading

After upgrading the package, reconnect the MCP server to pick up new tool
parameters and schema changes. In Claude Code, run `/mcp` and select
reconnect; other MCP hosts may require restarting the server process.

## Memory Directory Structure

```
memory/
├── _state.md              # Rolling state
├── _index.jsonl           # Lightweight search index
├── _rag_config.json       # Search configuration
├── _vocab.json            # Vocabulary cache for fuzzy matching
└── YYYY-MM-DD/
    └── HHMM_slug.md       # Session note
```

## License

Apache-2.0
