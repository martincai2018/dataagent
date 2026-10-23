import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from app.errors import GatewayError

# sqlglot 中 UNION ALL 是 exp.Union(distinct=False)，没有独立的 UnionAll 节点
_READ_ONLY_ROOT = (exp.Select, exp.Union, exp.Intersect, exp.Except)

# 纯只读查询的 AST 中任何位置都不允许出现这些节点：
# 可拦住数据修改型 CTE、藏在 UNION 分支/子查询里的 INTO、SELECT ... FOR UPDATE 等绕过
# 注：sqlglot 中 ALTER 的节点名是 exp.Alter（AlterColumn/AlterRename 等的基类，不存在 exp.AlterTable）
_FORBIDDEN_NODES = (
    exp.Insert, exp.Update, exp.Delete, exp.Merge,
    exp.Create, exp.Drop, exp.Alter, exp.TruncateTable,
    exp.Into, exp.Lock,
)


def validate_and_rewrite(sql: str, dialect: str, max_rows: int = 200) -> str:
    """校验 SQL 只读、单语句，并注入/收敛 LIMIT。返回重写后的 SQL。

    任何违规都抛 GatewayError(stage="parse")，suggestion 供 Agent 自纠。
    """
    if not isinstance(sql, str) or not sql.strip() or "\x00" in sql:
        raise GatewayError("parse", "SQL 为空或含非法字符", "提交一条 SELECT 查询")
    if max_rows < 1:
        raise GatewayError("config", "max_rows 必须为正整数", "联系管理员检查 MAX_ROWS 配置")

    try:
        # 解析、整树扫描、重写、序列化全部纳入：超深嵌套可能在序列化阶段
        # （generator 递归）而不是 parse 阶段触发 RecursionError，同样必须结构化
        parsed = sqlglot.parse(sql.strip(), read=dialect)

        # 容忍 "SELECT 1;" 这类尾随空语句（None / 孤立 Semicolon 节点），拒绝第二条真实语句
        statements = [
            node for node in parsed
            if node is not None and not isinstance(node, exp.Semicolon)
        ]
        if not statements:
            raise GatewayError("parse", "SQL 为空", "提交一条 SELECT 查询")
        if len(statements) > 1:
            raise GatewayError(
                "parse",
                "只允许提交单条 SQL 语句",
                "去掉多余分号与后续语句，一次只提交一条 SELECT",
            )

        statement = statements[0]
        if not isinstance(statement, _READ_ONLY_ROOT):
            raise GatewayError(
                "parse",
                f"只允许只读查询，检测到 {type(statement).__name__}",
                "改写为 SELECT/WITH 查询，禁止任何 DDL 或增删改操作",
            )

        # 整树扫描写节点：在集合操作包装之前做，保证拒绝发生在任何重写/包装之前
        # （深度防御，且错误信息指向原始语句；find 本身会递归进子查询，包装后同样能命中）
        forbidden = statement.find(*_FORBIDDEN_NODES)
        if forbidden is not None:
            raise GatewayError(
                "parse",
                f"只读查询中禁止出现 {type(forbidden).__name__}（DDL/DML/落表/锁）",
                "只允许纯 SELECT 查询，不要落表、修改数据或加锁",
            )

        # UNION/INTERSECT 等集合操作包一层子查询，统一在外层挂 LIMIT。
        # 派生表必须带别名：MySQL 要求 "Every derived table must have its own alias"
        if not isinstance(statement, exp.Select):
            statement = exp.select("*").from_(statement.subquery(alias="_q_"))

        statement = _apply_row_limit(statement, max_rows)
        return statement.sql(dialect=dialect)
    except (SqlglotError, RecursionError, ValueError) as exc:
        # ParseError / TokenError（未闭合引号）/ 超深嵌套 RecursionError（parse 或序列化阶段）/ 未知方言 ValueError
        # GatewayError 不在捕获列表内，上面的结构化拒绝原样向上抛
        raise GatewayError("parse", f"SQL 解析失败：{type(exc).__name__}", "检查 SQL 语法后重试")


def _apply_row_limit(select: exp.Select, max_rows: int) -> exp.Select:
    current = select.args.get("limit")
    if current is None:
        return select.limit(max_rows)

    expr = current.expression
    # 只信任无符号整数字面量。负数（SQLite/PG 中 LIMIT -1 等于不限制）、
    # 算术表达式（.name 只取最左 token）、十六进制、占位符、FETCH FIRST 等一律收敛
    if isinstance(expr, exp.Literal) and expr.is_int:
        try:
            requested = int(expr.name)
        except ValueError:
            return select.limit(max_rows)
        if 0 <= requested <= max_rows:
            return select

    return select.limit(max_rows)
