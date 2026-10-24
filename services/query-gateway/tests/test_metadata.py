from sqlalchemy import create_engine, text

from app.errors import GatewayError
from app.metadata import get_table_meta, list_tables


def _engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'meta.db'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE orders (id INTEGER, channel TEXT)"))
        conn.execute(text("CREATE TABLE users (id INTEGER, name TEXT)"))
    return engine


def test_list_tables_returns_all_table_names(tmp_path):
    tables = list_tables(_engine(tmp_path))
    names = {t["name"] for t in tables}
    assert names == {"orders", "users"}
    assert "comment" in tables[0]


def test_get_table_meta_returns_columns(tmp_path):
    meta = get_table_meta(_engine(tmp_path), "orders")
    assert meta["table"] == "orders"
    assert [c["name"] for c in meta["columns"]] == ["id", "channel"]
    assert meta["columns"][0]["type"]  # 类型非空


def test_get_table_meta_unknown_table_raises(tmp_path):
    try:
        get_table_meta(_engine(tmp_path), "nope")
    except GatewayError as exc:
        assert exc.stage == "metadata"
    else:
        raise AssertionError("应当抛 GatewayError")
