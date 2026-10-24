"""查询网关 MCP 入口。启动：python -m app.server（默认 SSE，0.0.0.0:8000，端点 /sse）"""
import os
import time

from mcp.server.fastmcp import FastMCP
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_settings
from app.gateway import Gateway

mcp = FastMCP("dataagent-query-gateway")
_settings = get_settings()


def _connect_with_retry(db_url: str, attempts: int = 15, wait_seconds: float = 2.0):
    """容器场景下等待 demo-mysql 就绪。"""
    last_error = None
    for _ in range(attempts):
        try:
            engine = create_engine(db_url, pool_pre_ping=True)
            with engine.connect():
                return engine
        except SQLAlchemyError as exc:
            last_error = exc
            time.sleep(wait_seconds)
    raise RuntimeError(f"数据库连接失败：{last_error}")


_gateway = Gateway(
    engine=_connect_with_retry(_settings.db_url),
    dialect=_settings.sql_dialect,
    audit_log=_settings.audit_log,
    max_rows=_settings.max_rows,
)


@mcp.tool()
def list_tables() -> dict:
    """列出业务数仓中所有可以查询的表，返回每张表的名称与注释。问数前应先调用。"""
    return _gateway.list_tables()


@mcp.tool()
def get_table_meta(table_name: str) -> dict:
    """获取指定表的字段结构（字段名、类型、注释）。生成 SQL 前必须先查看字段。table_name 为精确表名。"""
    return _gateway.get_table_meta(table_name)


@mcp.tool()
def run_readonly_sql(sql: str) -> dict:
    """在数仓上执行只读 SELECT 查询（自动注入 LIMIT 201 哨兵，最多返回 200 行）。
    成功返回 {ok, columns, rows, truncated, executed_sql}；
    失败返回 {ok:false, stage, reason, suggestion}，应按 suggestion 修正后重试。"""
    return _gateway.run_readonly_sql(sql, user="dbgpt")


if __name__ == "__main__":
    mcp.settings.host = "0.0.0.0"
    mcp.settings.port = int(os.getenv("PORT", "8000"))
    mcp.run(transport="sse")
