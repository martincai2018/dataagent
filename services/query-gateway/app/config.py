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
