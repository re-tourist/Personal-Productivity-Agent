"""An *explicitly opt-in* one-turn paid smoke test for Qwen connectivity."""
import argparse
import os
from urllib.parse import urlsplit

from dotenv import load_dotenv


def main():
    parser = argparse.ArgumentParser(description="Optional Qwen API smoke test")
    parser.add_argument("--live", action="store_true", help="Actually call the paid API")
    args = parser.parse_args()
    load_dotenv()
    model = os.getenv("PPA_MODEL", "qwen3.7-flash")
    endpoint = os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    key_present = bool(os.getenv("DASHSCOPE_API_KEY", "").strip())
    host = urlsplit(endpoint).hostname or ""
    region = "Beijing" if host == "dashscope.aliyuncs.com" or host.endswith(".cn-beijing.maas.aliyuncs.com") else "other/custom"
    print(f"model_configured={bool(model)}; endpoint_region={region}; key_configured={key_present}")
    if not args.live:
        print("Dry run: ZERO API calls. Add --live explicitly to spend tokens.")
        return
    if not key_present:
        raise SystemExit("Set DASHSCOPE_API_KEY in .env before using --live")
    from productivity_agent.providers.qwen import build_qwen_model
    try:
        response = build_qwen_model().invoke("请只回复两个字：收到")
    except Exception:  # noqa: BLE001 -- do not leak SDK error messages or credentials.
        raise SystemExit("Qwen smoke failed; provider details hidden to protect credentials") from None
    print("Qwen response_received:", bool(response.content))
    print("For budgeted business validation, use validate_qwen_agent.py after separate authorization.")


if __name__ == "__main__":
    main()
