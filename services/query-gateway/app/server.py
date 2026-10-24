"""查询网关 MCP 入口。启动：python -m app.server

默认 SSE，端点 /sse。绑定地址由 HOST 环境变量控制（默认 127.0.0.1 仅本机；
容器/compose 显式给 HOST=0.0.0.0 且不向宿主机发布端口，只走内部网络）。
端口由 PORT 环境变量控制（默认 8000）。
"""
import functools
import os
import time

import anyio
from mcp.server.fastmcp import FastMCP
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_settings
from app.gateway import Gateway

# DB-GPT 代具身份：Stage 0 所有工具调用统一记为 dbgpt；阶段 1 由 DB-GPT 侧透传真实用户
_TOOL_USER = "dbgpt"

mcp = FastMCP("dataagent-query-gateway")
_settings = get_settings()


def _engine_kwargs(db_url: str) -> dict:
    """PyMySQL 超时：不可达实例与跑不出来的只读 SELECT 都不得无限期挂住工作线程。

    其余引擎的超时参数各异（sqlite 不接受这些键），阶段 1 按引擎补全。
    """
    if db_url.startswith(("mysql://", "mysql+")):
        return {"connect_args": {"connect_timeout": 5, "read_timeout": 30}}
    return {}


def _connect_with_retry(db_url: str, attempts: int = 15, wait_seconds: float = 2.0, **engine_kwargs):
    """容器场景下等待 demo-mysql 就绪。"""
    last_error = None
    for _ in range(attempts):
        try:
            engine = create_engine(db_url, pool_pre_ping=True, **engine_kwargs)
            with engine.connect():
                return engine
        except SQLAlchemyError as exc:
            last_error = exc
            time.sleep(wait_seconds)
    raise RuntimeError(f"数据库连接失败：{last_error}")


_gateway = Gateway(
    engine=_connect_with_retry(_settings.db_url, **_engine_kwargs(_settings.db_url)),
    dialect=_settings.sql_dialect,
    audit_log=_settings.audit_log,
    max_rows=_settings.max_rows,
)


@mcp.tool()
async def list_tables() -> dict:
    """列出业务数仓中所有可以查询的表，返回每张表的名称与注释。问数前应先调用。"""
    # 同步 DB/审计调用卸到工作线程：mcp 1.2.0 的同步工具会被内联在事件循环线程执行，
    # 一条慢查询会冻僵所有 SSE 会话（Task 7 对抗式复审 I1）。
    return await anyio.to_thread.run_sync(
        functools.partial(_gateway.list_tables, user=_TOOL_USER)
    )


@mcp.tool()
async def get_table_meta(table_name: str) -> dict:
    """获取指定表的字段结构（字段名、类型、注释）。生成 SQL 前必须先查看字段。table_name 为精确表名。"""
    return await anyio.to_thread.run_sync(
        functools.partial(_gateway.get_table_meta, table_name, user=_TOOL_USER)
    )


@mcp.tool()
async def run_readonly_sql(sql: str) -> dict:
    """在数仓上执行只读 SELECT 查询（自动注入 LIMIT 201 哨兵，最多返回 200 行）。
    成功返回 {ok, columns, rows, truncated, executed_sql}；
    失败返回 {ok:false, stage, reason, suggestion}，应按 suggestion 修正后重试。"""
    return await anyio.to_thread.run_sync(
        functools.partial(_gateway.run_readonly_sql, sql, user=_TOOL_USER)
    )


if __name__ == "__main__":
    mcp.settings.host = os.getenv("HOST", "127.0.0.1")
    mcp.settings.port = int(os.getenv("PORT", "8000"))
    mcp.run(transport="sse")
