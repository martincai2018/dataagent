class GatewayError(Exception):
    """网关内部结构化错误，序列化为 Agent 可用于自纠的 JSON。"""

    def __init__(self, stage: str, reason: str, suggestion: str):
        self.stage = stage
        self.reason = reason
        self.suggestion = suggestion
        super().__init__(reason)

    def to_dict(self) -> dict:
        return {
            "ok": False,
            "stage": self.stage,
            "reason": self.reason,
            "suggestion": self.suggestion,
        }
