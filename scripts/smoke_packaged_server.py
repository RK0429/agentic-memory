#!/usr/bin/env python3
"""Smoke-test packaged MCP server metadata from a built wheel."""

from __future__ import annotations

import argparse
import re
import tempfile
from pathlib import Path

import anyio
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

TARGET_OPEN_WORLD_TOOLS = ("memory_search", "memory_search_global")
SMOKE_TIMEOUT_SECONDS = 30.0
WHEEL_VERSION_RE = re.compile(r"^agmemory-(?P<version>[^-]+)-")


def _wheel_version_key(path: Path) -> tuple[int, ...]:
    match = WHEEL_VERSION_RE.match(path.name)
    if match is None:
        raise ValueError(f"Could not parse wheel version from filename: {path.name}")
    return tuple(int(part) for part in match.group("version").split("."))


def _resolve_wheel(explicit: str | None) -> Path:
    if explicit is not None:
        wheel = Path(explicit).expanduser().resolve()
        if not wheel.is_file():
            raise FileNotFoundError(f"Wheel not found: {wheel}")
        return wheel

    dist_dir = Path("dist")
    wheels = sorted(
        dist_dir.glob("agmemory-*.whl"),
        key=_wheel_version_key,
        reverse=True,
    )
    if not wheels:
        raise FileNotFoundError("No agmemory wheel found under ./dist. Run `uv build` first.")
    return wheels[0].resolve()


async def _list_all_tools(session: ClientSession) -> dict[str, object]:
    tools: dict[str, object] = {}
    cursor: str | None = None
    while True:
        result = await session.list_tools(cursor=cursor)
        for tool in result.tools:
            tools[tool.name] = tool
        cursor = result.nextCursor
        if cursor is None:
            return tools


def _assert_packaged_annotations(tools: dict[str, object]) -> None:
    for name in TARGET_OPEN_WORLD_TOOLS:
        tool = tools.get(name)
        if tool is None:
            raise AssertionError(f"Packaged MCP server is missing expected tool: {name}")
        annotations = getattr(tool, "annotations", None)
        if annotations is None:
            raise AssertionError(f"Tool {name} is missing annotations in tools/list result")
        if annotations.openWorldHint is not True:
            raise AssertionError(
                f"Tool {name} expected openWorldHint=True, got {annotations.openWorldHint!r}"
            )
        if annotations.readOnlyHint is not True:
            raise AssertionError(
                f"Tool {name} expected readOnlyHint=True, got {annotations.readOnlyHint!r}"
            )
        if annotations.destructiveHint is not False:
            raise AssertionError(
                f"Tool {name} expected destructiveHint=False, got {annotations.destructiveHint!r}"
            )


async def _run_smoke_test(wheel: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="agmemory-packaged-smoke-") as memory_dir:
        server = StdioServerParameters(
            command="uv",
            args=[
                "tool",
                "run",
                "--from",
                str(wheel),
                "memory",
                "serve",
                "--transport",
                "stdio",
            ],
            env={"MEMORY_DIR": memory_dir},
            cwd=memory_dir,
        )
        async with (
            stdio_client(server) as (read_stream, write_stream),
            ClientSession(read_stream, write_stream) as session,
        ):
            with anyio.fail_after(SMOKE_TIMEOUT_SECONDS):
                await session.initialize()
                tools = await _list_all_tools(session)

    _assert_packaged_annotations(tools)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Smoke-test the packaged agentic-memory MCP server by launching the built "
            "wheel and validating tools/list annotations."
        )
    )
    parser.add_argument(
        "wheel",
        nargs="?",
        help=(
            "Optional path to the built agmemory wheel. Defaults to the newest dist/agmemory-*.whl."
        ),
    )
    args = parser.parse_args()

    wheel = _resolve_wheel(args.wheel)
    anyio.run(_run_smoke_test, wheel)
    print(
        "Packaged MCP smoke test passed:",
        wheel.name,
        ", ".join(TARGET_OPEN_WORLD_TOOLS),
    )


if __name__ == "__main__":
    main()
