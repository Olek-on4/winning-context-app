"""Talk to the stdio MCP server the way an agent does: handshake, list, call, read bytes.

Run from `apps/context-service`: `uv run python ../../scripts/mcp_probe.py`.
Proves the four tools answer and that a citation resolves to real corpus text.
"""

import asyncio, json, os
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    params = StdioServerParameters(
        command="/home/olek/.local/bin/uv",
        args=["run", "--directory", os.getcwd(), "python", "-m", "cli", "mcp"],
        env={**os.environ, "NEO4J_URI": "bolt://localhost:7687", "NEO4J_USER": "neo4j",
             "NEO4J_PASSWORD": "etyt-context"},
    )
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            info = await s.initialize()
            print("server:", info.server_info.name, info.server_info.version)
            tools = await s.list_tools()
            print("tools:", [t.name for t in tools.tools])
            res = await s.call_tool("context_search", {"question": "Does inventory-service still use a Redis cache?"})
            env = json.loads(res.content[0].text)
            print("claims:", len(env["claims"]), "degraded:", env["degraded"])
            for c in env["claims"][:3]:
                print(" ", c["status"], "|", c["statement"], "|", c["citations"][0]["path"])
            c0 = env["claims"][0]["citations"][0]
            span = await s.call_tool("resolve_span", {"path": c0["path"], "start": c0["lines"][0], "end": c0["lines"][1]})
            print("span:", repr(span.content[0].text[:120]))

asyncio.run(main())
