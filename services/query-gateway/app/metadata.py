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
