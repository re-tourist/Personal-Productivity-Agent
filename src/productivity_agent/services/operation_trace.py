"""Small context propagated through graph nodes into synchronous HTTP calls."""
import json
import logging
from contextvars import ContextVar

trace_context = ContextVar("ppa_trace", default=None)


def traced_node(fn):
    def run(state):
        context = {k: state.get(k) for k in ("request_id", "thread_id", "operation_id")}
        context["action"] = (state.get("intent") or {}).get("action")
        context["target_id"] = (state.get("target") or {}).get("id")
        token = trace_context.set(context)
        try:
            result = fn(state)
            logging.getLogger("ppa.agent").info(json.dumps({
                **context, "operation_id": result.get("operation_id", context["operation_id"]),
                "node": fn.__name__, "status": result.get("status"),
            }))
            return result
        finally:
            trace_context.reset(token)
    return run


def configure_logging():
    logger = logging.getLogger("ppa")
    logger.setLevel(logging.INFO)
    if not logging.getLogger().handlers and not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
