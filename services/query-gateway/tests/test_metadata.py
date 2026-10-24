import pytest
from sqlalchemy import create_engine, inspect, text

from app.errors import GatewayError
from app.metadata import get_table_meta, list_tables


@pytest.fixture
def engine(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path / 'meta.db'}")
    with eng.begin() as conn:
        conn.execute(text("CREATE TABLE orders (id INTEGER, channel TEXT)"))
        conn.execute(text("CREATE TABLE users (id INTEGER, name TEXT)"))
    yield eng
    eng.dispose()  # Windows 下不 dispose 会让 tmp_path 回收偶发失败（复审 I-1，同 executor M6）


def test_list_tables_returns_all_table_names(engine):
    tables = list_tables(engine)
    assert {t["name"] for t in tables} == {"orders", "users"}
    assert all("comment" in t for t in tables)


def test_get_table_meta_returns_columns(engine):
    meta = get_table_meta(engine, "orders")
    assert meta["table"] == "orders"
    assert [c["name"] for c in meta["columns"]] == ["id", "channel"]
    assert meta["columns"][0]["type"]  # 类型非空


def test_get_table_meta_unknown_table_raises(engine):
    with pytest.raises(GatewayError) as exc:
        get_table_meta(engine, "nope")
    assert exc.value.stage == "metadata"
    assert "共 2 张" in exc.value.suggestion  # 锁定给 Agent 的自纠契约


def test_identifier_injection_is_blocked_by_gate(engine):
    # 白名单 gate 是真正的防线：任何不等于现有表名的载荷都在反射 SQL 构造前拒绝
    with pytest.raises(GatewayError) as exc:
        get_table_meta(engine, "x'; DROP TABLE orders --")
    assert exc.value.stage == "metadata"
    assert inspect(engine).has_table("orders")  # 表安然无恙


def test_broken_engine_raises_structured_metadata_error(tmp_path):
    bad_engine = create_engine(f"sqlite:///{tmp_path / 'not_a_dir' / 'meta.db'}")
    try:
        with pytest.raises(GatewayError) as exc:
            list_tables(bad_engine)
        assert exc.value.stage == "metadata"
    finally:
        bad_engine.dispose()


def test_non_sqlalchemy_error_is_structured(monkeypatch, engine):
    # 非 SQLAlchemyError（实证：无默认库时 MySQL 方言会抛 AttributeError）也不得裸逃
    def _boom(*args, **kwargs):
        raise RuntimeError("unexpected reflection failure")

    monkeypatch.setattr("app.metadata.inspect", _boom)
    with pytest.raises(GatewayError) as exc:
        list_tables(engine)
    assert exc.value.stage == "metadata"
