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
