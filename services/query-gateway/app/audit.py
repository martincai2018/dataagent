import json
import time
from pathlib import Path


def append_audit(path: str, record: dict) -> None:
    """向 JSONL 审计文件追加一条记录，自动补 ts（调用方无法伪造/覆盖时间戳）。只追加。"""
    log_path = Path(path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {**record, "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")
