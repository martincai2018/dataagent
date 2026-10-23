import sqlglot
import pytest
from sqlglot import exp

from app.errors import GatewayError
from app.validator import validate_and_rewrite


def test_plain_select_gets_limit_injected():
    sql = validate_and_rewrite("SELECT id FROM orders", "mysql", max_rows=200)
    tree = sqlglot.parse_one(sql, read="mysql")
    assert isinstance(tree, exp.Select)
    assert int(tree.args["limit"].expression.name) == 200


def test_small_existing_limit_is_kept():
    sql = validate_and_rewrite("SELECT id FROM orders LIMIT 10", "mysql", max_rows=200)
    assert int(sqlglot.parse_one(sql, read="mysql").args["limit"].expression.name) == 10


def test_large_existing_limit_is_clamped():
    sql = validate_and_rewrite("SELECT id FROM orders LIMIT 99999", "mysql", max_rows=200)
    assert int(sqlglot.parse_one(sql, read="mysql").args["limit"].expression.name) == 200


def test_cte_select_is_allowed_and_limited():
    raw = "WITH a AS (SELECT id FROM orders) SELECT id FROM a"
    sql = validate_and_rewrite(raw, "mysql", max_rows=200)
    tree = sqlglot.parse_one(sql, read="mysql")
    assert isinstance(tree, exp.Select)
    assert tree.args["limit"] is not None


def test_union_is_wrapped_and_limited():
    raw = "SELECT id FROM orders UNION SELECT id FROM orders"
    sql = validate_and_rewrite(raw, "mysql", max_rows=200)
    tree = sqlglot.parse_one(sql, read="mysql")
    assert isinstance(tree, exp.Select)
    assert tree.args["limit"] is not None


@pytest.mark.parametrize("raw", [
    "DROP TABLE orders",
    "DELETE FROM orders WHERE id = 1",
    "INSERT INTO orders (id) VALUES (9)",
    "UPDATE orders SET id = 2 WHERE id = 1",
    "CREATE TABLE x (id INT)",
    "ALTER TABLE orders ADD COLUMN x INT",
    "TRUNCATE TABLE orders",
])
def test_writes_and_ddl_are_rejected(raw):
    with pytest.raises(GatewayError) as exc:
        validate_and_rewrite(raw, "mysql")
    assert exc.value.stage == "parse"


def test_multiple_statements_are_rejected():
    with pytest.raises(GatewayError) as exc:
        validate_and_rewrite("SELECT * FROM orders; DROP TABLE orders", "mysql")
    assert exc.value.stage == "parse"
    assert "单条" in exc.value.reason or "一条" in exc.value.reason


def test_select_into_is_rejected():
    with pytest.raises(GatewayError) as exc:
        validate_and_rewrite("SELECT * INTO orders_bak FROM orders", "mysql")
    assert exc.value.stage == "parse"


def test_trailing_semicolon_is_tolerated():
    sql = validate_and_rewrite("SELECT id FROM orders;", "mysql", max_rows=200)
    assert "LIMIT 200" in sql.upper()


def test_empty_sql_is_rejected():
    with pytest.raises(GatewayError) as exc:
        validate_and_rewrite("   ", "mysql")


def test_output_dialect_matches_target():
    sql = validate_and_rewrite("SELECT CURRENT_TIMESTAMP AS t", "sqlite")
    # 方言往返解析不报错即视为方言正确
    assert sqlglot.parse_one(sql, read="sqlite") is not None
