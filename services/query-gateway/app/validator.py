import sqlglot
from sqlglot import exp

from app.errors import GatewayError

# UNION ALL 在 sqlglot 中没有独立节点，统一为 exp.Union(distinct=False)
_READ_ONLY_ROOT = (exp.Select, exp.Union, exp.Intersect, exp.Except)


def validate_and_rewrite(sql: str, dialect: str, max_rows: int = 200) -> str:
    """校验 SQL 只读、单语句，并注入/收敛 LIMIT。返回重写后的 SQL。

    任何违规都抛 GatewayError(stage="parse")，suggestion 供 Agent 自纠。
    """
    if not sql or not sql.strip():
        raise GatewayError("parse", "SQL 为空", "提交一条 SELECT 查询")

    try:
        parsed = sqlglot.parse(sql.strip(), read=dialect)
    except sqlglot.errors.ParseError as exc:
        raise GatewayError("parse", f"SQL 解析失败：{exc}", "检查 SQL 语法后重试")

    # 容忍 "SELECT 1;" 这类尾随空语句（parse 成 None），但拒绝任何第二条真实语句
    statements = [node for node in parsed if node is not None]
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

    # UNION/INTERSECT 等集合操作包一层子查询，统一在外层挂 LIMIT
    if not isinstance(statement, exp.Select):
        statement = exp.select("*").from_(statement.subquery())

    if statement.args.get("into") is not None:
        raise GatewayError("parse", "禁止 SELECT INTO 类写操作", "只返回结果集，不要落表")

    statement = _apply_row_limit(statement, max_rows)
    return statement.sql(dialect=dialect)


def _apply_row_limit(select: exp.Select, max_rows: int) -> exp.Select:
    current = select.args.get("limit")
    if current is None:
        return select.limit(max_rows)

    try:
        requested = int(current.expression.name)
    except (AttributeError, ValueError):
        # LIMIT 是表达式而非字面量时，保守收敛
        return select.limit(max_rows)

    if requested > max_rows:
        return select.limit(max_rows)
    return select
