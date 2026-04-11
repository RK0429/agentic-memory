"""Memory directory initialization and configuration utilities."""

from __future__ import annotations

import copy
import json
import os
import re
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any

STATE_TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "assets/state-template.md"
NOTE_TEMPLATE_PATHS = {
    "ja": Path(__file__).resolve().parent.parent / "assets/note-template.md",
    "en": Path(__file__).resolve().parent.parent / "assets/note-template-en.md",
}

FALLBACK_TEMPLATE = (
    "# 作業状態（ローリング）\n"
    "Last updated: <YYYY-MM-DD HH:MM>\n\n"
    "## 現在のフォーカス\n"
    "-\n\n"
    "## 未解決・次のアクション\n"
    "-\n\n"
    "## 主要な判断\n"
    "-\n\n"
    "## 注意点\n"
    "-\n\n"
    "## スキルバックログ\n"
    "-\n"
)

DEFAULT_WEIGHTS: dict[str, float] = {
    "task_id": 8.0,
    "agent_id": 2.0,
    "relay_session_id": 1.5,
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
}

DEFAULT_CONFIG = {
    "weights": DEFAULT_WEIGHTS,
    "query_expansion": {"decay": 0.4, "synonyms": {}},
    "tokenizer": {"backend": "auto"},
    "hybrid": {"rrf_k": 60, "dense_weight": 0.3},
}

DEFAULT_DENSE_CONFIG = {
    "enabled": True,
    "model": "cl-nagoya/ruri-v3-70m",
    "dim": 384,
}

FALLBACK_NOTE_TEMPLATES = {
    "ja": ("# <short title>\n- Date: <YYYY-MM-DD>\n- Time: <HH:MM> - <HH:MM>\n\n## 目標\n- \n"),
    "en": ("# <short title>\n- Date: <YYYY-MM-DD>\n- Time: <HH:MM> - <HH:MM>\n\n## Goals\n- \n"),
}
PROMOTED_VALUES_BEGIN = "<!-- BEGIN:PROMOTED_VALUES -->"
PROMOTED_VALUES_END = "<!-- END:PROMOTED_VALUES -->"
# Loose detection patterns: tolerate optional annotation text inside the
# comment, e.g. "<!-- BEGIN:PROMOTED_VALUES (agentic-memory managed) -->".
# Used by both ``_ensure_promoted_values_markers`` and the AgentsMdAdapter so
# that hand-annotated marker lines are recognized as the existing block instead
# of being treated as missing.
PROMOTED_VALUES_BEGIN_RE = re.compile(r"^<!--\s*BEGIN:PROMOTED_VALUES\b.*-->$")
PROMOTED_VALUES_END_RE = re.compile(r"^<!--\s*END:PROMOTED_VALUES\b.*-->$")


def _merge_config(defaults: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(defaults)
    for key, value in current.items():
        default_value = merged.get(key)
        if isinstance(default_value, dict) and isinstance(value, dict):
            merged[key] = _merge_config(default_value, value)
            continue
        merged[key] = copy.deepcopy(value)
    return merged


def _read_json_dict(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"Config must be a JSON object: {path}")
    return loaded


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(serialized)
        os.replace(tmp_path, str(path))
    except BaseException:
        with suppress(OSError):
            os.unlink(tmp_path)
        raise


def _write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp_path, str(path))
    except BaseException:
        with suppress(OSError):
            os.unlink(tmp_path)
        raise


def _load_state_template() -> str:
    tpl = STATE_TEMPLATE_PATH.resolve()
    if tpl.exists():
        return tpl.read_text(encoding="utf-8")
    return FALLBACK_TEMPLATE


def resolve_memory_dir() -> Path:
    """Resolve default memory dir with backward-compatible fallback order."""
    memory_dir = Path("memory")
    if memory_dir.exists():
        return memory_dir

    daily_note_dir = Path("daily_note")
    if daily_note_dir.exists():
        return daily_note_dir

    return memory_dir


def load_template(lang: str = "ja") -> str:
    """Load note template from assets with fallback."""
    normalized = lang.lower()
    tpl = NOTE_TEMPLATE_PATHS.get(normalized)
    if tpl is None:
        raise ValueError(f"Unsupported template language: {lang}")

    tpl = tpl.resolve()
    if tpl.exists():
        return tpl.read_text(encoding="utf-8")
    return FALLBACK_NOTE_TEMPLATES[normalized]


def load_config(memory_dir: Path) -> dict[str, Any]:
    """Load `_rag_config.json` merged with defaults."""
    config_path = memory_dir / "_rag_config.json"
    if not config_path.exists():
        return copy.deepcopy(DEFAULT_CONFIG)
    return _merge_config(DEFAULT_CONFIG, _read_json_dict(config_path))


def _ensure_promoted_values_markers(agents_path: Path) -> None:
    if not agents_path.exists():
        return

    content = agents_path.read_text(encoding="utf-8")
    has_begin = any(PROMOTED_VALUES_BEGIN_RE.match(line.strip()) for line in content.splitlines())
    has_end = any(PROMOTED_VALUES_END_RE.match(line.strip()) for line in content.splitlines())
    if has_begin and has_end:
        return

    suffix = "" if content.endswith("\n") else "\n"
    marker_block = f"{suffix}\n{PROMOTED_VALUES_BEGIN}\n{PROMOTED_VALUES_END}\n"
    _write_text_atomic(agents_path, content + marker_block)


def _resolve_agents_md_path(memory_dir: Path) -> Path | None:
    env_path = os.environ.get("AGENTS_MD_PATH")
    candidates: list[Path] = []
    if env_path:
        candidates.append(Path(env_path))
    candidates.extend(
        [
            memory_dir.parent / "AGENTS.md",
            memory_dir.parent / "CLAUDE.md",
        ]
    )
    for candidate in candidates:
        if not candidate.exists():
            continue
        return candidate.resolve() if candidate.is_symlink() else candidate
    return None


def init_memory_dir(memory_dir: Path, enable_dense: bool = False) -> dict[str, str]:
    """Initialize memory directory structure and return status metadata.

    Status levels:
      - ``created``: directory did not exist; created with all files.
      - ``initialized``: directory existed but one or more files were missing and created.
      - ``already_exists``: directory and all files already existed.

    ``state_content`` is included only for ``created`` and ``initialized``
    statuses.  When ``already_exists``, it is omitted to reduce context
    consumption; use ``memory_state_show`` to read the current state.
    """
    state_path = memory_dir / "_state.md"
    index_path = memory_dir / "_index.jsonl"
    config_path = memory_dir / "_rag_config.json"

    dir_existed = memory_dir.exists()
    files_existed_before = (
        (state_path.exists() and index_path.exists() and config_path.exists())
        if dir_existed
        else False
    )

    memory_dir.mkdir(parents=True, exist_ok=True)
    (memory_dir / "knowledge").mkdir(exist_ok=True)
    (memory_dir / "values").mkdir(exist_ok=True)

    if state_path.exists():
        template_content = state_path.read_text(encoding="utf-8")
    else:
        template_content = _load_state_template()
        state_path.write_text(template_content, encoding="utf-8")

    if not index_path.exists():
        index_path.write_text("", encoding="utf-8")

    if config_path.exists():
        config_payload = load_config(memory_dir)
    else:
        config_payload = copy.deepcopy(DEFAULT_CONFIG)

    if enable_dense:
        config_payload = _merge_config({"dense": DEFAULT_DENSE_CONFIG}, config_payload)

    if enable_dense or not config_path.exists():
        _write_json_atomic(config_path, config_payload)

    agents_path = _resolve_agents_md_path(memory_dir)
    if agents_path is not None:
        _ensure_promoted_values_markers(agents_path)

    if not dir_existed:
        status = "created"
    elif not files_existed_before:
        status = "initialized"
    else:
        status = "already_exists"

    result: dict[str, str] = {
        "status": status,
        "memory_dir": str(memory_dir),
        "state_path": str(state_path),
        "index_path": str(index_path),
        "config_path": str(config_path),
    }
    # Include state_content only for new/partial init (not for already_exists)
    if status != "already_exists":
        result["state_content"] = template_content
    return result


def update_weights(memory_dir: Path, updates: dict[str, float]) -> dict[str, Any]:
    """Partially update weight settings and return the full weight mapping.

    Returns a dict with ``weights`` (the full mapping) and ``warnings``
    (list of ignored unknown keys, if any).
    """
    config_path = memory_dir / "_rag_config.json"
    config_payload = load_config(memory_dir)

    raw_weights = config_payload.get("weights")
    if isinstance(raw_weights, dict):
        weights: dict[str, Any] = raw_weights
    else:
        weights = copy.deepcopy(DEFAULT_WEIGHTS)
        config_payload["weights"] = weights

    ignored: list[str] = []
    for key, value in updates.items():
        if key not in weights:
            ignored.append(key)
            continue
        weights[key] = float(value)

    _write_json_atomic(config_path, config_payload)
    result: dict[str, Any] = {
        "weights": {key: float(value) for key, value in weights.items()},
    }
    if ignored:
        result["warnings"] = [f"Ignoring unknown weight key: {k}" for k in ignored]
    return result
