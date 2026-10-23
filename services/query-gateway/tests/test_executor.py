from sqlalchemy import create_engine, text

from app.executor import run_query


def _engine_with_orders(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 't.db'}")
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE orders (id INTEGER PRIMARY KEY, channel TEXT, amt REAL)"
        ))
        conn.execute(text(
            "INSERT INTO orders (id, channel, amt) VALUES "
            "(1, 'web', 10.0), (2, 'app', 20.0), (3, 'app', 30.0)"
        ))
    return engine


def test_run_query_returns_columns_and_rows(tmp_path):
    result = run_query(_engine_with_orders(tmp_path),
                       "SELECT channel, SUM(amt) AS total FROM orders GROUP BY channel ORDER BY channel",
                       max_rows=200)
    assert result["ok"] is True
    assert result["columns"] == ["channel", "total"]
    assert result["rows"] == [["app", 50.0], ["web", 10.0]]
    assert result["truncated"] is False


def test_run_query_marks_truncation(tmp_path):
    engine = _engine_with_orders(tmp_path)
    with engine.begin() as conn:
        for i in range(4, 8):
            conn.execute(text(f"INSERT INTO orders (id, channel, amt) VALUES ({i}, 'x', 1.0)"))

    result = run_query(engine, "SELECT id FROM orders ORDER BY id", max_rows=5)
    assert len(result["rows"]) == 5
    assert result["truncated"] is True


def test_run_query_returns_json_native_types(tmp_path):
    # SQLite 原样返回文本；MySQL 下 Decimal/datetime 由 _jsonable 兜底，此处直接验证转换函数
    import datetime
    from decimal import Decimal

    from app.executor import _jsonable

    assert _jsonable(Decimal("1.5")) == 1.5
    assert _jsonable(datetime.date(2026, 10, 22)) == "2026-10-22"
    assert _jsonable(datetime.datetime(2026, 10, 22, 9, 30)) == "2026-10-22T09:30:00"
    assert isinstance(_jsonable(None), type(None))
