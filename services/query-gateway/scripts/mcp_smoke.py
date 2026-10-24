"""不依赖 DB-GPT 验证 MCP SSE 服务：python scripts/mcp_smoke.py"""
import asyncio
import json

from mcp import ClientSession
from mcp.client.sse import sse_client

URL = "http://127.0.0.1:8000/sse"


def _content_to_obj(result):
    return json.loads(result.content[0].text)


async def main():
    async with sse_client(URL) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            tool_names = sorted(t.name for t in tools.tools)
            print("TOOLS:", tool_names)
            assert tool_names == ["get_table_meta", "list_tables", "run_readonly_sql"]

            tables = await session.call_tool("list_tables", {})
            print("LIST_TABLES:", _content_to_obj(tables))

            meta = await session.call_tool(
                "get_table_meta", {"table_name": "dws_trade_order_di"}
            )
            print("META_OK:", _content_to_obj(meta)["ok"])

            query = await session.call_tool(
                "run_readonly_sql",
                {"sql": "SELECT COUNT(*) AS n FROM dws_trade_order_di"},
            )
            print("QUERY:", _content_to_obj(query))

            blocked = await session.call_tool(
                "run_readonly_sql", {"sql": "DROP TABLE dws_trade_order_di"}
            )
            blocked_obj = _content_to_obj(blocked)
            assert blocked_obj["ok"] is False and blocked_obj["stage"] == "parse"
            print("BLOCK_OK:", blocked_obj)


if __name__ == "__main__":
    asyncio.run(main())
