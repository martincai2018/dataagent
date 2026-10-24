import sqlite3
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
import sqlglot
from sqlalchemy import create_engine, text

from app.errors import GatewayError
from app.executor import _jsonable, run_query
from app.validator import validate_and_rewrite


@pytest.fixture
def orders_engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 't.db'}")
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE orders (id INTEGER PRIMARY KEY, channel TEXT, amt REAL)"
        ))
        conn.execute(text(
            "INSERT INTO orders (id, channel, amt) VALUES "
            "(1, 'web', 10.0), (2, 'app', 20.0), (3, 'app', 30.0)"
        ))
    yield engine
    engine.dispose()  # Windows 下不 dispose 会让 tmp_path 回收偶发失败（复审 M6）


def _add_rows(engine, n, start=4):
    with engine.begin() as conn:
        for i in range(start, start + n):
            conn.execute(text(f"INSERT INTO orders (id, channel, amt) VALUES ({i}, 'x', 1.0)"))


def test_run_query_returns_columns_and_rows(orders_engine):
    result = run_query(
        orders_engine,
        "SELECT channel, SUM(amt) AS total FROM orders GROUP BY channel ORDER BY channel",
        max_rows=200,
    )
    assert result["ok"] is True
    assert result["columns"] == ["channel", "total"]
    assert result["rows"] == [["app", 50.0], ["web", 10.0]]
    assert result["truncated"] is False


def test_run_query_marks_truncation(orders_engine):
    _add_rows(orders_engine, 4)  # 共 7 行；直接喂执行器（无 LIMIT）验证 +1 哨兵机制本身
    result = run_query(orders_engine, "SELECT id FROM orders ORDER BY id", max_rows=5)
    assert len(result["rows"]) == 5
    assert result["truncated"] is True


def test_truncation_exact_boundary_is_false(orders_engine):
    _add_rows(orders_engine, 4)  # 共 7 行，恰好取 7 行不算截断
    result = run_query(orders_engine, "SELECT id FROM orders ORDER BY id", max_rows=7)
    assert len(result["rows"]) == 7
    assert result["truncated"] is False


def test_validator_then_executor_detects_truncation(orders_engine):
    # 复审 C1 回归：真实链路下 validator 注入 max_rows+1，截断标志必须可用
    _add_rows(orders_engine, 4)  # 共 7 行
    safe_sql = validate_and_rewrite("SELECT id FROM orders ORDER BY id", "sqlite", max_rows=5)
    assert int(sqlglot.parse_one(safe_sql, read="sqlite").args["limit"].expression.name) == 6
    result = run_query(orders_engine, safe_sql, max_rows=5)
    assert len(result["rows"]) == 5
    assert result["truncated"] is True


def test_validator_then_executor_exact_boundary(orders_engine):
    _add_rows(orders_engine, 4)  # 共 7 行，哨兵 LIMIT 8 只取回 7 行 → 不截断
    safe_sql = validate_and_rewrite("SELECT id FROM orders ORDER BY id", "sqlite", max_rows=7)
    result = run_query(orders_engine, safe_sql, max_rows=7)
    assert len(result["rows"]) == 7
    assert result["truncated"] is False


def test_bad_column_raises_gateway_error(orders_engine):
    with pytest.raises(GatewayError) as exc:
        run_query(orders_engine, "SELECT nope FROM orders")
    assert exc.value.stage == "execute"


class _ExplodingCursor:
    """模拟非 DBAPI 异常（PyMySQL 在 execute() 内解码字符集会抛 UnicodeDecodeError）。"""

    def __init__(self, cursor):
        self._cursor = cursor

    def execute(self, *args, **kwargs):
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad byte in legacy GBK table")

    def __getattr__(self, name):
        return getattr(self._cursor, name)


class _ExplodingConnection:
    def __init__(self, conn):
        self._conn = conn

    def cursor(self):
        return _ExplodingCursor(self._conn.cursor())

    def __getattr__(self, name):
        return getattr(self._conn, name)


def test_non_dbapi_error_is_structured_not_leaked():
    # 复审 C2 回归：非 DBAPI 异常不经 SQLAlchemy 包装，也必须结构化为 GatewayError
    engine = create_engine(
        "sqlite://",
        creator=lambda: _ExplodingConnection(sqlite3.connect(":memory:")),
    )
    try:
        with pytest.raises(GatewayError) as exc:
            run_query(engine, "SELECT 1")
        assert exc.value.stage == "execute"
        assert "UnicodeDecodeError" in exc.value.reason
    finally:
        engine.dispose()


@pytest.mark.parametrize("bad_max_rows", [0, -1])
def test_invalid_max_rows_raises_config_error(orders_engine, bad_max_rows):
    with pytest.raises(GatewayError) as exc:
        run_query(orders_engine, "SELECT 1", max_rows=bad_max_rows)
    assert exc.value.stage == "config"


def test_jsonable_conversions():
    # SQLite 原样返回文本；MySQL 下 Decimal/datetime 由 _jsonable 兜底
    assert _jsonable(Decimal("1.5")) == 1.5
    assert _jsonable(date(2026, 10, 22)) == "2026-10-22"
    assert _jsonable(datetime(2026, 10, 22, 9, 30)) == "2026-10-22T09:30:00"
    assert _jsonable(None) is None
    # MySQL TIME 经 PyMySQL 转 timedelta（可负、可超 24 小时、可带小数秒）（复审 I1）
    assert _jsonable(timedelta(hours=9, minutes=30)) == "09:30:00"
    assert _jsonable(timedelta(hours=-30)) == "-30:00:00"
    assert _jsonable(timedelta(hours=1, minutes=2, seconds=3, microseconds=456000)) == "01:02:03.456000"
    # 非有限浮点数不得产出 Infinity/NaN 非法 JSON token；Decimal NaN/超大指数同样收敛（复审 I2/I3）
    assert _jsonable(float("inf")) is None
    assert _jsonable(float("nan")) is None
    assert _jsonable(Decimal("NaN")) is None
    assert _jsonable(Decimal("sNaN")) == "sNaN"
    # 超 JS 安全整数范围的 BIGINT（如雪花 ID）转字符串保精度（复审 I3）
    assert _jsonable(2**63) == str(2**63)
    assert _jsonable(42) == 42
    assert _jsonable(True) is True
    assert _jsonable(b"\x01") == "01"
    # timedelta 边界：负半秒符号与微秒都不丢；timedelta.max 量级无宽度问题
    assert _jsonable(timedelta(seconds=-0.5)) == "-00:00:00.500000"
    assert _jsonable(timedelta.max) == "24000000000:00:00.999999"


def test_payload_roundtrips_strict_json(orders_engine):
    # 整个返回载荷必须能被严格 JSON 序列化（allow_nan=False）：
    # SQLite 1e999 → inf 经 _jsonable 收敛为 None，不得产出 Infinity 非法 token
    import json

    result = run_query(orders_engine, "SELECT 1e999 AS huge, x'01' AS blob", max_rows=5)
    assert result["rows"] == [[None, "01"]]
    json.dumps(result, allow_nan=False)  # 不抛即通过
