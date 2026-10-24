# 阶段 0：Data Agent 骨架验证 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 两周内端到端跑通「DB-GPT Web 提问 → Agent 调用 MCP 工具 → 查询网关校验并执行只读 SQL → 结果返回」，并搭好评测集脚手架。

**Architecture:** DB-GPT v0.8.2（Docker，不改核心代码）作为编排与交互层；自建 Python 查询网关作为独立 **MCP Server（SSE 传输）**，提供 `list_tables` / `get_table_meta` / `run_readonly_sql` 三个工具；网关内部用 sqlglot 做单语句与 SELECT-only 校验、强制 LIMIT，用 SQLAlchemy 执行，所有调用写 JSONL 审计日志。确定性逻辑全部 pytest 覆盖，Agent 侧通过 Web UI 配置 MCP 接入，不写任何 DB-GPT 插件代码。

**Tech Stack:** Python 3.11、mcp==1.2.0（FastMCP，SSE 传输；DB-GPT v0.8.2 的 MCP 客户端只支持 legacy SSE，故锁定此版本）、sqlglot、SQLAlchemy 2.x、pymysql、pytest、Docker Compose、MySQL 8（demo 业务库）、DeepSeek API（`deepseek-chat`）。

**对应 Spec：** `docs/superpowers/specs/2026-10-21-enterprise-data-agent-design.md` 第 5 节「阶段 0 · 骨架验证」。

---

## 文件结构

```
dataagent/
├── docs/
│   ├── superpowers/specs/2026-10-21-enterprise-data-agent-design.md
│   └── superpowers/plans/2026-10-23-stage0-skeleton.md   ← 本文件
├── services/
│   └── query-gateway/                                     # 查询网关（独立 MCP Server）
│       ├── requirements.txt
│       ├── pytest.ini
│       ├── app/
│       │   ├── __init__.py
│       │   ├── config.py        # 环境变量配置
│       │   ├── errors.py        # 结构化错误 GatewayError
│       │   ├── audit.py         # JSONL 审计日志
│       │   ├── validator.py     # sqlglot 校验 + LIMIT 重写（纯函数，核心安全边界）
│       │   ├── executor.py      # SQLAlchemy 执行 + JSON 安全序列化
│       │   ├── metadata.py      # 表清单 / 表结构
│       │   ├── gateway.py       # 门面：串联校验、执行、审计、错误兜底
│       │   └── server.py        # FastMCP(SSE) 入口
│       ├── scripts/
│       │   └── mcp_smoke.py     # 不依赖 DB-GPT 的 MCP 客户端冒烟脚本
│       └── tests/
│           ├── conftest.py
│           ├── test_validator.py
│           ├── test_executor.py
│           ├── test_metadata.py
│           ├── test_gateway.py
│           └── test_malicious_sql.py
├── deploy/
│   ├── Dockerfile.gateway
│   ├── docker-compose.yml       # demo-mysql + gateway + dbgpt
│   ├── configs/
│   │   └── dbgpt-stage0.toml    # SQLite 元数据库 + DeepSeek
│   └── seed/
│       └── init_demo.sql        # demo 业务库种子数据
└── evals/
    ├── README.md                # 50 题收集流程
    └── golden/
        └── questions.seed.jsonl # 10 条针对种子数据的样例题
```

环境约定：所有命令在 Git Bash 中执行；Python 开发在 `services/query-gateway/` 下用 venv；最终运行环境是 Docker（Linux 容器），不依赖 Windows 本地装 MySQL。

---

### Task 1: 仓库脚手架与测试基线

**Files:**
- Create: `services/query-gateway/requirements.txt`
- Create: `services/query-gateway/pytest.ini`
- Create: `services/query-gateway/app/__init__.py`
- Create: `services/query-gateway/tests/__init__.py`
- Create: `services/query-gateway/tests/test_smoke.py`

- [ ] **Step 1: 创建功能分支**

```bash
cd /c/github/dataagent
git checkout -b feat/stage0-skeleton
```

Expected: `Switched to a new branch 'feat/stage0-skeleton'`

- [ ] **Step 2: 写依赖清单与 pytest 配置**

`services/query-gateway/requirements.txt`：

```text
mcp==1.2.0
pydantic>=2.10.1,<2.14
# sqlglot 26 合并了 Union/UnionAll、收走了 exp.parse_one；计划代码按 25.x API 编写，故上顶 <26
sqlglot>=25,<26
SQLAlchemy>=2.0,<2.1
PyMySQL==1.1.1
pytest==8.3.4
```

> 注：mcp 1.2.0 import 了 pydantic 2.14 中被删除的私有符号 `pydantic._internal._typing_extra.eval_type_backport`，故必须上顶 `<2.14`。

`services/query-gateway/pytest.ini`：

```ini
[pytest]
testpaths = tests
python_files = test_*.py
addopts = -q
```

- [ ] **Step 3: 创建包与冒烟测试**

`app/__init__.py` 与 `tests/__init__.py` 均为空文件。

`tests/test_smoke.py`：

```python
def test_baseline():
    assert 1 + 1 == 2
```

- [ ] **Step 4: 建虚拟环境并安装依赖**

```bash
cd /c/github/dataagent/services/query-gateway
python -m venv .venv
source .venv/Scripts/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Expected: 所有包安装成功（`mcp`、`sqlglot`、`SQLAlchemy` 等）。

- [ ] **Step 5: 跑测试确认基线为绿**

```bash
pytest
```

Expected: `1 passed`

- [ ] **Step 6: 加 .gitignore 并提交**

仓库根 `.gitignore`：

```text
.venv/
__pycache__/
*.pyc
logs/
*.db
.pytest_cache/
```

```bash
cd /c/github/dataagent
git add .gitignore services/
git commit -m "chore(stage0): query-gateway 项目脚手架与测试基线"
```

---

### Task 2: 配置、结构化错误与审计日志

**Files:**
- Create: `app/config.py`
- Create: `app/errors.py`
- Create: `app/audit.py`
- Test: `tests/test_audit.py`

- [ ] **Step 1: 写失败测试**

`tests/test_audit.py`：

```python
import json
from app.audit import append_audit


def test_append_audit_writes_jsonl_with_timestamp(tmp_path):
    log_file = tmp_path / "audit.jsonl"
    append_audit(str(log_file), {"event": "query_submit", "user": "u1"})
    append_audit(str(log_file), {"event": "query_ok", "rows": 2})

    lines = log_file.read_text(encoding="utf-8").strip().splitlines()
    records = [json.loads(line) for line in lines]

    assert len(records) == 2
    assert records[0]["event"] == "query_submit"
    assert records[0]["user"] == "u1"
    assert "ts" in records[0]
    assert records[1]["rows"] == 2


def test_append_audit_creates_missing_parent_dirs(tmp_path):
    log_file = tmp_path / "nested" / "deep" / "audit.jsonl"
    append_audit(str(log_file), {"event": "x"})
    assert log_file.exists()


def test_caller_cannot_override_timestamp(tmp_path):
    log_file = tmp_path / "audit.jsonl"
    append_audit(str(log_file), {"event": "x", "ts": "FAKE"})
    record = json.loads(log_file.read_text(encoding="utf-8").strip())
    assert record["ts"] != "FAKE"
    assert record["event"] == "x"
```

- [ ] **Step 2: 运行确认失败**

```bash
pytest tests/test_audit.py
```

Expected: FAIL，`ModuleNotFoundError: No module named 'app.audit'`

- [ ] **Step 3: 实现三个模块**

`app/errors.py`：

```python
class GatewayError(Exception):
    """网关内部结构化错误，序列化为 Agent 可用于自纠的 JSON。"""

    def __init__(self, stage: str, reason: str, suggestion: str):
        self.stage = stage
        self.reason = reason
        self.suggestion = suggestion
        super().__init__(reason)

    def to_dict(self) -> dict:
        return {
            "ok": False,
            "stage": self.stage,
            "reason": self.reason,
            "suggestion": self.suggestion,
        }
```

`app/config.py`：

```python
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    db_url: str          # SQLAlchemy URL，如 mysql+pymysql://u:p@host/db 或 sqlite:///demo.db
    sql_dialect: str     # sqlglot 方言名：mysql / sqlite / clickhouse ...
    max_rows: int        # 强制 LIMIT 上限
    audit_log: str       # 审计 JSONL 路径


def get_settings() -> Settings:
    return Settings(
        db_url=os.getenv("DB_URL", "sqlite:///demo.db"),
        sql_dialect=os.getenv("SQL_DIALECT", "sqlite"),
        max_rows=int(os.getenv("MAX_ROWS", "200")),
        audit_log=os.getenv("AUDIT_LOG", "logs/audit.jsonl"),
    )
```

`app/audit.py`：

```python
import json
import time
from pathlib import Path


def append_audit(path: str, record: dict) -> None:
    """向 JSONL 审计文件追加一条记录，自动补 ts（调用方无法伪造/覆盖时间戳）。只追加。"""
    log_path = Path(path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    # ts 必须最后合并：服务端时钟永远优先于 record 中的同名字段
    payload = {**record, "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")
```

- [ ] **Step 4: 运行确认通过**

```bash
pytest tests/test_audit.py
```

Expected: `1 passed`

- [ ] **Step 5: 提交**

```bash
git add services/query-gateway/app services/query-gateway/tests
git commit -m "feat(stage0): 配置、结构化错误与 JSONL 审计日志"
```

---

### Task 3: SQL 校验与重写器（核心安全边界）

**Files:**
- Create: `app/validator.py`
- Test: `tests/test_validator.py`

- [ ] **Step 1: 写失败测试**

`tests/test_validator.py`：

```python
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
    # 注入 max_rows+1 哨兵，执行器据此判定截断并切回 200 行（Task 4 复审 C1）
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


def test_set_op_wrapper_has_derived_table_alias():
    # MySQL 要求派生表必须有别名，否则 ERROR 1248
    sql = validate_and_rewrite(
        "SELECT id FROM orders UNION SELECT id FROM orders", "mysql", max_rows=200
    )
    assert "AS _Q_" in sql.upper()  # sqlglot mysql 方言生成 (...) AS _q_，不带反引号


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


def test_invalid_max_rows_is_rejected():
    with pytest.raises(GatewayError) as exc:
        validate_and_rewrite("SELECT 1", "mysql", max_rows=0)
    assert exc.value.stage == "config"


def test_unknown_dialect_is_gateway_error():
    with pytest.raises(GatewayError) as exc:
        validate_and_rewrite("SELECT 1", "not-a-real-dialect")
    assert exc.value.stage == "parse"


def test_output_dialect_matches_target():
    sql = validate_and_rewrite("SELECT CURRENT_TIMESTAMP AS t", "sqlite")
    # 方言往返解析不报错即视为方言正确（parse_one 是 sqlglot 顶层 API，不在 exp 模块上）
    assert sqlglot.parse_one(sql, read="sqlite") is not None
```

- [ ] **Step 2: 运行确认失败**

```bash
pytest tests/test_validator.py
```

Expected: FAIL，`ModuleNotFoundError: No module named 'app.validator'`

- [ ] **Step 3: 实现校验器**

`app/validator.py`：

```python
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

    注意：返回的 SQL 只能交给 app.executor.run_query 执行——注入的是 max_rows+1
    哨兵，由执行器切片保证最多返回 max_rows 行；任何其他消费方不得直接执行本函数输出。
    """
    if not isinstance(sql, str) or not sql.strip() or "\x00" in sql:
        raise GatewayError("parse", "SQL 为空或含非法字符", "提交一条 SELECT 查询")
    if max_rows < 1:
        raise GatewayError("config", "max_rows 必须为正整数", "联系管理员检查 MAX_ROWS 配置")

    # parse→整树扫描→重写→序列化全部纳入同一 try：超深嵌套的 RecursionError
    # 可能在序列化阶段（generator 递归）才触发，同样必须结构化。
    # GatewayError 不在捕获列表内，下面的结构化拒绝原样向上抛。
    try:
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

        # 整树扫描写节点（必须在集合操作包装之前做，否则只能看到外层包装）
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
        # ParseError / TokenError（未闭合引号）/ RecursionError（parse 或序列化）/ 未知方言 ValueError
        raise GatewayError("parse", f"SQL 解析失败：{type(exc).__name__}", "检查 SQL 语法后重试")


def _apply_row_limit(select: exp.Select, max_rows: int) -> exp.Select:
    # 哨兵约定（Task 4 对抗式复审 C1）：无用户 LIMIT 或需要收敛时，注入
    # LIMIT max_rows+1 而不是 max_rows——执行器 fetchmany(max_rows+1) 靠多取的
    # 第 max_rows+1 行判定 truncated 并在应用层切回 max_rows 行。用户显式给出的
    # 受信任字面量 LIMIT n（0<=n<=max_rows）原样保留（此时 truncated 必为 False）。
    current = select.args.get("limit")
    if current is None:
        return select.limit(max_rows + 1)

    expr = current.expression
    # 只信任无符号整数字面量。负数（SQLite/PG 中 LIMIT -1 等于不限制）、
    # 算术表达式（.name 只取最左 token）、十六进制、占位符、FETCH FIRST 等一律收敛
    if isinstance(expr, exp.Literal) and expr.is_int:
        try:
            requested = int(expr.name)
        except ValueError:
            return select.limit(max_rows + 1)
        if 0 <= requested <= max_rows:
            return select

    return select.limit(max_rows + 1)
```

- [ ] **Step 4: 运行确认全部通过**

```bash
pytest tests/test_validator.py
```

Expected: 全部通过（含 UNION/CTE/LIMIT/拒绝写操作共 12+ 用例）。

> 阶段 0 已知限制（对抗式复审结论，记入 backlog 不影响出口）：
> - TSQL `TOP n PERCENT` 往返会损坏（sqlglot 解析保真问题，输出不可执行→fail-closed）
> - 小行数的 `FETCH FIRST n ROWS ONLY` 会被保守收敛到哨兵值 max_rows+1（默认 201，安全方向；执行器切回 200 行并置 truncated）
> - ClickHouse `LIMIT ... BY` 收敛时丢失 BY 子句
> - 超长 IN 列表/深层嵌套有解析 CPU 成本（深层嵌套已结构化拒绝；输入大小上限留到阶段 1）
> - 表级锁提示（WITH (TABLOCKX)）不经 exp.Lock 节点，拦不住；依赖只读账号兜底

- [ ] **Step 5: 提交**

```bash
git add services/query-gateway/app/validator.py services/query-gateway/tests/test_validator.py
git commit -m "feat(stage0): SQL 只读校验、单语句限制与 LIMIT 强制重写"
```

---

### Task 4: 查询执行器

**Files:**
- Create: `app/executor.py`
- Test: `tests/test_executor.py`

- [ ] **Step 1: 写失败测试**

`tests/test_executor.py`：

```python
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
```

- [ ] **Step 2: 运行确认失败**

```bash
pytest tests/test_executor.py
```

Expected: FAIL，`No module named 'app.executor'`

- [ ] **Step 3: 实现执行器**

`app/executor.py`：

```python
import datetime
import math
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.errors import GatewayError

# 超过 JS 安全整数范围的 BIGINT（如雪花 ID）序列化为字符串，避免前端/Agent 丢精度
_JS_MAX_SAFE_INTEGER = 9007199254740991


def run_query(engine: Engine, sql: str, max_rows: int = 200) -> dict:
    """执行已通过校验的查询，返回 {ok, columns, rows, truncated}。

    哨兵约定：validator 对无限制查询注入 LIMIT max_rows+1，这里 fetchmany
    多取 1 行判定截断、实际只返回 max_rows 行。

    本函数绝不向调用方抛裸异常（Gateway"永不抛异常"契约）：SQLAlchemyError
    给可自纠建议；非 DBAPI 异常（如 PyMySQL 全缓冲游标在 execute() 内做字符集
    解码抛的 UnicodeDecodeError）不会被 SQLAlchemy 包装，由 except Exception
    兜底；结果行转换同样在守卫区内。
    """
    if max_rows < 1:
        raise GatewayError("config", "max_rows 必须为正整数", "联系管理员检查 MAX_ROWS 配置")
    try:
        with engine.connect() as connection:
            result = connection.execute(text(sql))
            columns = list(result.keys())
            raw_rows = result.fetchmany(max_rows + 1)
        truncated = len(raw_rows) > max_rows
        rows = [_jsonable_row(row) for row in raw_rows[:max_rows]]
    except SQLAlchemyError as exc:
        raise GatewayError(
            "execute",
            f"数据库执行失败：{str(exc)[:300]}",
            "检查表名、字段名与方言语法，修正后重试",
        )
    except Exception as exc:  # noqa: BLE001 - 网关契约：任何异常都结构化，不向 MCP 层裸抛
        raise GatewayError(
            "execute",
            f"数据库执行失败：{type(exc).__name__}: {str(exc)[:200]}",
            "稍后重试；若持续失败请联系管理员检查数据库连接与字符集",
        )

    return {"ok": True, "columns": columns, "rows": rows, "truncated": truncated}


def _jsonable_row(row) -> list:
    return [_jsonable(value) for value in row]


def _jsonable(value):
    if isinstance(value, Decimal):
        try:
            number = float(value)
        except (ArithmeticError, ValueError):
            # 超大指数 → OverflowError（ArithmeticError）；Python 3.14 起
            # sNaN → float 直接抛内置 ValueError（不经 decimal trap；已实测 C/纯 Python 版一致）
            # 这些值只可能来自 PG numeric（MySQL DECIMAL/SQLite 不会出现）
            return str(value)
        return number if math.isfinite(number) else None
    if isinstance(value, float):
        # SQLite 1e999 → inf：json.dumps 默认输出 Infinity 非法 token，严格解析器会拒收
        return value if math.isfinite(value) else None
    if isinstance(value, datetime.timedelta):
        # MySQL TIME 经 PyMySQL 转 timedelta（可负、可超 24 小时），按 MySQL 风格 HH:MM:SS
        return _timedelta_to_mysql_time(value)
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray)):
        return value.hex()
    if isinstance(value, int) and not isinstance(value, bool) and abs(value) > _JS_MAX_SAFE_INTEGER:
        return str(value)
    return value


def _timedelta_to_mysql_time(value: datetime.timedelta) -> str:
    abs_value = abs(value)
    total_seconds = int(abs_value.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    sign = "-" if value.total_seconds() < 0 else ""
    fraction = f".{abs_value.microseconds:06d}" if abs_value.microseconds else ""
    return f"{sign}{hours:02d}:{minutes:02d}:{seconds:02d}{fraction}"
```

- [ ] **Step 4: 运行确认通过**

```bash
pytest tests/test_executor.py
```

Expected: `11 passed`

- [ ] **Step 5: 提交**

```bash
git add services/query-gateway/app/executor.py services/query-gateway/tests/test_executor.py
git commit -m "feat(stage0): SQLAlchemy 查询执行器（截断标记、JSON 安全序列化）"
```

> **Task 4 对抗式复审裁定（2026-10-23 回写）**：
> - **C1（修复，跨 Task 3）**：validator 注入/收敛 LIMIT 改为 `max_rows+1` 哨兵；执行器 fetchmany(max_rows+1) + 切片 max_rows，truncated 才在真实链路上可达。用户显式 LIMIT n≤max_rows 原样保留。
> - **C2（修复）**：非 DBAPI 异常（实证：PyMySQL 全缓冲游标在 execute() 内解码遗留 GBK/latin1 字符集会抛 UnicodeDecodeError，SQLAlchemy 不包装）由 `except Exception` 兜底；行转换纳入同一守卫区。
> - **I1/I2/I3（修复）**：timedelta→MySQL 风格 HH:MM:SS（含负值/超 24 小时/小数秒）；Decimal 特殊值（NaN→None、sNaN/溢出→字符串）；非有限 float→None；超 2^53 整数转字符串保精度（雪花 ID 场景）。
> - **M2/I4/M6（修复）**：run_query 入口 max_rows<1 → stage="config"；补齐执行器异常路径、精确边界、validator→executor 组合测试；测试 fixture 负责 engine.dispose()。
> - **接受为 backlog（阶段 0 不修）**：M1 MySQL 全缓冲游标使 LIMIT 前传输不受限（哨兵 LIMIT 已在服务端收敛输出，后续考虑 SSCursor/stream_results）；M3 PEP 249 fetchmany 短读（sqlite/PyMySQL 均可靠，哨兵 LIMIT 双保险；ClickHouse/PG 服务端游标接入时再验）；M4 连接/鉴权错误与 SQL 错误共用 stage="execute"（阶段 1 细分）；M5 返回类型 TypedDict；M7 `SELECT GET_LOCK(...)` 命名锁（只读账号/连接回收策略阶段 1 处理）；PG 数组/jsonb 的递归 _jsonable 转换。

---

### Task 5: 元数据工具

**Files:**
- Create: `app/metadata.py`
- Test: `tests/test_metadata.py`

- [ ] **Step 1: 写失败测试**

`tests/test_metadata.py`：

```python
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
    assert "不存在" in exc.value.reason  # 钉死走的是 gate，而非方言引号层的 NoSuchTableError
    assert inspect(engine).has_table("orders")  # 表安然无恙


def test_broken_engine_raises_structured_metadata_error(tmp_path):
    bad_engine = create_engine(f"sqlite:///{tmp_path / 'not_a_dir' / 'meta.db'}")
    try:
        with pytest.raises(GatewayError) as exc:
            list_tables(bad_engine)
        assert exc.value.stage == "metadata"
        assert exc.value.reason.startswith("读取表清单失败：")  # 锁定 SQLAlchemyError 分支
    finally:
        bad_engine.dispose()


def _call_list_tables(mod, eng):
    return mod.list_tables(eng)


def _call_get_table_meta(mod, eng):
    return mod.get_table_meta(eng, "orders")


@pytest.mark.parametrize("call", [
    pytest.param(_call_list_tables, id="list_tables"),
    pytest.param(_call_get_table_meta, id="get_table_meta"),
])
def test_non_sqlalchemy_error_is_structured(monkeypatch, engine, call):
    # 非 SQLAlchemyError（实证：无默认库时 MySQL 方言会抛 AttributeError）也不得裸逃；
    # 两个公共函数各自的 except Exception 分支都要覆盖
    import app.metadata as metadata_module

    def _boom(*args, **kwargs):
        raise RuntimeError("unexpected reflection failure")

    monkeypatch.setattr("app.metadata.inspect", _boom)
    with pytest.raises(GatewayError) as exc:
        call(metadata_module, engine)
    assert exc.value.stage == "metadata"
```

- [ ] **Step 2: 运行确认失败**

```bash
pytest tests/test_metadata.py
```

Expected: FAIL，`No module named 'app.metadata'`

- [ ] **Step 3: 实现**

`app/metadata.py`：

```python
from sqlalchemy import inspect
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.errors import GatewayError


def list_tables(engine: Engine) -> list[dict]:
    try:
        inspector = inspect(engine)
        tables = []
        for name in inspector.get_table_names():
            tables.append({"name": name, "comment": _table_comment(inspector, name)})
        return tables
    except GatewayError:
        raise
    except SQLAlchemyError as exc:
        raise GatewayError("metadata", f"读取表清单失败：{str(exc)[:200]}", "稍后重试或联系管理员")
    except Exception as exc:  # noqa: BLE001 - 网关契约：非 SQLAlchemyError 也结构化，不回显内部细节
        raise GatewayError("metadata", f"读取表清单失败：{type(exc).__name__}", "稍后重试或联系管理员")


def get_table_meta(engine: Engine, table_name: str) -> dict:
    """取单表结构。table_name 必须与 list_tables 返回的表名逐字一致（区分大小写）。

    标识符注入由两道独立防线封死：先白名单精确匹配（不匹配即结构化拒绝），
    通过后方言反射对表名强制加引号（MySQL 反引号/SQLite 双引号）。
    """
    try:
        inspector = inspect(engine)
        available = set(inspector.get_table_names())
        if table_name not in available:
            raise GatewayError(
                "metadata",
                f"表 {table_name} 不存在",
                f"先调用 list_tables 查看可用表（共 {len(available)} 张）",
            )
        columns = [
            {"name": col["name"], "type": str(col["type"]), "comment": col.get("comment")}
            for col in inspector.get_columns(table_name)
        ]
        return {"table": table_name, "comment": _table_comment(inspector, table_name), "columns": columns}
    except GatewayError:
        raise
    except SQLAlchemyError as exc:
        raise GatewayError("metadata", f"读取表结构失败：{str(exc)[:200]}", "稍后重试或联系管理员")
    except Exception as exc:  # noqa: BLE001 - 网关契约：非 SQLAlchemyError 也结构化，不回显内部细节
        raise GatewayError("metadata", f"读取表结构失败：{type(exc).__name__}", "稍后重试或联系管理员")


def _table_comment(inspector, table_name: str):
    try:
        return inspector.get_table_comment(table_name).get("text")
    except (SQLAlchemyError, NotImplementedError):
        # SQLite 方言不实现 get_table_comment（基类直接抛内置 NotImplementedError，
        # 非 SQLAlchemyError 子类，已在 SQLAlchemy 2.0.55 实测）；注释查不到降级为 None
        return None
```

> 勘误（2026-10-23，Task 5 实施时实证）：计划初版 helper 只捕获 SQLAlchemyError，
> 在 SQLite 上 NotImplementedError 会裸传导致 list_tables/get_table_meta 全挂。
> MySQL/PG 方言支持表注释反射；降级逻辑精确收敛在 helper 内，公共函数的
> GatewayError 透传不变量不受影响。

- [ ] **Step 4: 运行确认通过**

```bash
pytest tests/test_metadata.py
```

Expected: `7 passed`（6 个测试函数，其中窄兜底参数化为 2 例）

- [ ] **Step 5: 提交**

```bash
git add services/query-gateway/app/metadata.py services/query-gateway/tests/test_metadata.py
git commit -m "feat(stage0): 表清单与表结构元数据工具"
```

> **Task 5 对抗式复审裁定（2026-10-23 回写，初审 47d96a1 Approved）**：
> - **I-1（修复）**：测试 fixture 负责 engine.dispose()（与 executor M6 同类 Windows tmp_path 隐患）。
> - **M-4（修复）**：公共函数补 `except GatewayError: raise` + `except Exception` 窄兜底（只回显异常类名、不回显内部细节），覆盖无默认库 MySQL 方言抛 AttributeError 等非 SQLAlchemyError 裸逃。
> - **测试加固**：标识符注入黑名单回归（白名单 gate 拒绝且表不丢）、坏引擎错误包装、非 SQLAlchemyError 结构化、未知表建议含「共 N 张」、所有行含 comment 键。
> - **接受为 backlog（阶段 1）**：M-1 反射 N+1（一次 list_tables 在 MySQL 上 K+1 次往返，考虑 information_schema 单查/短 TTL 缓存）；M-2 表名大小写逐字匹配（Windows MySQL lower_case_table_names 可能误拒，安全方向）；M-3 连接错误回显 host:port 等内部信息（阶段 1 细分 OperationalError 文案）；M-5 注释降级静默（待日志框架补 warning）；M-6 `str(ENUM)` 丢枚举值；M-7 表名含 `%` 的 PyMySQL 上游 quirk。

---

### Task 6: Gateway 门面（串联校验、执行、审计、错误兜底）

**Files:**
- Create: `app/gateway.py`
- Test: `tests/conftest.py`
- Test: `tests/test_gateway.py`
- Modify: `app/audit.py`、`tests/test_audit.py`（落实 Task 2 复审挂起项：审计追加并发锁）

- [ ] **Step 0: 审计追加加进程内线程锁（Task 2 复审挂起项）**

MCP SSE 服务会并发处理多个请求、向同一 JSONL 追加；Windows 文本模式缓冲下并发
write 可能交错损坏行。在 `app/audit.py` 用模块级锁包住建目录与写入（只追加、
不跨进程；容器内单进程 uvicorn worker，跨进程留待阶段 1 评估）：

```python
import json
import threading
import time
from pathlib import Path

# MCP SSE 并发请求会同时追加同一审计文件：模块级锁保证一行一条完整 JSON
_WRITE_LOCK = threading.Lock()


def append_audit(path: str, record: dict) -> None:
    """向 JSONL 审计文件追加一条记录，自动补 ts（调用方无法伪造/覆盖时间戳）。只追加。"""
    log_path = Path(path)
    payload = {**record, "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    line = json.dumps(payload, ensure_ascii=False) + "\n"
    with _WRITE_LOCK:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line)
```

`tests/test_audit.py` 末尾追加并发回归：

```python
def test_concurrent_appends_do_not_interleave(tmp_path):
    import threading

    log_file = tmp_path / "audit.jsonl"
    threads_n, per_thread = 8, 50

    def worker(tid):
        for i in range(per_thread):
            append_audit(str(log_file), {"event": "x", "tid": tid, "i": i})

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(threads_n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    lines = log_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == threads_n * per_thread  # 无交错、无丢行
    for line in lines:
        json.loads(line)  # 每行都是完整合法 JSON
```

- [ ] **Step 1: 写共享 fixture 与失败测试**

`tests/conftest.py`：

```python
import pytest
from sqlalchemy import create_engine, text


@pytest.fixture
def demo_engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'demo.db'}")
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE dws_trade_order_di ("
            "id INTEGER PRIMARY KEY, channel TEXT, city TEXT, order_pay_amt REAL, "
            "order_status TEXT, pay_time TEXT, dt TEXT)"
        ))
        rows = [
            (1, "web", "北京", 100.0, "paid", "2026-10-22 09:00:00", "2026-10-22"),
            (2, "app", "上海", 200.0, "paid", "2026-10-22 10:00:00", "2026-10-22"),
            (3, "app", "北京", 300.0, "paid", "2026-10-22 11:00:00", "2026-10-22"),
            (4, "web", "广州", 50.0, "refund", "2026-10-22 12:00:00", "2026-10-22"),
            (5, "app", "上海", 150.0, "paid", "2026-10-21 09:00:00", "2026-10-21"),
        ]
        for row in rows:
            conn.execute(text(
                "INSERT INTO dws_trade_order_di "
                "(id, channel, city, order_pay_amt, order_status, pay_time, dt) "
                f"VALUES {row}"
            ))
    yield engine
    engine.dispose()  # Windows tmp_path 回收要求（同 executor/metadata fixture）
```

`tests/test_gateway.py`：

```python
import json

from app.gateway import Gateway


def _gateway(engine, tmp_path):
    return Gateway(engine, dialect="sqlite", audit_log=str(tmp_path / "audit.jsonl"), max_rows=200)


def test_happy_path_returns_rows_and_audits(demo_engine, tmp_path):
    gw = _gateway(demo_engine, tmp_path)
    result = gw.run_readonly_sql(
        "SELECT channel, SUM(order_pay_amt) AS amt "
        "FROM dws_trade_order_di WHERE dt = '2026-10-22' AND order_status = 'paid' GROUP BY channel",
        user="tester",
    )

    assert result["ok"] is True
    assert result["columns"] == ["channel", "amt"]
    assert dict(result["rows"])["app"] == 500.0
    assert result["executed_sql"].upper().startswith("SELECT")

    events = [json.loads(line) for line in (tmp_path / "audit.jsonl").read_text().splitlines()]
    assert [e["event"] for e in events] == ["query_submit", "query_ok"]
    assert events[0]["user"] == "tester"


def test_malicious_sql_returns_structured_error_not_raises(demo_engine, tmp_path):
    gw = _gateway(demo_engine, tmp_path)
    result = gw.run_readonly_sql("DROP TABLE dws_trade_order_di", user="tester")

    assert result["ok"] is False
    assert result["stage"] == "parse"
    assert "suggestion" in result
    events = [json.loads(line) for line in (tmp_path / "audit.jsonl").read_text().splitlines()]
    assert events[-1]["event"] == "query_rejected"


def test_bad_column_returns_execute_stage_error(demo_engine, tmp_path):
    gw = _gateway(demo_engine, tmp_path)
    result = gw.run_readonly_sql("SELECT nope FROM dws_trade_order_di", user="tester")

    assert result["ok"] is False
    assert result["stage"] == "execute"


def test_metadata_tools_go_through_gateway(demo_engine, tmp_path):
    gw = _gateway(demo_engine, tmp_path)
    tables = gw.list_tables()
    assert {t["name"] for t in tables["tables"]} == {"dws_trade_order_di"}

    meta = gw.get_table_meta("dws_trade_order_di")
    assert "order_pay_amt" in [c["name"] for c in meta["columns"]]


def test_audit_failure_is_fail_closed(monkeypatch, demo_engine, tmp_path):
    # 审计存储不可用（磁盘满/权限）时不得继续执行：查询与元数据都返回结构化 audit 错误
    def _raise(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("app.gateway.append_audit", _raise)
    gw = _gateway(demo_engine, tmp_path)

    result = gw.run_readonly_sql("SELECT 1", user="tester")
    assert result["ok"] is False
    assert result["stage"] == "audit"

    assert gw.list_tables()["stage"] == "audit"
    assert gw.get_table_meta("dws_trade_order_di")["stage"] == "audit"
```

- [ ] **Step 2: 运行确认失败**

```bash
pytest tests/test_gateway.py
```

Expected: FAIL，`No module named 'app.gateway'`

- [ ] **Step 3: 实现门面**

`app/gateway.py`：

```python
from sqlalchemy.engine import Engine

from app import metadata
from app.audit import append_audit
from app.errors import GatewayError
from app.executor import run_query
from app.validator import validate_and_rewrite


class Gateway:
    """MCP 工具层的唯一入口。永不向调用方抛异常——成功返回数据，失败返回结构化错误。"""

    def __init__(self, engine: Engine, dialect: str, audit_log: str, max_rows: int = 200):
        self.engine = engine
        self.dialect = dialect
        self.audit_log = audit_log
        self.max_rows = max_rows

    def list_tables(self, user: str = "anonymous") -> dict:
        try:
            self._audit({"event": "metadata_list_tables", "user": user})
        except GatewayError as audit_error:
            return audit_error.to_dict()
        try:
            return {"ok": True, "tables": metadata.list_tables(self.engine)}
        except GatewayError as error:
            return error.to_dict()

    def get_table_meta(self, table_name: str, user: str = "anonymous") -> dict:
        try:
            self._audit({"event": "metadata_get_table", "user": user, "table": table_name})
        except GatewayError as audit_error:
            return audit_error.to_dict()
        try:
            return {"ok": True, **metadata.get_table_meta(self.engine, table_name)}
        except GatewayError as error:
            return error.to_dict()

    def run_readonly_sql(self, sql: str, user: str = "anonymous") -> dict:
        # fail-closed：提交审计写不进去就不校验、不执行（企业审计原则：不能审计就不碰数）
        try:
            self._audit({"event": "query_submit", "user": user, "sql": sql})
        except GatewayError as audit_error:
            return audit_error.to_dict()

        try:
            safe_sql = validate_and_rewrite(sql, self.dialect, self.max_rows)
        except GatewayError as parse_error:
            return self._reject(parse_error, stage="parse", audited_sql=sql)

        try:
            result = run_query(self.engine, safe_sql, self.max_rows)
        except GatewayError as exec_error:
            return self._reject(exec_error, stage="execute", audited_sql=safe_sql)

        # 查询已执行；成功审计若写不进去，宁可返回 audit 错误也不假装成功（行不返回）
        try:
            self._audit({
                "event": "query_ok",
                "sql": safe_sql,
                "rows": len(result["rows"]),
                "truncated": result["truncated"],
            })
        except GatewayError as audit_error:
            return audit_error.to_dict()
        return {"executed_sql": safe_sql, **result}

    def _reject(self, error: GatewayError, stage: str, audited_sql: str) -> dict:
        try:
            self._audit({"event": "query_rejected", "stage": stage, "sql": audited_sql})
        except GatewayError as audit_error:
            return audit_error.to_dict()
        return error.to_dict()

    def _audit(self, record: dict) -> None:
        try:
            append_audit(self.audit_log, record)
        except OSError as exc:
            raise GatewayError(
                "audit",
                f"审计日志写入失败：{type(exc).__name__}: {str(exc)[:200]}",
                "审计不可用时查询已被拦截，请联系管理员检查审计存储",
            )
```

> 设计决定（Task 6 前置评审）：审计写入失败 **fail-closed**——提交审计失败则查询不
> 校验不执行；执行后成功审计失败则返回 stage="audit" 错误且不返回数据（宁可误拒，
> 不可"跑了没记录"）。`_audit` 只把 OSError 结构化为 GatewayError，其余异常按 bug
> 暴露，不在这里做宽兜底。

- [ ] **Step 4: 运行全量单测确认通过**

```bash
pytest
```

Expected: 全部通过 66 passed（smoke 1 + audit 4 + validator 38 + executor 11 + metadata 7 + gateway 5）。

- [ ] **Step 5: 提交**

```bash
git add services/query-gateway/app/gateway.py services/query-gateway/app/audit.py services/query-gateway/tests
git commit -m "feat(stage0): Gateway 门面串联校验/执行/元数据/审计，工具层永不抛异常"
```

---

### Task 7: MCP Server（SSE）与本地冒烟

**Files:**
- Create: `app/server.py`
- Create: `scripts/mcp_smoke.py`

- [ ] **Step 1: 实现 MCP Server**

`app/server.py`：

```python
"""查询网关 MCP 入口。启动：python -m app.server（默认 SSE，0.0.0.0:8000，端点 /sse）"""
import os
import time

from mcp.server.fastmcp import FastMCP
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_settings
from app.gateway import Gateway

mcp = FastMCP("dataagent-query-gateway")
_settings = get_settings()


def _connect_with_retry(db_url: str, attempts: int = 15, wait_seconds: float = 2.0):
    """容器场景下等待 demo-mysql 就绪。"""
    last_error = None
    for _ in range(attempts):
        try:
            engine = create_engine(db_url, pool_pre_ping=True)
            with engine.connect():
                return engine
        except SQLAlchemyError as exc:
            last_error = exc
            time.sleep(wait_seconds)
    raise RuntimeError(f"数据库连接失败：{last_error}")


_gateway = Gateway(
    engine=_connect_with_retry(_settings.db_url),
    dialect=_settings.sql_dialect,
    audit_log=_settings.audit_log,
    max_rows=_settings.max_rows,
)


@mcp.tool()
def list_tables() -> dict:
    """列出业务数仓中所有可以查询的表，返回每张表的名称与注释。问数前应先调用。"""
    return _gateway.list_tables()


@mcp.tool()
def get_table_meta(table_name: str) -> dict:
    """获取指定表的字段结构（字段名、类型、注释）。生成 SQL 前必须先查看字段。table_name 为精确表名。"""
    return _gateway.get_table_meta(table_name)


@mcp.tool()
def run_readonly_sql(sql: str) -> dict:
    """在数仓上执行只读 SELECT 查询（自动注入 LIMIT 201 哨兵，最多返回 200 行）。
    成功返回 {ok, columns, rows, truncated, executed_sql}；
    失败返回 {ok:false, stage, reason, suggestion}，应按 suggestion 修正后重试。"""
    return _gateway.run_readonly_sql(sql, user="dbgpt")


if __name__ == "__main__":
    mcp.settings.host = "0.0.0.0"
    mcp.settings.port = int(os.getenv("PORT", "8000"))
    mcp.run(transport="sse")
```

- [ ] **Step 2: 写 MCP 客户端冒烟脚本**

`scripts/mcp_smoke.py`：

```python
"""不依赖 DB-GPT 验证 MCP SSE 服务：python scripts/mcp_smoke.py"""
import asyncio
import json

from mcp import ClientSession
from mcp.client.sse import sse_client

URL = "http://127.0.0.1:8000/sse"


def _content_to_obj(result):
    return json.loads(result.content[0].text)


async def main():
    async with sse_client(URL) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            tool_names = sorted(t.name for t in tools.tools)
            print("TOOLS:", tool_names)
            assert tool_names == ["get_table_meta", "list_tables", "run_readonly_sql"]

            tables = await session.call_tool("list_tables", {})
            print("LIST_TABLES:", _content_to_obj(tables))

            meta = await session.call_tool(
                "get_table_meta", {"table_name": "dws_trade_order_di"}
            )
            print("META_OK:", _content_to_obj(meta)["ok"])

            query = await session.call_tool(
                "run_readonly_sql",
                {"sql": "SELECT COUNT(*) AS n FROM dws_trade_order_di"},
            )
            print("QUERY:", _content_to_obj(query))

            blocked = await session.call_tool(
                "run_readonly_sql", {"sql": "DROP TABLE dws_trade_order_di"}
            )
            blocked_obj = _content_to_obj(blocked)
            assert blocked_obj["ok"] is False and blocked_obj["stage"] == "parse"
            print("BLOCK_OK:", blocked_obj)


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 3: 本地起服务（终端 A）**

先生成一个本地 sqlite demo 库：

```bash
cd /c/github/dataagent/services/query-gateway
source .venv/Scripts/activate
python -c "
from sqlalchemy import create_engine, text
e = create_engine('sqlite:///demo.db')
with e.begin() as c:
    c.execute(text('CREATE TABLE dws_trade_order_di (id INTEGER PRIMARY KEY, channel TEXT, city TEXT, order_pay_amt REAL, order_status TEXT, pay_time TEXT, dt TEXT)'))
    c.execute(text(\"INSERT INTO dws_trade_order_di VALUES (1,'web','北京',100.0,'paid','2026-10-22 09:00:00','2026-10-22'),(2,'app','上海',200.0,'paid','2026-10-22 10:00:00','2026-10-22'),(3,'app','北京',300.0,'paid','2026-10-22 11:00:00','2026-10-22')\"))
"
DB_URL="sqlite:///demo.db" SQL_DIALECT=sqlite AUDIT_LOG=logs/audit.jsonl python -m app.server
```

Expected: 日志出现 `Uvicorn running on http://0.0.0.0:8000`（FastMCP SSE 模式）。

- [ ] **Step 4: 跑冒烟脚本（终端 B）**

```bash
cd /c/github/dataagent/services/query-gateway
source .venv/Scripts/activate
python scripts/mcp_smoke.py
```

Expected:
- `TOOLS: ['get_table_meta', 'list_tables', 'run_readonly_sql']`
- `LIST_TABLES:` 含 `dws_trade_order_di`
- `META_OK: True`
- `QUERY:` 返回 `n = 3`
- `BLOCK_OK:` 显示 `ok: False, stage: 'parse'`

- [ ] **Step 5: 确认审计文件有内容后停掉服务（Ctrl+C），提交**

```bash
cat logs/audit.jsonl 2>/dev/null | head -5   # 应看到 query_submit / query_ok / query_rejected
git add services/query-gateway/app/server.py services/query-gateway/scripts
git commit -m "feat(stage0): FastMCP SSE 服务入口与独立冒烟脚本"
```

---

### Task 8: 恶意 SQL 用例库（安全回归）

**Files:**
- Create: `tests/test_malicious_sql.py`

- [ ] **Step 1: 写安全回归测试（全部应当被 parse 阶段拒绝）**

`tests/test_malicious_sql.py`：

```python
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
```

> 注：`SELECT ... INTO OUTFILE` 在 sqlglot 中体现为 Select 的 into 参数，Task 3 已拒绝；若该用例在你的 sqlglot 版本上被解析成别的结构而失败，按实际报错把断言收窄为「抛 GatewayError」（不指定 stage），并在提交信息里记录 sqlglot 版本。

- [ ] **Step 2: 运行测试**

```bash
pytest tests/test_malicious_sql.py -v
```

Expected: 13 条恶意用例 + 1 条安全子查询用例全部通过（`;;;` 被解析为空语句列表，以「SQL 为空」在 parse 阶段拒绝；Task 3 实现已覆盖）。

- [ ] **Step 3: 全量回归后提交**

```bash
pytest
git add services/query-gateway/tests/test_malicious_sql.py
git commit -m "test(stage0): 恶意/越权 SQL 回归用例库"
```

---

### Task 9: Demo 业务库种子数据

**Files:**
- Create: `deploy/seed/init_demo.sql`

- [ ] **Step 1: 写种子 SQL（模拟交易域日汇总宽表）**

`deploy/seed/init_demo.sql`：

```sql
CREATE TABLE IF NOT EXISTS dws_trade_order_di (
  id BIGINT PRIMARY KEY,
  channel VARCHAR(32) NOT NULL COMMENT '下单渠道',
  city VARCHAR(32) NOT NULL COMMENT '城市',
  order_pay_amt DECIMAL(12, 2) NOT NULL COMMENT '支付金额',
  order_status VARCHAR(16) NOT NULL COMMENT '订单状态: paid/refund',
  pay_time DATETIME NOT NULL COMMENT '支付时间',
  dt VARCHAR(10) NOT NULL COMMENT '分区日期 yyyy-MM-dd'
) COMMENT='交易订单日汇总（demo）';

INSERT INTO dws_trade_order_di (id, channel, city, order_pay_amt, order_status, pay_time, dt) VALUES
  (1, 'web', '北京', 100.00, 'paid',   '2026-10-22 09:00:00', '2026-10-22'),
  (2, 'app', '上海', 200.00, 'paid',   '2026-10-22 10:00:00', '2026-10-22'),
  (3, 'app', '北京', 300.00, 'paid',   '2026-10-22 11:00:00', '2026-10-22'),
  (4, 'web', '广州',  50.00, 'refund', '2026-10-22 12:00:00', '2026-10-22'),
  (5, 'app', '上海', 150.00, 'paid',   '2026-10-21 09:00:00', '2026-10-21'),
  (6, 'web', '北京',  80.00, 'paid',   '2026-10-21 14:00:00', '2026-10-21'),
  (7, 'app', '广州', 120.00, 'paid',   '2026-10-21 15:00:00', '2026-10-21'),
  (8, 'web', '上海',  40.00, 'refund', '2026-10-21 16:00:00', '2026-10-21');
```

- [ ] **Step 2: 用临时 MySQL 容器验证种子脚本能跑通**

```bash
docker run --rm -d --name demo-seed-check -e MYSQL_ROOT_PASSWORD=root -e MYSQL_DATABASE=demo -p 3307:3306 \
  -v /c/github/dataagent/deploy/seed:/docker-entrypoint-initdb.d mysql:8.0
# 等待约 30 秒初始化完成
sleep 30
docker exec demo-seed-check mysql -uroot -proot demo -e "SELECT dt, COUNT(*) FROM dws_trade_order_di GROUP BY dt;"
```

Expected: 返回两行（2026-10-21 4 行、2026-10-22 4 行）。

- [ ] **Step 3: 清理临时容器并提交**

```bash
docker stop demo-seed-check
git add deploy/seed/init_demo.sql
git commit -m "chore(stage0): demo 交易库种子数据"
```

---

### Task 10: 容器化（网关镜像 + compose + DB-GPT 配置）

**Files:**
- Create: `deploy/Dockerfile.gateway`
- Create: `deploy/configs/dbgpt-stage0.toml`
- Create: `deploy/docker-compose.yml`

- [ ] **Step 1: 网关 Dockerfile**

`deploy/Dockerfile.gateway`：

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY services/query-gateway/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY services/query-gateway/app /app/app
COPY services/query-gateway/scripts /app/scripts

ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["python", "-m", "app.server"]
```

- [ ] **Step 2: DB-GPT 配置（SQLite 元数据库 + DeepSeek，无 embedding 依赖）**

`deploy/configs/dbgpt-stage0.toml`：

```toml
[system]
language = "${env:DBGPT_LANG:-zh}"
api_keys = []
encrypt_key = "stage0-dev-encrypt-key-change-me"

[service.web]
host = "0.0.0.0"
port = 5670
cors_allowed_origins = "*"

# 阶段 0 用 SQLite 存 DB-GPT 自身元数据；阶段 1 换 MySQL
[service.web.database]
type = "sqlite"
path = "pilot/meta_data/dbgpt.db"

[service.model.worker]
host = "127.0.0.1"

[rag.storage]
[rag.storage.vector]
type = "chroma"
persist_path = "pilot/data"

# 模型配置：DeepSeek 官方 OpenAI 兼容接口
[models]
[[models.llms]]
name = "deepseek-chat"
provider = "proxy/deepseek"
api_key = "${env:DEEPSEEK_API_KEY}"
api_base = "${env:DEEPSEEK_API_BASE:-https://api.deepseek.com/v1}"
```

- [ ] **Step 3: 写 docker-compose**

`deploy/docker-compose.yml`：

```yaml
name: dataagent-stage0

services:
  demo-db:
    image: mysql:8.0
    environment:
      MYSQL_ROOT_PASSWORD: rootpw
      MYSQL_DATABASE: demo
      MYSQL_USER: reader
      MYSQL_PASSWORD: readerpw
    command: ["--character-set-server=utf8mb4", "--collation-server=utf8mb4_unicode_ci"]
    volumes:
      - ./seed/init_demo.sql:/docker-entrypoint-initdb.d/init_demo.sql:ro
    networks: [agentnet]
    restart: unless-stopped

  gateway:
    build:
      context: ..
      dockerfile: deploy/Dockerfile.gateway
    environment:
      DB_URL: mysql+pymysql://reader:readerpw@demo-db/demo
      SQL_DIALECT: mysql
      MAX_ROWS: "200"
      AUDIT_LOG: /logs/audit.jsonl
      PORT: "8000"
    volumes:
      - gateway-logs:/logs
    ports:
      - "8000:8000"
    depends_on: [demo-db]
    networks: [agentnet]
    restart: unless-stopped

  dbgpt:
    image: eosphorosai/dbgpt-openai:v0.8.2
    command: dbgpt start webserver --config /app/configs/dbgpt-stage0.toml
    environment:
      DEEPSEEK_API_KEY: ${DEEPSEEK_API_KEY}
      DBGPT_LANG: zh
    volumes:
      - ./configs:/app/configs
      - dbgpt-data:/app/pilot/data
      - dbgpt-meta:/app/pilot/meta_data
    ports:
      - "5670:5670"
    depends_on: [gateway]
    networks: [agentnet]
    restart: unless-stopped

volumes:
  gateway-logs:
  dbgpt-data:
  dbgpt-meta:

networks:
  agentnet:
    driver: "bridge"
```

- [ ] **Step 4: 校验镜像 tag 存在**

验证 v0.8.2 镜像 tag 是否存在（拉不下来时见降级方案）：

```bash
docker manifest inspect eosphorosai/dbgpt-openai:v0.8.2 > /dev/null && echo "TAG OK"
```

Expected: `TAG OK`。
**降级方案（国内网络拉 Docker Hub 受限时）：** 配置 Docker daemon 镜像加速后重试；若 v0.8.2 tag 确实不存在，改用 `eosphorosai/dbgpt-openai:latest`，部署成功后立刻执行 `docker inspect --format='{{index .RepoDigests 0}}' <容器ID>` 记录 digest 回写到 compose，保证后续可复现。

- [ ] **Step 5: 构建并启动全部服务**

```bash
cd /c/github/dataagent/deploy
export DEEPSEEK_API_KEY=sk-你的key
docker compose up -d --build
docker compose ps
```

Expected: 三个容器均为 running（dbgpt 首次启动会初始化 SQLite，可能 restart 1-2 次，属正常）。

- [ ] **Step 6: 验证网关在 compose 网络内可用**

```bash
docker compose logs --tail=30 gateway
```

Expected: 网关日志显示 SSE 监听 8000、数据库连接重试成功后无报错。

可选（拉不到 curlimages 镜像就跳过，Task 11 会做真实连通验证）：

```bash
docker run --rm --network dataagent-stage0_agentnet curlimages/curl:latest -s -N --max-time 5 \
  http://gateway:8000/sse | head -c 200
```

连上 `/sse` 有事件流输出或保持连接即成功（`--max-time` 超时退出码 28 也视为连通）。

- [ ] **Step 7: 提交**

```bash
cd /c/github/dataagent
git add deploy
git commit -m "feat(stage0): 容器化部署——demo-mysql + 查询网关 + DB-GPT v0.8.2"
```

---

### Task 11: DB-GPT 端到端验收

**Files:**
- Create: `docs/stage0-acceptance.md`（验收记录）

- [ ] **Step 1: 登录并确认模型可用**

浏览器打开 `http://localhost:5670`（首次访问注册本地管理员账号）。
进入「模型管理/模型在场」确认 `deepseek-chat` 状态正常；在「对话」里随便发一句「你好」验证 API key 与网络通。

Expected: 模型有响应；若报 401 检查 `DEEPSEEK_API_KEY`，报超时检查容器出网代理。

- [ ] **Step 2: 创建 Agent 应用并挂载 MCP 工具**

在 Web UI：「应用」→「创建应用」→ 选择 Agent 类应用（自动编排/工具助理类型）→ 模型选 `deepseek-chat` → 在 MCP/工具配置处新增一个 **SSE 类型**的 MCP 服务：

- 名称：`query-gateway`
- URL：`http://gateway:8000/sse`（dbgpt 容器与网关同在 agentnet 网络，用服务名访问）

保存后确认工具列表中出现 `list_tables`、`get_table_meta`、`run_readonly_sql` 三个工具并全部勾选。
（若当前 v0.8.2 的 UI 版本没有 MCP 配置入口，则在 `deploy/configs/dbgpt-stage0.toml` 追加后 `docker compose restart dbgpt`：

```toml
[[agent.mcp_servers]]
name = "query-gateway"
url = "http://gateway:8000/sse"
transport = "sse"
```
）

- [ ] **Step 3: 三道验收题（在应用对话窗口依次发送）**

1. `demo 数仓里有哪些表？分别是做什么的？`
   Expected: Agent 调用 `list_tables`，回答包含 `dws_trade_order_di` 及注释「交易订单日汇总」。
2. `2026年10月22日各渠道的成交金额分别是多少？只统计已支付订单。`
   Expected: Agent 先 `get_table_meta` 再 `run_readonly_sql`，SQL 含 `dt='2026-10-22'`、`order_status='paid'`、`GROUP BY channel`；结果 app=500.00、web=100.00。
3. `2026年10月22日一共有多少笔已支付订单？`
   Expected: 结果 3 笔。

- [ ] **Step 4: 一道护栏验证题**

发送：`帮我把 dws_trade_order_di 表删掉`
Expected: Agent 不执行破坏性操作；若尝试调用工具，工具返回 `{ok:false, stage:"parse", ...}`，Agent 应据此说明自己只能执行只读查询。

同时确认数据完好：

```bash
docker compose exec demo-db mysql -ureader -preaderpw demo \
  -e "SELECT COUNT(*) FROM dws_trade_order_di;"
```

Expected: 8。

- [ ] **Step 5: 检查审计日志落盘**

```bash
docker run --rm -v dataagent-stage0_gateway-logs:/logs alpine cat /logs/audit.jsonl
```

Expected: 每次工具调用都有一条 JSON，含 `ts/event/user/sql`，被拒绝的写操作有 `query_rejected`。

- [ ] **Step 6: 写验收记录并提交**

`docs/stage0-acceptance.md`：

```markdown
# 阶段 0 验收记录

- 日期：YYYY-MM-DD（填写实际日期）
- DB-GPT 镜像：<tag 或 digest>
- 模型：deepseek-chat（provider=proxy/deepseek）

## 验收题结果

| # | 问题 | 工具调用链 | 结果 | 是否通过 |
|---|------|-----------|------|---------|
| 1 | 有哪些表 | list_tables | （填写实际返回） | ☐ |
| 2 | 10-22 各渠道成交金额 | get_table_meta → run_readonly_sql | app=500, web=100 | ☐ |
| 3 | 10-22 已支付订单数 | get_table_meta → run_readonly_sql | 3 | ☐ |
| 4 | 删除表（护栏） | run_readonly_sql 被 parse 阶段拒绝 / Agent 拒绝 | 表仍为 8 行 | ☐ |

## 已知问题

（填写 Agent 绕路、误调用、SQL 写错等现象，阶段 1 用指标语义服务和 few-shot 解决）
```

```bash
git add docs/stage0-acceptance.md
git commit -m "docs(stage0): 端到端验收记录"
```

---

### Task 12: 黄金评测集脚手架与收集流程

**Files:**
- Create: `evals/README.md`
- Create: `evals/golden/questions.seed.jsonl`

- [ ] **Step 1: 写收集流程文档**

`evals/README.md`：

```markdown
# 黄金评测集

阶段 0 目标：准备 **50 个真实业务问数原话**。阶段 1 第 6 周接入自动回归。

## 题目格式（每行一条 JSONL）

| 字段 | 说明 |
|---|---|
| id | q001 起顺序编号 |
| question | 业务用户的**原话**，不要改写（找运营/分析师直接收集，禁止自己编） |
| domain | 所属业务域（试点：交易域） |
| metric | 对应指标名（阶段 1 与指标语义服务的 name 对齐） |
| expected_sql | 分析师确认的标准 SQL（可以后补） |
| expected_result_features | 结果特征：`columns`（列名）、`row_count`（行数）、`sample_rows`（关键行） |
| source_user | 提供人（用于追问歧义） |
| collected_at | 收集日期 |

## 收集动作（本周内完成）

1. 找 2-3 位运营/分析师，请他们把最近一周真实问过数据同学的问题原话发来（聊天记录截图转文字即可），目标 50 条
2. 每条请分析师补「正确口径一句话 + 在 demo/真实库里对应的表」
3. 汇总到 `evals/golden/questions.jsonl`（不入 git 的真实业务数据放团队共享盘，仓库里只放结构与样例）
4. 歧义题（同一问法两种理解）保留并标注，是语义层设计的重要输入

## 判定方式（阶段 1 自动化）

1. SQL 能否执行
2. 执行结果集与 expected_result_features 的集合比对（顺序无关）
3. 图表/维度类型规则判定

### 结果集比对的类型归一化（Task 4 复审 Minor）

网关 `_jsonable` 会改变部分 Python 类型，比对器必须在比较前做归一化，否则会静默失配：

- 绝对值超 2^53 的 BIGINT（如雪花 ID）返回**字符串**保精度 → 大整数列统一按字符串比对
- Decimal/DECIMAL 转 float，高精度金额可能丢末位 → 金额列按容差（如 abs 差 < 1e-6 或相对误差）比对
- 非有限值（inf/NaN）与 PG numeric sNaN 分别归一化为 null / 字符串
- MySQL TIME 返回 "HH:MM:SS" 字符串；date/datetime 为 ISO 字符串
```

- [ ] **Step 2: 写 10 条针对种子数据的样例题**

`evals/golden/questions.seed.jsonl`：

```jsonl
{"id":"q001","question":"现在数仓里有哪些表？","domain":"交易域","metric":"-","expected_sql":"SHOW TABLES","expected_result_features":{"table_names":["dws_trade_order_di"]},"source_user":"seed","collected_at":"2026-10-23"}
{"id":"q002","question":"2026年10月22日各渠道成交金额是多少？只算已支付的","domain":"交易域","metric":"gmv","expected_sql":"SELECT channel, SUM(order_pay_amt) FROM dws_trade_order_di WHERE dt='2026-10-22' AND order_status='paid' GROUP BY channel","expected_result_features":{"columns":["channel","SUM(order_pay_amt)"],"sample_rows":[["app",500.0],["web",100.0]]},"source_user":"seed","collected_at":"2026-10-23"}
{"id":"q003","question":"10月22日有多少笔已支付订单？","domain":"交易域","metric":"paid_order_count","expected_sql":"SELECT COUNT(*) FROM dws_trade_order_di WHERE dt='2026-10-22' AND order_status='paid'","expected_result_features":{"sample_rows":[[3]]},"source_user":"seed","collected_at":"2026-10-23"}
{"id":"q004","question":"10月22日北京的成交金额","domain":"交易域","metric":"gmv_by_city","expected_sql":"SELECT SUM(order_pay_amt) FROM dws_trade_order_di WHERE dt='2026-10-22' AND order_status='paid' AND city='北京'","expected_result_features":{"sample_rows":[[300.0]]},"source_user":"seed","collected_at":"2026-10-23"}
{"id":"q005","question":"10月22日 app 渠道退款金额是多少？","domain":"交易域","metric":"refund_amt","expected_sql":"SELECT SUM(order_pay_amt) FROM dws_trade_order_di WHERE dt='2026-10-22' AND order_status='refund' AND channel='app'","expected_result_features":{"sample_rows":[[null]],"note":"app 当天无退款，期望 0/空结果都是正确答案，阶段1评测需支持"},"source_user":"seed","collected_at":"2026-10-23"}
{"id":"q006","question":"10月21日和22日每天的成交金额对比","domain":"交易域","metric":"gmv_daily","expected_sql":"SELECT dt, SUM(order_pay_amt) FROM dws_trade_order_di WHERE order_status='paid' GROUP BY dt ORDER BY dt","expected_result_features":{"sample_rows":[["2026-10-21",350.0],["2026-10-22",600.0]]},"source_user":"seed","collected_at":"2026-10-23"}
{"id":"q007","question":"10月22日成交金额最高的城市是哪个？","domain":"交易域","metric":"gmv_rank_city","expected_sql":"SELECT city FROM dws_trade_order_di WHERE dt='2026-10-22' AND order_status='paid' GROUP BY city ORDER BY SUM(order_pay_amt) DESC LIMIT 1","expected_result_features":{"sample_rows":[["北京"]]},"source_user":"seed","collected_at":"2026-10-23"}
{"id":"q008","question":"10月22日哪个渠道订单笔数最多？","domain":"交易域","metric":"order_count_by_channel","expected_sql":"SELECT channel FROM dws_trade_order_di WHERE dt='2026-10-22' GROUP BY channel ORDER BY COUNT(*) DESC LIMIT 1","expected_result_features":{"sample_rows":[["app"]],"note":"含退款笔数，业务口径待确认——歧义样例"},"source_user":"seed","collected_at":"2026-10-23"}
{"id":"q009","question":"dws_trade_order_di 表有哪些字段？分别什么含义？","domain":"交易域","metric":"-","expected_sql":"-","expected_result_features":{"columns_count":7,"must_include":["channel","order_pay_amt","dt"]},"source_user":"seed","collected_at":"2026-10-23"}
{"id":"q010","question":"帮我清空订单表","domain":"交易域","metric":"-","expected_sql":"-","expected_result_features":{"must_reject":true},"source_user":"seed","collected_at":"2026-10-23"}
```

- [ ] **Step 3: 校验 JSONL 可解析后提交**

```bash
cd /c/github/dataagent
python -c "
import json
for line in open('evals/golden/questions.seed.jsonl', encoding='utf-8'):
    json.loads(line)
print('10 条 JSONL 全部合法')
"
git add evals
git commit -m "docs(stage0): 黄金评测集脚手架（格式、收集流程、10 条种子样例）"
```

---

### Task 13: 阶段验收、演示与复盘

**Files:**
- Create: `docs/stage0-demo.md`

- [ ] **Step 1: 全量回归（模拟 CI）**

```bash
cd /c/github/dataagent/services/query-gateway && source .venv/Scripts/activate
pytest -v
```

Expected: 所有测试通过（含 13+ 条恶意 SQL 用例）。

- [ ] **Step 2: 干净环境重建演练**

```bash
cd /c/github/dataagent/deploy
docker compose down -v
docker compose up -d --build
# 等待 60 秒后重做 Task 11 的三道验收题
```

Expected: 不借助任何手工修补，三道题全部通过。不通过则把缺失步骤补回本计划。

- [ ] **Step 3: 写 5 分钟演示脚本**

`docs/stage0-demo.md`：

```markdown
# 阶段 0 演示脚本（5 分钟）

1. （1 分钟）展示架构图（spec 第 2 节），强调：DB-GPT 零修改，所有能力在独立 MCP 服务
2. （1.5 分钟）现场问「10 月 22 日各渠道成交金额」，展开 Agent 的工具调用链：
   list_tables → get_table_meta → run_readonly_sql，并展示 executed_sql
3. （1 分钟）问「帮我删表」，展示结构化拒绝 + 审计日志里的 query_rejected
4. （1 分钟）展示 pytest 全绿与恶意 SQL 用例库；强调确定性安全不靠模型自觉
5. （0.5 分钟）讲阶段 1：指标语义服务、行列权限、评测集自动化；现场招募 2-3 位业务方提供问数原话
```

- [ ] **Step 4: 阶段复盘并合并分支**

在 `docs/stage0-acceptance.md` 的「已知问题」补全复盘结论，然后：

```bash
git add docs/stage0-demo.md docs/stage0-acceptance.md
git commit -m "docs(stage0): 演示脚本与复盘"
git checkout main
git merge --no-ff feat/stage0-skeleton -m "merge: 阶段 0 骨架验证完成"
```

- [ ] **Step 5: 阶段 0 出口标准对照（逐条勾选确认后才进入阶段 1 规划）**

- [ ] DB-GPT v0.8.2 容器运行，DeepSeek 接通，Web 可对话
- [ ] 三个 MCP 工具经网关工作，网关是唯一数据库出口
- [ ] 三道验收题结果正确（500/100、3 笔、表清单）
- [ ] 破坏性 SQL 100% 被 parse 阶段拒绝，恶意用例库全绿
- [ ] 无限制查询注入 LIMIT 201 哨兵、返回最多 200 行且超量时 truncated=true，审计 JSONL 完整
- [ ] 50 个真实问数原话已启动收集（至少到位 20 条）
- [ ] 干净环境 `down -v` 重建可复现
```
