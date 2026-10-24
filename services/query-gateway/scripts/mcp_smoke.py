"""不依赖 DB-GPT 验证 MCP SSE 服务：python scripts/mcp_smoke.py"""
import asyncio
import json

from mcp import ClientSession
from mcp.client.sse import sse_client

URL = "http://127.0.0.1:8000/sse"


def _content_to_obj(result):
    # MCP 层错误（非 Gateway 结构化返回）在 mcp 1.2.0 会以 isError/异常形式出现：
    # 给出可读失败信息，而不是让 content[0] 抛无上下文的 IndexError
    if getattr(result, "isError", False):
        raise AssertionError(f"工具返回 MCP 错误：{result.content}")
    try:
        return json.loads(result.content[0].text)
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        raise AssertionError(f"无法解析工具返回：{result.content!r}") from exc


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
