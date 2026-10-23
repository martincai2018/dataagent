import datetime
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.errors import GatewayError


def run_query(engine: Engine, sql: str, max_rows: int = 200) -> dict:
    """执行已通过校验的查询。多取 1 行用于判断截断；结果做 JSON 安全序列化。"""
    try:
        with engine.connect() as connection:
            result = connection.execute(text(sql))
            columns = list(result.keys())
            rows = result.fetchmany(max_rows + 1)
    except SQLAlchemyError as exc:
        raise GatewayError(
            "execute",
            f"数据库执行失败：{str(exc)[:300]}",
            "检查表名、字段名与方言语法，修正后重试",
        )

    truncated = len(rows) > max_rows
    data = [_jsonable_row(row) for row in rows[:max_rows]]
    return {"ok": True, "columns": columns, "rows": data, "truncated": truncated}


def _jsonable_row(row) -> list:
    return [_jsonable(value) for value in row]


def _jsonable(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray)):
        return value.hex()
    return value
