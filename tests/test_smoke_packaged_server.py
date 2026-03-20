from __future__ import annotations

import importlib.util
from pathlib import Path


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
