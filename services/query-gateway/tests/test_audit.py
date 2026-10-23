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
