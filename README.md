# agentic-mem

Persistent memory system for AI agents — session notes, rolling state, and RAG search.

## Features

- **Session notes**: Create structured markdown notes per session with metadata extraction
- **Rolling state**: Track focus, open items, decisions, pitfalls across sessions
- **RAG search**: BM25+ scoring with field-level weighting, query expansion, fuzzy matching
- **MCP server**: Expose all operations as MCP tools for AI agent integration
- **CLI**: Full-featured command-line interface

## Installation

```bash
pip install agentic-mem
```

With optional features:

```bash
# Japanese tokenization support
pip install agentic-mem[japanese]

# Dense embedding search
pip install agentic-mem[dense]

# All extras
pip install agentic-mem[all]
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
      "args": ["agentic-mem", "serve"]
    }
  }
}
```

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
