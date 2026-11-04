"""M2: Add natural-language intent parsing in front of the existing M1 graph.

Provide an object exposing .invoke(messages) and returning ScheduleIntent.
This allows offline tests with a fake extractor and runtime use with an LLM.
"""

from typing import Literal, NotRequired, TypedDict

from langgraph.graph import END, START, StateGraph

from productivity_agent.application.agent.llm.contracts import ScheduleIntent
from productivity_agent.application.agent.llm.normalization import normalize_schedule_intent
from productivity_agent.application.agent.llm.prompts import natural_language_system_prompt
from productivity_agent.application.agent.workflows.calendar import (
    build_graph as build_calendar_graph,
)
from productivity_agent.application.ports.llm import StructuredExtractor
from productivity_agent.domain.contracts import CalendarRequest, TimeSlot


class NaturalLanguageState(TypedDict):
    user_text: str
    reference_now: str  # Offset-aware ISO 8601 time, supplied by the application
    busy_slots: list[TimeSlot]
    parsed_intent: NotRequired[dict]
    request: NotRequired[CalendarRequest]
    parse_error: NotRequired[str]
    clarification: NotRequired[str]
    decision: NotRequired[Literal["calendar", "clarify", "unsupported"]]
    result: NotRequired[dict]


def build_natural_language_graph(extractor: StructuredExtractor[ScheduleIntent]):
    """Compose new intent graph with the unchanged M1 calendar workflow."""
    calendar_graph = build_calendar_graph()

    def parse_intent(state: NaturalLanguageState) -> dict:
        system = natural_language_system_prompt(state["reference_now"])
        try:
            parsed = extractor.invoke([
                ("system", system),
                ("human", state["user_text"]),
            ])
            # Schema validation at the data boundary; a fake may return a dict.
            validated = ScheduleIntent.model_validate(parsed)
            return {"parsed_intent": validated.model_dump(mode="json")}
        except Exception as exc:  # noqa: BLE001 -- preserve the existing model/schema failure boundary.
            # M2 MVP: graceful failure; production should log a traceback and
            # classify timeouts/rate-limits separately in M4.
            return {"parse_error": type(exc).__name__}

    def route_after_parse(state: NaturalLanguageState) -> Literal["parse_failed", "normalize"]:
        return "parse_failed" if state.get("parse_error") else "normalize"

    def normalize(state: NaturalLanguageState) -> dict:
        parsed = ScheduleIntent.model_validate(state["parsed_intent"])
        if parsed.action == "unsupported":
            return {"decision": "unsupported"}
        request, question = normalize_schedule_intent(parsed, state["reference_now"])
        if question:
            return {"decision": "clarify", "clarification": question}
        return {"decision": "calendar", "request": request}

    def route_after_normalize(
        state: NaturalLanguageState,
    ) -> Literal["calendar", "clarify", "unsupported"]:
        return state["decision"]

    def calendar(state: NaturalLanguageState) -> dict:
        final = calendar_graph.invoke({
            "request": state["request"],
            "busy_slots": state["busy_slots"],
        })
        return {"result": final["result"]}

    def clarify(state: NaturalLanguageState) -> dict:
        return {"result": {
            "status": "clarification_required",
            "message": state["clarification"],
        }}

    def unsupported(_state: NaturalLanguageState) -> dict:
        return {"result": {
            "status": "unsupported",
            "message": "目前仅支持创建日程前的冲突检测及时间推荐。",
        }}

    def parse_failed(_state: NaturalLanguageState) -> dict:
        return {"result": {
            "status": "parse_failed",
            "message": "暂时无法理解这条指令，请稍后重试。",
        }}

    builder = StateGraph(NaturalLanguageState)
    builder.add_node("parse_intent", parse_intent)
    builder.add_node("normalize", normalize)
    builder.add_node("calendar", calendar)
    builder.add_node("clarify", clarify)
    builder.add_node("unsupported", unsupported)
    builder.add_node("parse_failed", parse_failed)

    builder.add_edge(START, "parse_intent")
    builder.add_conditional_edges("parse_intent", route_after_parse)
    builder.add_conditional_edges("normalize", route_after_normalize)
    for node_name in ("calendar", "clarify", "unsupported", "parse_failed"):
        builder.add_edge(node_name, END)
    return builder.compile()
