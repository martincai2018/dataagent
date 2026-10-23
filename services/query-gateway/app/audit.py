import json
import time
from pathlib import Path


def append_audit(path: str, record: dict) -> None:
    """向 JSONL 审计文件追加一条记录，自动补 ts。只追加，不修改历史。"""
    log_path = Path(path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **record}
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")
