"""Memory directory initialization and configuration utilities."""

from __future__ import annotations

import json
from pathlib import Path

TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "assets/state-template.md"

FALLBACK_TEMPLATE = "# 作業状態（ローリング）\nLast updated: <YYYY-MM-DD HH:MM>\n\n## 現在のフォーカス\n-\n\n## 未解決・次のアクション\n-\n\n## 主要な判断\n-\n\n## 注意点\n-\n\n## スキルバックログ\n-\n"

DEFAULT_CONFIG = {
    "weights": {
        "title": 6.0,
        "tags": 5.0,
        "keywords": 4.0,
        "auto_keywords": 3.5,
        "context": 3.0,
        "files": 6.0,
        "errors": 7.0,
        "skills": 4.0,
        "decisions": 3.0,
        "next": 2.5,
        "pitfalls": 2.5,
        "commands": 2.0,
        "summary": 2.0,
        "work_log_keywords": 2.5,
        "plan": 0.8,
        "tests": 0.6,
    },
    "query_expansion": {"decay": 0.4, "synonyms": {}},
    "tokenizer": {"backend": "auto"},
    "hybrid": {"rrf_k": 60, "dense_weight": 0.3},
}


def resolve_memory_dir() -> Path:
    """Resolve default memory dir with backward-compatible fallback order."""
    memory_dir = Path("memory")
    if memory_dir.exists():
        return memory_dir

    daily_note_dir = Path("daily_note")
    if daily_note_dir.exists():
        return daily_note_dir

    return memory_dir


def load_template() -> str:
    """Load state template from assets with fallback."""
    tpl = TEMPLATE_PATH.resolve()
    if tpl.exists():
        return tpl.read_text(encoding="utf-8")
    return FALLBACK_TEMPLATE


def init_memory_dir(memory_dir: Path) -> dict[str, str]:
    """Initialize memory directory structure and return status metadata."""
    state_path = memory_dir / "_state.md"
    index_path = memory_dir / "_index.jsonl"
    config_path = memory_dir / "_rag_config.json"

    if memory_dir.exists():
        state_content = state_path.read_text(encoding="utf-8") if state_path.exists() else ""
        return {
            "status": "already_exists",
            "memory_dir": str(memory_dir),
            "state_path": str(state_path),
            "state_content": state_content,
            "index_path": str(index_path),
            "config_path": str(config_path),
        }

    memory_dir.mkdir(parents=True, exist_ok=True)
    template_content = load_template()
    state_path.write_text(template_content, encoding="utf-8")
    index_path.write_text("", encoding="utf-8")
    config_path.write_text(
        json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    return {
        "status": "created",
        "memory_dir": str(memory_dir),
        "state_path": str(state_path),
        "state_content": template_content,
        "index_path": str(index_path),
        "config_path": str(config_path),
    }
