from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from agentic_memory.cli import main


def _run(runner: CliRunner, memory_dir: Path, args: list[str]):
    return runner.invoke(main, ["--memory-dir", str(memory_dir), *args])


def _init_memory(runner: CliRunner, memory_dir: Path) -> None:
    result = _run(runner, memory_dir, ["init"])
    assert result.exit_code == 0


def _write_note_for_state(memory_dir: Path, name: str = "from_note.md") -> Path:
    note_path = memory_dir / name
    note_path.write_text(
        (
            "# State Source\n\n"
            "- Date: 2026-03-02\n"
            "- Time: 10:00 - 11:00\n\n"
            "## 目標\n- CLI test goal\n\n"
            "## 判断\n- Use simple assertions\n\n"
            "## 次のアクション\n- Add server tests\n\n"
            "## 注意点・残課題\n- Keep deterministic inputs\n\n"
            "## スキル候補\n- pytest\n"
        ),
        encoding="utf-8",
    )
    return note_path


def _write_note_for_evidence(memory_dir: Path, name: str = "evidence.md") -> Path:
    note_path = memory_dir / name
    note_path.write_text(
        (
            "# Evidence Source\n\n"
            "- Date: 2026-03-02\n"
            "- Time: 09:00 - 09:30\n\n"
            "## 目標\n- verify evidence term\n\n"
            "## 次のアクション\n- finalize tests\n"
        ),
        encoding="utf-8",
    )
    return note_path


def test_cli_version() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["version"])
    assert result.exit_code == 0
    assert result.output.strip() == "0.1.0"


def test_cli_help() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    for command in ["init", "note", "state", "search", "index", "evidence", "serve", "version"]:
        assert command in result.output


def test_cli_init(tmp_path: Path) -> None:
    runner = CliRunner()
    memory_dir = tmp_path / "mem"
    result = _run(runner, memory_dir, ["init"])
    assert result.exit_code == 0
    assert (memory_dir / "_state.md").exists()
    assert (memory_dir / "_index.jsonl").exists()


def test_cli_init_already_exists(tmp_path: Path) -> None:
    runner = CliRunner()
    memory_dir = tmp_path / "mem"
    _init_memory(runner, memory_dir)

    result = _run(runner, memory_dir, ["init"])
    assert result.exit_code == 0
    assert "Already exists" in result.output


def test_cli_note_new(tmp_path: Path) -> None:
    runner = CliRunner()
    memory_dir = tmp_path / "mem"
    _init_memory(runner, memory_dir)

    result = _run(runner, memory_dir, ["note", "new", "--title", "Test"])
    assert result.exit_code == 0

    created = Path(result.output.strip())
    assert created.exists()
    assert created.suffix == ".md"


def test_cli_state_show_empty(tmp_memory_dir: Path) -> None:
    runner = CliRunner()
    memory_dir = tmp_memory_dir

    result = _run(runner, memory_dir, ["state", "show"])
    assert result.exit_code == 0
    assert "- (empty)" in result.output
    assert "現在のフォーカス" in result.output


def test_cli_state_add(tmp_memory_dir: Path) -> None:
    runner = CliRunner()
    memory_dir = tmp_memory_dir

    add = _run(
        runner,
        memory_dir,
        ["state", "add", "--section", "focus", "--item", "Item A", "--item", "Item B"],
    )
    assert add.exit_code == 0

    show = _run(runner, memory_dir, ["state", "show", "--section", "focus"])
    assert show.exit_code == 0
    assert "Item A" in show.output
    assert "Item B" in show.output


def test_cli_state_set(tmp_memory_dir: Path) -> None:
    runner = CliRunner()
    memory_dir = tmp_memory_dir

    _run(runner, memory_dir, ["state", "add", "--section", "focus", "--item", "Old Item"])
    set_result = _run(
        runner, memory_dir, ["state", "set", "--section", "focus", "--item", "New Item"]
    )
    assert set_result.exit_code == 0

    show = _run(runner, memory_dir, ["state", "show", "--section", "focus"])
    assert show.exit_code == 0
    assert "New Item" in show.output
    assert "Old Item" not in show.output


def test_cli_state_remove(tmp_memory_dir: Path) -> None:
    runner = CliRunner()
    memory_dir = tmp_memory_dir

    _run(
        runner,
        memory_dir,
        ["state", "add", "--section", "focus", "--item", "Keep This", "--item", "Remove This"],
    )
    removed = _run(
        runner, memory_dir, ["state", "remove", "--section", "focus", "--pattern", "Remove"]
    )
    assert removed.exit_code == 0
    assert removed.output.splitlines()[0].strip() == "1"

    show = _run(runner, memory_dir, ["state", "show", "--section", "focus"])
    assert show.exit_code == 0
    assert "Keep This" in show.output
    assert "Remove This" not in show.output


def test_cli_state_from_note(tmp_memory_dir: Path) -> None:
    runner = CliRunner()
    memory_dir = tmp_memory_dir

    note_path = _write_note_for_state(memory_dir)
    result = _run(runner, memory_dir, ["state", "from-note", str(note_path), "--no-auto-improve"])
    assert result.exit_code == 0

    show = _run(runner, memory_dir, ["state", "show", "--section", "open"])
    assert show.exit_code == 0
    assert "Add server tests" in show.output


def test_cli_search(tmp_memory_dir: Path) -> None:
    runner = CliRunner()
    memory_dir = tmp_memory_dir

    result = _run(
        runner, memory_dir, ["search", "--query", "__no_result_expected__", "--engine", "python"]
    )
    assert result.exit_code == 0
    assert "No matches." in result.output


def test_cli_search_json(tmp_memory_dir: Path) -> None:
    runner = CliRunner()
    memory_dir = tmp_memory_dir

    result = _run(
        runner,
        memory_dir,
        ["search", "--query", "__no_result_expected__", "--engine", "python", "--json"],
    )
    assert result.exit_code == 0

    payload = json.loads(result.output)
    assert payload["query"] == "__no_result_expected__"
    assert isinstance(payload["results"], list)


def test_cli_index_build(tmp_memory_dir: Path) -> None:
    runner = CliRunner()
    memory_dir = tmp_memory_dir
    note_result = _run(runner, memory_dir, ["note", "new", "--title", "Index Build"])
    assert note_result.exit_code == 0

    result = _run(runner, memory_dir, ["index", "build", "--no-dense"])
    assert result.exit_code == 0
    assert (memory_dir / "_index.jsonl").exists()
    assert str(memory_dir / "_index.jsonl") in result.output


def test_cli_index_build_dry_run(tmp_memory_dir: Path) -> None:
    runner = CliRunner()
    memory_dir = tmp_memory_dir

    note_result = _run(runner, memory_dir, ["note", "new", "--title", "Dry Run"])
    assert note_result.exit_code == 0
    note_path = Path(note_result.output.strip())

    result = _run(runner, memory_dir, ["index", "build", "--dry-run"])
    assert result.exit_code == 0
    assert str(note_path) in result.output
    assert (memory_dir / "_index.jsonl").read_text(encoding="utf-8") == ""


def test_cli_index_upsert(tmp_memory_dir: Path) -> None:
    runner = CliRunner()
    memory_dir = tmp_memory_dir

    note_result = _run(runner, memory_dir, ["note", "new", "--title", "Upsert Note"])
    assert note_result.exit_code == 0
    note_path = Path(note_result.output.strip())

    result = _run(
        runner,
        memory_dir,
        ["index", "upsert", "--note", str(note_path), "--no-dense"],
    )
    assert result.exit_code == 0

    index_text = (memory_dir / "_index.jsonl").read_text(encoding="utf-8")
    assert note_path.name in index_text


def test_cli_evidence(tmp_memory_dir: Path) -> None:
    runner = CliRunner()
    memory_dir = tmp_memory_dir

    note_path = _write_note_for_evidence(memory_dir)
    result = _run(
        runner,
        memory_dir,
        ["evidence", "--query", "verify", "--paths", str(note_path)],
    )
    assert result.exit_code == 0
    assert "# DailyNote Evidence Pack" in result.output
    assert str(note_path) in result.output
