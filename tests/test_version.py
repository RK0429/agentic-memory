from __future__ import annotations

from importlib.metadata import version

from agentic_memory import __version__


def test_runtime_version_matches_package_metadata() -> None:
    assert __version__ == version("agmemory")
