import json
import threading

from app.gateway import Gateway


def _gateway(engine, tmp_path):
    return Gateway(engine, dialect="sqlite", audit_log=str(tmp_path / "audit.jsonl"), max_rows=200)


def _events(tmp_path):
    return [
        json.loads(line)
        for line in (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    ]


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
    assert result["truncated"] is False
    assert result["executed_sql"].upper().startswith("SELECT")

    events = _events(tmp_path)
    assert [e["event"] for e in events] == ["query_submit", "query_ok"]
    # 对抗式复审 I1：同一请求的事件靠 request_id 配对，且全部携带 user
    assert events[0]["user"] == events[1]["user"] == "tester"
    assert events[0]["request_id"] == events[1]["request_id"]
    assert len(events[0]["request_id"]) == 32
    # query_ok 载荷钉死，防止成功事件悄悄丢字段
    assert events[1]["rows"] == 2
    assert events[1]["truncated"] is False


def test_malicious_sql_returns_structured_error_not_raises(demo_engine, tmp_path):
    gw = _gateway(demo_engine, tmp_path)
    result = gw.run_readonly_sql("DROP TABLE dws_trade_order_di", user="tester")

    assert result["ok"] is False
    assert result["stage"] == "parse"
    assert "suggestion" in result
    events = _events(tmp_path)
    assert events[-1]["event"] == "query_rejected"
    # 拒绝事件必须能与提交事件配对归因
    assert events[-1]["request_id"] == events[0]["request_id"]
    assert events[-1]["user"] == "tester"


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

    # 钉死顺序：fail-closed 必须挡在校验之后、执行之前——run_query 一旦被调即测试失败
    def _must_not_execute(*args, **kwargs):
        raise AssertionError("审计不可用时不得执行查询")

    monkeypatch.setattr("app.gateway.run_query", _must_not_execute)

    gw = _gateway(demo_engine, tmp_path)

    result = gw.run_readonly_sql("SELECT 1", user="tester")
    assert result["ok"] is False
    assert result["stage"] == "audit"

    assert gw.list_tables()["stage"] == "audit"
    assert gw.get_table_meta("dws_trade_order_di")["stage"] == "audit"


def test_query_ok_audit_failure_withholds_rows(monkeypatch, demo_engine, tmp_path):
    # 对抗式复审 I3：提交审计成功、查询已执行，但成功审计失败——结果行必须扣下
    seen = []

    def _flaky(path, record):
        seen.append(record["event"])
        if record["event"] == "query_ok":
            raise OSError("disk full")

    monkeypatch.setattr("app.gateway.append_audit", _flaky)
    gw = _gateway(demo_engine, tmp_path)

    result = gw.run_readonly_sql("SELECT 1 AS x", user="tester")

    assert result["ok"] is False
    assert result["stage"] == "audit"
    assert "rows" not in result
    assert "columns" not in result
    assert seen == ["query_submit", "query_ok"]  # 查询确实执行了，但成功响应没放出去


def test_rejection_audit_failure_preserves_original_error(monkeypatch, demo_engine, tmp_path):
    # 对抗式复审 M1：拒绝事件本身审计失败时，原始 parse/execute 原因不能丢
    def _flaky(path, record):
        if record["event"] == "query_rejected":
            raise OSError("disk full")

    monkeypatch.setattr("app.gateway.append_audit", _flaky)

    def _must_not_execute(*args, **kwargs):
        raise AssertionError("parse 已拒绝，不得执行")

    monkeypatch.setattr("app.gateway.run_query", _must_not_execute)

    gw = _gateway(demo_engine, tmp_path)
    result = gw.run_readonly_sql("DROP TABLE dws_trade_order_di", user="tester")

    assert result["stage"] == "audit"
    assert result["original_stage"] == "parse"
    assert result["original_reason"]


def test_lone_surrogate_sql_never_raises(demo_engine, tmp_path):
    # 对抗式复审 I2：JSON-RPC 可送达孤立代理项；门面契约是绝不裸抛、审计文件不损坏。
    # sqlite 下该语句可正常执行（ok=True），成功与否不是本断言重点——任何结果都只能是 dict，
    # 且审计 JSONL 每一行都必须仍能被 json.loads 解析（写入侧 errors="backslashreplace" 兜底）。
    gw = _gateway(demo_engine, tmp_path)
    result = gw.run_readonly_sql("SELECT 'a\ud800b' AS x", user="tester")

    assert isinstance(result, dict)
    for line in (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines():
        json.loads(line)


def test_concurrent_requests_audit_events_are_attributable(demo_engine, tmp_path):
    # 对抗式复审 I1：并发交错时，靠 request_id+user 必须能把每条事件归到唯一请求
    gw = _gateway(demo_engine, tmp_path)
    outcomes = {}

    def worker(user):
        outcomes[user] = gw.run_readonly_sql(
            "SELECT COUNT(*) AS n FROM dws_trade_order_di", user=user
        )

    threads = [threading.Thread(target=worker, args=(u,)) for u in ("alice", "bob")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert {outcomes["alice"]["ok"], outcomes["bob"]["ok"]} == {True}

    groups = {}
    for event in _events(tmp_path):
        groups.setdefault(event["request_id"], []).append(event)

    assert len(groups) == 2  # 两个 request_id 不串号
    paired_users = set()
    for events in groups.values():
        assert {e["event"] for e in events} == {"query_submit", "query_ok"}
        users = {e["user"] for e in events}
        assert len(users) == 1  # 同一 request_id 下用户一致
        paired_users.add(next(iter(users)))
    assert paired_users == {"alice", "bob"}
