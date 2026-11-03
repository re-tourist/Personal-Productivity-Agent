"""R1 boundaries and request bindings; existing business/HTTP suites remain the acceptance tests."""
import ast
import hashlib
import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from productivity_agent.infrastructure.security.accounts import Identity
from productivity_agent.interfaces.http.assistant_app import create_app
from productivity_agent.interfaces.http.dependencies import resources_for
from scripts.verify_r1_compatibility import route_manifest

PACKAGE = Path(__file__).resolve().parents[1] / "src/productivity_agent"
OLD_PREFIXES = tuple("productivity_agent." + p for p in ("api", "services", "providers", "cli"))


def imported_modules(path):
    # ast.walk includes function-local/deferred imports, not just the module header.
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert node.level == 0, f"Resolve relative imports in boundary checker: {path}"
            yield node.module
        elif isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)


def test_layer_import_boundaries_include_deferred_imports():
    forbidden_domain = (
        "fastapi", "langgraph", "langchain", "sqlite3", "productivity_agent.interfaces",
        "productivity_agent.infrastructure", "productivity_agent.workflows", "productivity_agent.tools",
        "productivity_agent.bootstrap", *OLD_PREFIXES,
    )
    for path in PACKAGE.rglob("*.py"):
        relative = path.relative_to(PACKAGE)
        modules = tuple(imported_modules(path))
        if relative.parts[0] == "domain":
            assert not any(m.startswith(forbidden_domain) for m in modules), relative
        if relative.parts[0] == "infrastructure":
            assert not any(m.startswith(("fastapi", "productivity_agent.interfaces", *OLD_PREFIXES))
                           for m in modules), relative
        if relative.parts[0] == "interfaces":
            assert "sqlite3" not in modules, relative
        if relative.parts[0] in {"interfaces", "infrastructure"} or relative.name == "bootstrap.py":
            assert not any(m.startswith(OLD_PREFIXES) for m in modules), relative
            assert "productivity_agent.infrastructure.security.identity" not in modules, relative


def test_accounts_and_ownership_have_separate_technology_dependencies():
    accounts = tuple(imported_modules(PACKAGE / "infrastructure/security/accounts.py"))
    assert not any(m.startswith(("sqlite3", "productivity_agent.infrastructure.persistence")) for m in accounts)
    ownership = tuple(imported_modules(PACKAGE / "infrastructure/persistence/thread_ownership.py"))
    assert not any(m.startswith(("fastapi", "starlette", "productivity_agent.interfaces",
                                 "productivity_agent.infrastructure.security")) for m in ownership)


def test_route_aggregator_only_composes_routers_and_reexports_draft_helpers():
    path = PACKAGE / "interfaces/http/routes/api.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    functions = [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    assert len(functions) == 1 and functions[0].name == "api_router"
    assert functions[0].decorator_list == []
    assert not any(isinstance(node, ast.ClassDef) for node in ast.walk(tree))
    assert set(imported_modules(path)) <= {"fastapi", *(
        "productivity_agent.interfaces.http.routes." + name
        for name in ("system", "tasks", "calendar", "drafts", "agent")
    )}


def test_route_order_and_endpoint_names_match_r1_contract():
    from productivity_agent.interfaces.http.routes.api import api_router

    expected = [
        ("/", "GET", "home"), ("/health", "GET", "health"), ("/app", "GET", "dashboard"),
        ("/v1/system", "GET", "system"), ("/v1/me", "GET", "me"),
        ("/v1/tasks", "GET", "list_tasks"), ("/v1/tasks/{task_id}", "GET", "task_detail"),
        ("/v1/operations/{operation_id}", "GET", "operation_detail"),
        ("/v1/calendar/natural-language", "POST", "calendar_natural_language"),
        ("/v1/calendar/check", "POST", "calendar_check"),
        ("/v1/calendar/check/stream", "POST", "calendar_check_stream"),
        ("/v1/tasks/drafts", "POST", "create_task_draft"),
        ("/v1/tasks/drafts/{thread_id}", "GET", "get_task_draft"),
        ("/v1/tasks/drafts/{thread_id}/decision", "POST", "decide_task_draft"),
        ("/v1/agent/ask", "POST", "ask_agent"), ("/v1/agent/stream", "POST", "stream_agent"),
    ]
    actual = route_manifest(api_router())
    assert [(r["path"], r["methods"][0], r["name"]) for r in actual] == expected


@pytest.mark.parametrize("module", [
    "interfaces.http.routes." + name for name in ("api", "system", "tasks", "calendar", "drafts", "agent")
] + ["infrastructure.security.accounts", "infrastructure.security.identity",
     "infrastructure.persistence.thread_ownership"])
def test_new_modules_import_in_fresh_processes(module):
    # A fresh interpreter prevents prior import order from hiding a cycle or a missing symbol.
    result = subprocess.run([sys.executable, "-c", "import importlib,sys; importlib.import_module(sys.argv[1])",
                             "productivity_agent." + module], check=False, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_identity_and_draft_compatibility_imports_are_exact_aliases():
    from productivity_agent.api import app as old_app
    from productivity_agent.infrastructure.persistence.thread_ownership import ThreadOwnership
    from productivity_agent.infrastructure.security import accounts, identity
    from productivity_agent.interfaces.http.routes import api, drafts
    from productivity_agent.services import identity as old_identity

    for legacy in (identity, old_identity):
        assert legacy.Identity is accounts.Identity
        assert legacy.Accounts is accounts.Accounts
        assert legacy.LEGACY_OWNER == accounts.LEGACY_OWNER
        assert legacy.ThreadOwnership is ThreadOwnership
    for legacy in (api, old_app):
        assert legacy._snapshot_response is drafts._snapshot_response
        assert legacy._thread_config is drafts._thread_config


def test_package_import_graph_has_no_cycles():
    graph = {}
    for path in PACKAGE.rglob("*.py"):
        parts = path.relative_to(PACKAGE).with_suffix("").parts
        name = ".".join(("productivity_agent", *parts))
        if name.endswith(".__init__"):
            name = name.removesuffix(".__init__")
        graph[name] = set(imported_modules(path))
    visited, active = set(), set()

    def visit(name):
        assert name not in active, f"Import cycle through {name}"
        if name in visited or name not in graph:
            return
        active.add(name)
        for target in graph[name]:
            visit(target)
        active.remove(name)
        visited.add(name)

    for name in graph:
        visit(name)


def test_every_internal_import_resolves_including_optional_startup_branches():
    for path in PACKAGE.rglob("*.py"):
        for module in imported_modules(path):
            if module.startswith("productivity_agent."):
                assert (PACKAGE / (module.removeprefix("productivity_agent.").replace(".", "/") + ".py")).exists() or (
                    PACKAGE / module.removeprefix("productivity_agent.").replace(".", "/") / "__init__.py"
                ).exists(), (path.relative_to(PACKAGE), module)


def test_optional_model_startup_assembles_without_invoking_a_model(tmp_path, monkeypatch):
    class AssemblyOnlyModel:
        def bind_tools(self, tools, **kwargs):
            return self

        def with_structured_output(self, schema, **kwargs):
            return self

        def invoke(self, *args, **kwargs):
            pytest.fail("Startup must not invoke a model")

    monkeypatch.setenv("PPA_AUTH_CONFIG", "")
    monkeypatch.setenv("PPA_TASK_SERVICE_URL", "")
    monkeypatch.setenv("PPA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PPA_ENABLE_LIVE_QWEN", "1")
    monkeypatch.setattr("productivity_agent.infrastructure.models.qwen.build_qwen_model", AssemblyOnlyModel)
    with TestClient(create_app(api_token="")) as api:
        system = api.get("/v1/system").json()
        assert system["assistant_mode"] == "qwen"
        assert system["live_qwen_enabled"] is True
        assert system["intent_parser_enabled"] is True


@pytest.mark.parametrize("old,new", [
    ("api.app", "interfaces.http.assistant_app"),
    ("api.task_service", "interfaces.http.business_app"),
    ("cli", "interfaces.cli"),
    ("services.task_store", "infrastructure.persistence.task_store"),
    ("services.http_task_store", "infrastructure.integrations.http_task_store"),
    ("services.operation_trace", "infrastructure.observability.operation_trace"),
    ("providers.qwen", "infrastructure.models.qwen"),
    ("providers.offline_intent", "infrastructure.models.offline_intent"),
    ("providers.qwen_meter", "infrastructure.observability.qwen_meter"),
])
def test_compatibility_facades_share_implementations(old, new):
    legacy = importlib.import_module("productivity_agent." + old)
    implementation = importlib.import_module("productivity_agent." + new)
    for name in legacy.__all__:
        if hasattr(implementation, name):
            assert getattr(legacy, name) is getattr(implementation, name)


@pytest.mark.parametrize("remote", [False, True])
def test_request_resources_cache_per_request_without_mutating_shared_store(tmp_path, monkeypatch, remote):
    auth = tmp_path / "accounts.auth.json"
    auth.write_text(json.dumps({"users": {owner: {"token_sha256": hashlib.sha256(owner.encode()).hexdigest()}
                                          for owner in ("alice", "bob")}}), encoding="utf-8")
    monkeypatch.setenv("PPA_AUTH_CONFIG", str(auth))
    monkeypatch.setenv("PPA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PPA_ENABLE_LIVE_QWEN", "0")
    # No HTTP calls here: test the real resource construction before graph execution.
    monkeypatch.setenv("PPA_TASK_SERVICE_URL", "http://127.0.0.1:1" if remote else "")
    with TestClient(create_app(api_token="")) as api:
        shared = api.app.state.store
        original = vars(shared).copy()
        bindings = []
        for owner in ("alice", "bob"):
            request = Request({"type": "http", "app": api.app,
                               "state": {"identity": Identity(owner, owner + "-synthetic-bearer")}})
            binding = resources_for(request)
            assert resources_for(request) is binding
            assert binding.store is not shared
            if remote:
                assert binding.store.expected_owner == owner
                assert binding.store.bearer == request.state.identity.bearer
            else:
                assert binding.store.owner_id == owner
                assert binding.store.store is shared
            bindings.append(binding)
        assert vars(shared) == original
        assert bindings[0].assistant_graph is not bindings[1].assistant_graph
        assert bindings[0].approval_graph is not bindings[1].approval_graph
