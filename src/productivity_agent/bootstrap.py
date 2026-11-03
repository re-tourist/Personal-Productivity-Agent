"""Composition root for the two local, single-worker applications.

Business SQLite, identity ownership, and LangGraph checkpoints remain separate.
No HTTP route or request object is required to construct or bind resources.
"""
import os
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

from productivity_agent.infrastructure.persistence.thread_ownership import ThreadOwnership
from productivity_agent.infrastructure.security.accounts import Accounts


def configured_accounts():
    return Accounts(os.getenv("PPA_AUTH_CONFIG"))


def assistant_lifespan(
    *, approval_graph=None, calendar_graph=None, store=None, live_agent=None,
    intent_graph=None, api_token=None, command_factory=None, session_extractor=None,
    session_backend=None,
):
    @asynccontextmanager
    async def lifespan(app):
        from productivity_agent.infrastructure.observability.operation_trace import (
            configure_logging,
        )
        configure_logging()
        try:
            from dotenv import load_dotenv
            load_dotenv(override=False)
        except ImportError:
            pass  # The installed project declares python-dotenv as a dependency.
        app.state.api_token = (
            os.getenv("PPA_API_TOKEN", "") if api_token is None else api_token
        )
        app.state.accounts = configured_accounts()
        app.state.thread_locks = {}
        app.state.live_agent = live_agent
        app.state.intent_graph = intent_graph
        app.state.command_factory = command_factory
        app.state.assistant_graph = None
        app.state.assistant_mode = "unavailable"
        if approval_graph is not None:
            app.state.approval_graph = approval_graph
            app.state.calendar_graph = calendar_graph
            app.state.store = store
            yield
            return

        # Defer these imports: unit tests of the transport layer don't need LangGraph.
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        from productivity_agent.domain.agent_intent import AgentIntent
        from productivity_agent.infrastructure.models.offline_intent import OfflineIntentExtractor
        from productivity_agent.infrastructure.persistence.task_store import SQLiteTaskStore
        from productivity_agent.tools.productivity import MockProductivityBackend
        from productivity_agent.workflows.approval_session import build_approval_graph
        from productivity_agent.workflows.assistant import build_assistant_graph
        from productivity_agent.workflows.calendar import build_graph

        data_dir = Path(os.getenv("PPA_DATA_DIR", ".ppa-data"))
        data_dir.mkdir(parents=True, exist_ok=True)
        app.state.thread_ownership = ThreadOwnership(data_dir / "access.sqlite")
        task_store = SQLiteTaskStore(data_dir / "tasks.sqlite")
        if os.getenv("PPA_TASK_SERVICE_URL"):
            from productivity_agent.infrastructure.integrations.http_task_store import HTTPTaskStore
            task_store = HTTPTaskStore(os.environ["PPA_TASK_SERVICE_URL"])
        async with AsyncSqliteSaver.from_conn_string(
            str(data_dir / "m6-checkpoints.sqlite")
        ) as saver:
            app.state.approval_graph = build_approval_graph(task_store, saver)
            app.state.calendar_graph = build_graph()
            app.state.store = task_store
            extractor = session_extractor or OfflineIntentExtractor()
            app.state.assistant_mode = (
                getattr(session_extractor, "mode", "scripted") if session_extractor else "offline_rules"
            )
            if os.getenv("PPA_ENABLE_LIVE_QWEN", "0") == "1":
                from productivity_agent.domain.intent import ScheduleIntent
                from productivity_agent.infrastructure.models.qwen import build_qwen_model
                from productivity_agent.infrastructure.observability.qwen_meter import QwenMeter
                from productivity_agent.tools.productivity import MockProductivityBackend
                from productivity_agent.workflows.natural_language import (
                    build_natural_language_graph,
                )
                from productivity_agent.workflows.tool_agent import build_tool_agent

                model = build_qwen_model()
                app.state.live_agent = build_tool_agent(
                    model, MockProductivityBackend(),
                    allow_mock_writes=False, max_model_calls=4,
                )
                app.state.intent_graph = build_natural_language_graph(
                    model.with_structured_output(ScheduleIntent, method="function_calling")
                )
                if session_extractor is None:
                    extractor = QwenMeter(model).structured(AgentIntent)
                    app.state.assistant_mode = "qwen"
            if session_backend is None:
                from productivity_agent.demo_data import make_tomorrow_conflict_case
                sample = make_tomorrow_conflict_case()
                backend = MockProductivityBackend(events=[{
                    "title": "模拟已有组会", **sample["busy_slots"][0],
                }])
            else:
                backend = session_backend
            app.state.saver = saver
            app.state.session_extractor = extractor
            app.state.session_backend = backend
            app.state.assistant_graph = build_assistant_graph(extractor, task_store, saver, backend)
            yield

    return lifespan


def business_store(store=None):
    from productivity_agent.infrastructure.observability.operation_trace import configure_logging
    from productivity_agent.infrastructure.persistence.task_store import SQLiteTaskStore

    configure_logging()
    return store or SQLiteTaskStore(Path(os.getenv("PPA_DATA_DIR", ".ppa-data")) / "tasks.sqlite")


def bind_user_resources(state, owner_id, bearer):
    """Build per-request graphs/store; never put a user's credentials on shared state."""
    from productivity_agent.workflows.approval_session import build_approval_graph
    from productivity_agent.workflows.assistant import build_assistant_graph

    store = state.store.for_owner(owner_id, bearer)
    return SimpleNamespace(
        store=store,
        assistant_graph=build_assistant_graph(state.session_extractor, store, state.saver, state.session_backend),
        approval_graph=build_approval_graph(store, state.saver),
    )
