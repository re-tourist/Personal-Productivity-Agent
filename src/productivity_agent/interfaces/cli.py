"""Simple command-line entry point; no real API or database calls in M0/M1."""

import argparse
import json

from productivity_agent.demo_data import make_tomorrow_conflict_case


def main() -> int:
    parser = argparse.ArgumentParser(description="Personal Productivity Agent")
    parser.add_argument("--demo", action="store_true", help="Execute the M1 LangGraph workflow")
    args = parser.parse_args()

    if not args.demo:
        print("PPA v1.0 ready. Use ppa --demo or start the API with uvicorn (see README).")
        return 0

    from productivity_agent.workflows.calendar import build_graph

    graph = build_graph()
    final = graph.invoke(make_tomorrow_conflict_case())

    print(json.dumps(final["result"], ensure_ascii=False, indent=2))
    return 0
