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
