from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


def _load_smoke_script():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "smoke_packaged_server.py"
    spec = importlib.util.spec_from_file_location("smoke_packaged_server", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_resolve_wheel_prefers_highest_version_over_mtime(tmp_path: Path, monkeypatch) -> None:
    module = _load_smoke_script()
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()

    older_version = dist_dir / "agmemory-0.12.1-py3-none-any.whl"
    newer_version = dist_dir / "agmemory-0.12.2-py3-none-any.whl"
    newer_version.write_text("", encoding="utf-8")
    older_version.write_text("", encoding="utf-8")

    monkeypatch.chdir(tmp_path)

    resolved = module._resolve_wheel(None)

    assert resolved == newer_version.resolve()


def test_help_mentions_highest_version_default() -> None:
    module = _load_smoke_script()

    help_text = module._build_parser().format_help()

    assert "highest-version dist/agmemory-*.whl" in help_text
    assert "newest dist/agmemory-*.whl" not in help_text


def test_main_reports_missing_wheel_without_traceback(monkeypatch, capsys) -> None:
    module = _load_smoke_script()

    monkeypatch.setattr(sys, "argv", ["smoke_packaged_server.py", "/tmp/does-not-exist.whl"])

    with pytest.raises(SystemExit) as exc:
        module.main()

    captured = capsys.readouterr()

    assert exc.value.code == 2
    assert "Wheel not found" in captured.err
    assert "usage:" in captured.err
    assert "Traceback" not in captured.err


def test_main_reports_invalid_wheel_name_without_traceback(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    module = _load_smoke_script()
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    (dist_dir / "agmemory-bad.whl").write_text("", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["smoke_packaged_server.py"])

    with pytest.raises(SystemExit) as exc:
        module.main()

    captured = capsys.readouterr()

    assert exc.value.code == 2
    assert "Could not parse wheel version" in captured.err
    assert "usage:" in captured.err
    assert "Traceback" not in captured.err
