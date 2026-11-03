"""SSE wire encoders. Preserve each endpoint family's serialization behavior."""
import json
from typing import Any


def _encode_sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def encode_assistant_sse(event, data, *, ensure_ascii=False):
    # Assistant payloads remain strict JSON (no default=str coercion).
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=ensure_ascii)}\n\n"


ASSISTANT_INTERRUPTED_EVENT = (
    'event: error\ndata: {"message":"执行中断，请查询会话状态后恢复。"}\n\n'
)
