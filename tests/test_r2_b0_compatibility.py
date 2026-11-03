"""B0 gate reused by every future slice: no candidate-generated old fixtures."""
import ast
import json
from pathlib import Path

from scripts.verify_r2_baseline import verify

REPO = Path(__file__).resolve().parents[1]


def test_fixed_baseline_producer_candidate_consumer_and_restart(tmp_path):
    report = verify(tmp_path)
    target = REPO / "reports/r2-b0/pytest-compatibility.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    assert report["contracts_exact"]
    assert len(report["matrix"]) == 5
    assert report["live_model_calls"] == 0


def test_domain_compatibility_exceptions_cannot_expand():
    """D1 permits exactly these legacy locations, never another Domain facade."""
    allowed = {"state.py", "intent.py", "agent_intent.py"}
    domain = REPO / "src/productivity_agent/domain"
    for path in domain.glob("*.py"):
        imports = []
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
        forbidden = [module for module in imports if module.startswith((
            "productivity_agent.application", "productivity_agent.workflows", "productivity_agent.tools",
            "productivity_agent.infrastructure", "productivity_agent.interfaces", "fastapi", "langgraph"))]
        assert not forbidden or (path.name in allowed and all(
            module.startswith("productivity_agent.application") for module in forbidden)), (path, forbidden)
