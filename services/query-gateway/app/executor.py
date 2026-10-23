import datetime
import math
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.errors import GatewayError

# 超过 JS 安全整数范围的 BIGINT（如雪花 ID）序列化为字符串，避免前端/Agent 丢精度
_JS_MAX_SAFE_INTEGER = 9007199254740991


def run_query(engine: Engine, sql: str, max_rows: int = 200) -> dict:
    """执行已通过校验的查询，返回 {ok, columns, rows, truncated}。

    哨兵约定：validator 对无限制查询注入 LIMIT max_rows+1，这里 fetchmany
    多取 1 行判定截断、实际只返回 max_rows 行。

    本函数绝不向调用方抛裸异常（Gateway"永不抛异常"契约）：SQLAlchemyError
    给可自纠建议；非 DBAPI 异常（如 PyMySQL 全缓冲游标在 execute() 内做字符集
    解码抛的 UnicodeDecodeError）不会被 SQLAlchemy 包装，由 except Exception
    兜底；结果行转换同样在守卫区内。
    """
    if max_rows < 1:
        raise GatewayError("config", "max_rows 必须为正整数", "联系管理员检查 MAX_ROWS 配置")
    try:
        with engine.connect() as connection:
            result = connection.execute(text(sql))
            columns = list(result.keys())
            raw_rows = result.fetchmany(max_rows + 1)
        truncated = len(raw_rows) > max_rows
        rows = [_jsonable_row(row) for row in raw_rows[:max_rows]]
    except SQLAlchemyError as exc:
        raise GatewayError(
            "execute",
            f"数据库执行失败：{str(exc)[:300]}",
            "检查表名、字段名与方言语法，修正后重试",
        )
    except Exception as exc:  # noqa: BLE001 - 网关契约：任何异常都结构化，不向 MCP 层裸抛
        raise GatewayError(
            "execute",
            f"数据库执行失败：{type(exc).__name__}: {str(exc)[:200]}",
            "稍后重试；若持续失败请联系管理员检查数据库连接与字符集",
        )

    return {"ok": True, "columns": columns, "rows": rows, "truncated": truncated}


def _jsonable_row(row) -> list:
    return [_jsonable(value) for value in row]


def _jsonable(value):
    if isinstance(value, Decimal):
        try:
            number = float(value)
        except (ArithmeticError, ValueError):
            # 超大指数 → OverflowError（ArithmeticError）；Python 3.14 起
            # sNaN → float 直接抛内置 ValueError（不经 decimal trap；已实测 C/纯 Python 版一致）
            # 这些值只可能来自 PG numeric（MySQL DECIMAL/SQLite 不会出现）
            return str(value)
        return number if math.isfinite(number) else None
    if isinstance(value, float):
        # SQLite 1e999 → inf：json.dumps 默认输出 Infinity 非法 token，严格解析器会拒收
        return value if math.isfinite(value) else None
    if isinstance(value, datetime.timedelta):
        # MySQL TIME 经 PyMySQL 转 timedelta（可负、可超 24 小时），按 MySQL 风格 HH:MM:SS
        return _timedelta_to_mysql_time(value)
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray)):
        return value.hex()
    if isinstance(value, int) and not isinstance(value, bool) and abs(value) > _JS_MAX_SAFE_INTEGER:
        return str(value)
    return value


def _timedelta_to_mysql_time(value: datetime.timedelta) -> str:
    abs_value = abs(value)
    total_seconds = int(abs_value.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    sign = "-" if value.total_seconds() < 0 else ""
    fraction = f".{abs_value.microseconds:06d}" if abs_value.microseconds else ""
    return f"{sign}{hours:02d}:{minutes:02d}:{seconds:02d}{fraction}"
