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
    # 单语句 Command 根（Task 8 对抗复审加厚）：sqlglot 把 GRANT/CALL/USE 等解析为
    # exp.Command 家族，根白名单拒绝；此前整库仅 RENAME 一条单品钉住该家族
    "GRANT SELECT ON *.* TO x",
    "CALL some_proc(1)",
    "USE demo",
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


def test_versioned_comment_injection_is_neutralized_by_rewrite():
    # MySQL 版本化注释 /*! ... */ 在 sqlglot 生成器重写时被规范成普通注释（/*! -> /* !），
    # 钉死该无害化行为，防 sqlglot 升级改变生成器输出（执行器只跑重写后 SQL）
    out = validate_and_rewrite("SELECT * FROM t /*! ; DROP TABLE t */", "mysql")
    assert "/*!" not in out
