"""M2 live intent demo via low-cost Qwen (consumes model tokens)."""

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from productivity_agent.demo_data import make_tomorrow_conflict_case
from productivity_agent.domain.intent import ScheduleIntent
from productivity_agent.providers.qwen import build_qwen_model
from productivity_agent.workflows.natural_language import build_natural_language_graph


def main():
    load_dotenv()
    model = build_qwen_model()
    # Function-calling mode for broad compatibility with OpenAI-compatible services.
    extractor = model.with_structured_output(ScheduleIntent, method="function_calling")
    graph = build_natural_language_graph(extractor)
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    result = graph.invoke({
        "user_text": "明天下午三点安排一小时组会，有冲突就推荐其他时间",
        "reference_now": now.isoformat(),
        "busy_slots": make_tomorrow_conflict_case(now)["busy_slots"],
    })
    print(json.dumps(result["result"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
