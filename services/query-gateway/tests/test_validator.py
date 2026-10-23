import sqlglot
import pytest
from sqlglot import exp

from app.errors import GatewayError
from app.validator import validate_and_rewrite

# 注：parse_one 是 sqlglot 顶层 API（exp 模块上不存在）；UNION ALL 解析为 exp.Union(distinct=False)


def test_plain_select_gets_limit_injected():
    sql = validate_and_rewrite("SELECT id FROM orders", "mysql", max_rows=200)
    tree = sqlglot.parse_one(sql, read="mysql")
    assert isinstance(tree, exp.Select)
    assert int(tree.args["limit"].expression.name) == 201


def test_small_existing_limit_is_kept():
    sql = validate_and_rewrite("SELECT id FROM orders LIMIT 10", "mysql", max_rows=200)
    assert int(sqlglot.parse_one(sql, read="mysql").args["limit"].expression.name) == 10


def test_large_existing_limit_is_clamped():
    sql = validate_and_rewrite("SELECT id FROM orders LIMIT 99999", "mysql", max_rows=200)
    assert int(sqlglot.parse_one(sql, read="mysql").args["limit"].expression.name) == 201


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
    assert "LIMIT 201" in sql.upper()


def test_empty_sql_is_rejected():
    with pytest.raises(GatewayError):
        validate_and_rewrite("   ", "mysql")


def test_nul_byte_is_rejected():
    with pytest.raises(GatewayError):
        validate_and_rewrite("SELECT 1\x00", "mysql")


def test_trailing_comment_after_semicolon_is_tolerated():
    sql = validate_and_rewrite("SELECT id FROM orders; -- note\n", "mysql", max_rows=200)
    assert "LIMIT 201" in sql.upper()


def test_unterminated_string_returns_gateway_error():
    with pytest.raises(GatewayError) as exc:
        validate_and_rewrite("SELECT 'abc", "mysql")
    assert exc.value.stage == "parse"


@pytest.mark.parametrize("raw,dialect", [
    ("SELECT id FROM orders LIMIT -1", "sqlite"),
    ("SELECT id FROM orders LIMIT 1 + 99999", "sqlite"),
    ("SELECT id FROM orders LIMIT 2 * 99999", "sqlite"),
    ("SELECT id FROM orders LIMIT 0x100", "mysql"),
])
def test_non_literal_or_negative_limits_are_clamped(raw, dialect):
    sql = validate_and_rewrite(raw, dialect, max_rows=200)
    tree = sqlglot.parse_one(sql, read=dialect)
    assert int(tree.args["limit"].expression.name) == 201


def test_into_hidden_in_union_branch_is_rejected():
    with pytest.raises(GatewayError) as exc:
        validate_and_rewrite(
            "SELECT id INTO orders_bak FROM orders UNION SELECT id FROM orders", "mysql"
        )
    assert exc.value.stage == "parse"


def test_data_modifying_cte_is_rejected():
    with pytest.raises(GatewayError) as exc:
        validate_and_rewrite(
            "WITH d AS (DELETE FROM orders RETURNING *) SELECT * FROM d", "postgres"
        )
    assert exc.value.stage == "parse"


def test_for_update_lock_is_rejected():
    with pytest.raises(GatewayError) as exc:
        validate_and_rewrite(
            "SELECT id FROM orders WHERE id = 1 FOR UPDATE", "mysql"
        )
    assert exc.value.stage == "parse"


def test_union_all_semantics_survive_rewrite():
    raw = "SELECT id FROM orders UNION ALL SELECT id FROM orders"
    sql = validate_and_rewrite(raw, "mysql", max_rows=200)
    tree = sqlglot.parse_one(sql, read="mysql")
    union = tree.find(exp.Union)
    assert union is not None and union.args.get("distinct") is False


@pytest.mark.parametrize("raw,dialect", [
    ("SELECT id FROM orders UNION SELECT id FROM orders", "mysql"),
    ("SELECT 1 INTERSECT SELECT 2", "mysql"),
    ("SELECT 1 EXCEPT SELECT 2", "sqlite"),
])
def test_set_op_wrapper_has_derived_table_alias(raw, dialect):
    # MySQL 要求派生表必须有别名，否则 ERROR 1248；三种集合操作都要回归
    sql = validate_and_rewrite(raw, dialect, max_rows=200)
    assert ") AS _Q_" in sql.upper()  # sqlglot 生成 (...) AS _q_，不带反引号


def test_clamp_preserves_offset():
    sql = validate_and_rewrite("SELECT id FROM orders LIMIT 50, 99999", "mysql", max_rows=200)
    tree = sqlglot.parse_one(sql, read="mysql")
    assert int(tree.args["limit"].expression.name) == 201
    assert int(tree.args["offset"].expression.name) == 50


def test_deeply_nested_sql_returns_gateway_error():
    raw = "SELECT * FROM " + "(" * 300 + "SELECT 1" + ") x" * 300
    with pytest.raises(GatewayError) as exc:
        validate_and_rewrite(raw, "mysql")
    assert exc.value.stage == "parse"
    # 钉住真实触发路径：该深度在序列化（generator 递归）阶段触顶
    assert "RecursionError" in exc.value.reason


@pytest.mark.parametrize("bad_sql", [None, 123])
def test_non_string_input_is_rejected(bad_sql):
    with pytest.raises(GatewayError) as exc:
        validate_and_rewrite(bad_sql, "mysql")
    assert exc.value.stage == "parse"
    assert "为空或含非法字符" in exc.value.reason


@pytest.mark.parametrize("bad_max_rows", [0, -1])
def test_invalid_max_rows_is_rejected(bad_max_rows):
    with pytest.raises(GatewayError) as exc:
        validate_and_rewrite("SELECT 1", "mysql", max_rows=bad_max_rows)
    assert exc.value.stage == "config"


def test_unknown_dialect_is_gateway_error():
    with pytest.raises(GatewayError) as exc:
        validate_and_rewrite("SELECT 1", "not-a-real-dialect")
    assert exc.value.stage == "parse"


def test_output_dialect_matches_target():
    sql = validate_and_rewrite("SELECT CURRENT_TIMESTAMP AS t", "sqlite")
    # 方言往返解析不报错即视为方言正确（parse_one 是 sqlglot 顶层 API，不在 exp 模块上）
    assert sqlglot.parse_one(sql, read="sqlite") is not None
