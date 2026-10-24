import json
import threading
import time
from pathlib import Path

# MCP SSE 并发请求会同时追加同一审计文件：模块级锁保证一行一条完整 JSON
_WRITE_LOCK = threading.Lock()


def append_audit(path: str, record: dict) -> None:
    """向 JSONL 审计文件追加一条记录，自动补 ts（调用方无法伪造/覆盖时间戳）。只追加。

    防御性序列化（Task 6 对抗式复审 I2）：JSON-RPC 可送达孤立代理项（如 "SELECT '\\ud800'"，
    json.loads 接受合法 \\uD800 转义），json.dumps(ensure_ascii=False) 不报错但 UTF-8 文本
    写入会抛 UnicodeEncodeError——它是 ValueError 不是 OSError，会裸逃出审计边界。故：
    default=str 兜底不可序列化对象；文件流 errors="backslashreplace" 保证任何 str 都能落成
    可解码 ASCII（孤立代理项写成 \\ud800 字面量），单行始终是完整合法 JSON。
    """
    log_path = Path(path)
    payload = {**record, "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    line = json.dumps(payload, ensure_ascii=False, default=str) + "\n"
    with _WRITE_LOCK:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8", errors="backslashreplace") as f:
            f.write(line)
