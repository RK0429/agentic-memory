from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

config = importlib.import_module("agentic_memory.core.config")

SAMPLE_NOTE_CONTENT = """# Sample Session

- Date: 2026-01-01
- Time: 10:15 - 11:00
- Context: https://example.com/issues/123
- Tags: backend,auth
- Keywords: token,refresh

## 目標

- Fix login failure

## 計画

- Reproduce the issue
- Patch token validation

## 作業ログ

- Observed HTTP 500 and AuthError while refreshing tokens.

## 変更点

- Files:
  - src/auth.py
  - tests/test_auth.py
- Notes:
  - tighten refresh token parsing

## コマンド

- uv run pytest tests/test_auth.py
```bash
uv run ruff check .
```

## 検証

- Tests:
  - tests/test_auth.py::test_refresh_token
- Result:
  - pass

## 成果

- Login failure resolved for refresh tokens.

## 判断

- Use stricter token validation.

## 次のアクション

- Add integration coverage.

## 注意点・残課題

- Monitor 401 spikes after deploy.

## 想起フィードバック（任意）

- Query used: auth refresh token
- Useful notes: memory/2025-12-31/0900_auth.md
- Missed notes / gaps: none
- Retrieval improvements: add oauth keyword

## スキルフィードバック

- SIGFB: .agents/skills/software-engineer/SKILL.md | friction | auth debug checklist was missing

## スキル候補

- SKILL: software-engineer
"""


@pytest.fixture
def tmp_memory_dir(tmp_path: Path) -> Path:
    memory_dir = tmp_path / "memory"
    result = config.init_memory_dir(memory_dir)
    assert result["status"] == "created"
    assert (memory_dir / "_state.md").exists()
    assert (memory_dir / "_index.jsonl").exists()
    assert (memory_dir / "_rag_config.json").exists()
    assert (memory_dir / "knowledge").exists()
    assert (memory_dir / "values").exists()
    return memory_dir


@pytest.fixture
def sample_note_path(tmp_memory_dir: Path) -> Path:
    note_dir = tmp_memory_dir / "2026-01-01"
    note_dir.mkdir(parents=True, exist_ok=True)
    note_path = note_dir / "1015_sample-session.md"
    note_path.write_text(SAMPLE_NOTE_CONTENT, encoding="utf-8")
    return note_path


@pytest.fixture
def sample_state_path(tmp_memory_dir: Path) -> Path:
    return tmp_memory_dir / "_state.md"


@pytest.fixture
def sample_index_path(tmp_memory_dir: Path) -> Path:
    return tmp_memory_dir / "_index.jsonl"
