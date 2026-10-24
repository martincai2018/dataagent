import pytest

from app.errors import GatewayError
from app.validator import validate_and_rewrite

MALICIOUS = [
    # 经典多语句注入
    "SELECT * FROM t; DROP TABLE t",
    "SELECT * FROM t; DELETE FROM t",
    "SELECT * FROM t; UPDATE t SET a=1",
    "SELECT * FROM t; INSERT INTO t VALUES (1)",
    "SELECT * FROM t; CREATE USER x IDENTIFIED BY 'y'",
    "SELECT * FROM t; GRANT ALL ON *.* TO x",
    # 行注释后换行追加语句（-- 只注释到行尾，第二行的 DROP 仍是真实语句）
    "SELECT * FROM t -- harmless\n; DROP TABLE t",
    # DDL/DML 单品
    "DROP DATABASE demo",
    "RENAME TABLE t TO t2",
    "CREATE VIEW v AS SELECT 1",
    # 落表类
    "SELECT * INTO OUTFILE '/tmp/x.csv' FROM t",
    # 空白/异常
    "",
    ";;;",
]


@pytest.mark.parametrize("sql", MALICIOUS)
def test_malicious_sql_rejected(sql):
    with pytest.raises(GatewayError) as exc:
        validate_and_rewrite(sql, "mysql")
    assert exc.value.stage == "parse"


def test_safe_subqueries_are_allowed():
    # 子查询、IN、EXISTS 等正常只读写法不得误伤
    safe = "SELECT * FROM orders WHERE id IN (SELECT order_id FROM pay WHERE dt = '2026-10-22')"
    out = validate_and_rewrite(safe, "mysql", max_rows=200)
    assert "LIMIT 201" in out.upper()
