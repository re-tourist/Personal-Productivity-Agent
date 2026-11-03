"""Low-cost Qwen client via Alibaba Cloud Model Studio's OpenAI-compatible API."""

import os

from langchain_openai import ChatOpenAI

DEFAULT_QWEN_MODEL = "qwen3.7-flash"
# Beijing legacy endpoint; the newer per-workspace endpoint is preferred.
# Set DASHSCOPE_BASE_URL explicitly for a different region/workspace.
DEFAULT_BEIJING_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


def build_qwen_model(*, http_client=None) -> ChatOpenAI:
    """Build a low-cost non-thinking model without exposing credentials."""
    key = os.getenv("DASHSCOPE_API_KEY", "").strip()
    if not key:
        raise RuntimeError("请在环境变量 DASHSCOPE_API_KEY 中配置百炼 API Key。")

    return ChatOpenAI(
        model=os.getenv("PPA_MODEL", DEFAULT_QWEN_MODEL),
        api_key=key,
        base_url=os.getenv("DASHSCOPE_BASE_URL", DEFAULT_BEIJING_BASE_URL),
        temperature=0,
        max_tokens=600,
        timeout=25,
        max_retries=0,  # Keep live API retries explicit and observable (M4).
        extra_body={"enable_thinking": False},
        use_responses_api=False,
        http_client=http_client,
    )
