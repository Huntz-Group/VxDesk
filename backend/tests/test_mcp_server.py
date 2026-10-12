"""MCP server smoke tests (construction + tool dispatch, no stdio needed)."""

from __future__ import annotations

import asyncio

import pytest


def test_fastmcp_server_builds():
    pytest.importorskip("mcp")
    from vxdesk.mcp_server import _build_fastmcp

    server = _build_fastmcp()
    assert server.name == "vxdesk"


def test_fastmcp_tools_registered():
    pytest.importorskip("mcp")
    from vxdesk.mcp_server import TOOLS, _build_fastmcp

    server = _build_fastmcp()
    tools = asyncio.run(server.list_tools())
    names = {t.name for t in tools}
    for expected in TOOLS:
        assert expected in names
