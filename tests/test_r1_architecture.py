"""R1 boundaries and request bindings; existing business/HTTP suites remain the acceptance tests."""
import ast
import hashlib
import importlib
import json
from pathlib import Path

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from productivity_agent.infrastructure.security.identity import Identity
from productivity_agent.interfaces.http.assistant_app import create_app
from productivity_agent.interfaces.http.dependencies import resources_for

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
