"""Task 7 对抗式复审 I1/B2：SSE 工具必须是 async（卸到工作线程执行），且导入期装配可用。

app.server 在导入期即创建 engine 并连接（I3，Task 10 健康检查配合），故本模块在导入
app.server 之前把 DB_URL 指向内存 sqlite、AUDIT_LOG 指向临时文件，避免工作目录落库。
"""
import asyncio
import inspect
import os
import tempfile

if "DB_URL" not in os.environ:
    os.environ["DB_URL"] = "sqlite://"
if "AUDIT_LOG" not in os.environ:
    os.environ["AUDIT_LOG"] = os.path.join(tempfile.mkdtemp(), "audit.jsonl")

from app import server  # noqa: E402


def test_tools_are_async_coroutines():
    # FastMCP 的 @mcp.tool() 原样返回函数本身；同步工具会被内联在事件循环线程执行
    # （慢查询冻僵所有 SSE 会话），async+to_thread 形态由本测试钉死
    assert inspect.iscoroutinefunction(server.list_tables)
    assert inspect.iscoroutinefunction(server.get_table_meta)
    assert inspect.iscoroutinefunction(server.run_readonly_sql)


def test_async_tools_roundtrip_against_inmemory_db():
    tables = asyncio.run(server.list_tables())
    assert tables["ok"] is True
    assert tables["tables"] == []  # 内存库无表，只验证 async 工具到 Gateway 的装配

    result = asyncio.run(server.run_readonly_sql("SELECT 1 AS x"))
    assert result["ok"] is True
    assert result["columns"] == ["x"]
    assert result["rows"] == [[1]]
