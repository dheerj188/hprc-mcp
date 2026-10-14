"""A tiny MCP client with no AI in it: start the server, read its menu, press one button.

    uv run python client/mini_client.py          # simulated cluster
    uv run python client/mini_client.py --real   # the real cluster (on a login node, or after `ssh grace`)

It shows that a server describes itself: this client knows nothing about HPRC,
yet it can list what the server offers and call a tool, exactly as Claude Desktop does.
"""

import asyncio
import os
import sys
from pathlib import Path

from mcp import Client, StdioServerParameters

REPO = Path(__file__).resolve().parent.parent


async def main() -> None:
    env = dict(os.environ, HPRC_MCP_BACKEND="auto" if "--real" in sys.argv else "mock")
    server = StdioServerParameters(command="uv", args=["run", "--directory", str(REPO), "hprc-mcp"], env=env)
    async with Client(server) as client:
        print("The server offers these tools:")
        for tool in (await client.list_tools()).tools:
            summary = " ".join(tool.description.split()).split(". ")[0]
            print(f"  - {tool.name}: {summary}")
        print("\nResources:", ", ".join(str(r.uri) for r in (await client.list_resources()).resources))
        print("Prompts:  ", ", ".join(p.name for p in (await client.list_prompts()).prompts))

        print("\nPressing one button: my_jobs()")
        result = await client.call_tool("my_jobs", {})
        print(result.content[0].text)


asyncio.run(main())
