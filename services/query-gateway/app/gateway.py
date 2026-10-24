import uuid

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
        request_id = uuid.uuid4().hex
        try:
            self._audit({"event": "metadata_list_tables", "request_id": request_id, "user": user})
        except GatewayError as audit_error:
            return audit_error.to_dict()
        try:
            return {"ok": True, "tables": metadata.list_tables(self.engine)}
        except GatewayError as error:
            return error.to_dict()

    def get_table_meta(self, table_name: str, user: str = "anonymous") -> dict:
        request_id = uuid.uuid4().hex
        try:
            self._audit({
                "event": "metadata_get_table",
                "request_id": request_id,
                "user": user,
                "table": table_name,
            })
        except GatewayError as audit_error:
            return audit_error.to_dict()
        try:
            return {**metadata.get_table_meta(self.engine, table_name), "ok": True}
        except GatewayError as error:
            return error.to_dict()

    def run_readonly_sql(self, sql: str, user: str = "anonymous") -> dict:
        # 每次请求一个 request_id，同一次调用的 submit/ok/rejected 全事件携带它与 user
        # （对抗式复审 I1：并发 SSE 下交错的 JSONL 行必须能配对归因）
        request_id = uuid.uuid4().hex
        # fail-closed：提交审计写不进去就不校验、不执行（企业审计原则：不能审计就不碰数）
        try:
            self._audit({
                "event": "query_submit",
                "request_id": request_id,
                "user": user,
                "sql": sql,
            })
        except GatewayError as audit_error:
            return audit_error.to_dict()

        try:
            safe_sql = validate_and_rewrite(sql, self.dialect, self.max_rows)
        except GatewayError as parse_error:
            return self._reject(parse_error, "parse", sql, request_id, user)

        try:
            result = run_query(self.engine, safe_sql, self.max_rows)
        except GatewayError as exec_error:
            return self._reject(exec_error, "execute", safe_sql, request_id, user)

        # 查询已执行；成功审计若写不进去，宁可返回 audit 错误也不假装成功（行不返回）
        try:
            self._audit({
                "event": "query_ok",
                "request_id": request_id,
                "user": user,
                "sql": safe_sql,
                "rows": len(result["rows"]),
                "truncated": result["truncated"],
            })
        except GatewayError as audit_error:
            return audit_error.to_dict()
        return {**result, "executed_sql": safe_sql}

    def _reject(
        self,
        error: GatewayError,
        stage: str,
        audited_sql: str,
        request_id: str,
        user: str,
    ) -> dict:
        try:
            self._audit({
                "event": "query_rejected",
                "request_id": request_id,
                "user": user,
                "stage": stage,
                "sql": audited_sql,
            })
        except GatewayError as audit_error:
            # 拒绝事件本身也落不了盘：返回 audit 错误，但保留原始 parse/execute 原因（M1）
            return {
                **audit_error.to_dict(),
                "original_stage": stage,
                "original_reason": error.reason,
            }
        return error.to_dict()

    def _audit(self, record: dict) -> None:
        try:
            append_audit(self.audit_log, record)
        except Exception as exc:  # noqa: BLE001
            # 审计边界必须永不裸逃：OSError 之外 UnicodeEncodeError（ValueError）等实证可达，
            # 只回显异常类名，不回显内部路径等细节（对抗式复审 I2 + M6）
            raise GatewayError(
                "audit",
                f"审计日志写入失败：{type(exc).__name__}",
                "审计不可用时查询已被拦截，请联系管理员检查审计存储",
            )
