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


def test_lone_surrogate_value_is_written_without_raising(tmp_path):
    # 对抗式复审 I2：孤立代理项经 JSON-RPC 可达；审计写入必须不抛异常且文件仍可解码
    log_file = tmp_path / "audit.jsonl"
    append_audit(str(log_file), {"event": "query_submit", "sql": "SELECT 'a\ud800b'"})

    records = [json.loads(line) for line in log_file.read_text(encoding="utf-8").splitlines()]
    assert records[0]["event"] == "query_submit"
