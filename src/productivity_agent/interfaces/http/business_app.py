"""Independent local business HTTP app; loopback only, not a production API."""
from fastapi import FastAPI, Request

from productivity_agent.application.use_cases import tasks as task_reads
from productivity_agent.application.use_cases.task_creation import create_task_once
from productivity_agent.bootstrap import business_store
from productivity_agent.interfaces.http.dependencies import identity_for
from productivity_agent.interfaces.http.errors import install_business_errors, require_approval, run
from productivity_agent.interfaces.http.middleware import install_business_trace, install_identity
from productivity_agent.interfaces.http.schemas import ChangeRequest, CreateRequest


def create_task_service(store=None):
    store = business_store(store)
    app = FastAPI(title="PPA local test business service")
    install_identity(app, business=True)
    install_business_trace(app)
    install_business_errors(app)

    def owned(request):
        return store.for_owner(identity_for(request).owner_id)

    @app.get("/health")
    def health():
        return {"status": "ok", "local_test_service": True}

    @app.get("/tasks")
    def listing(request: Request, limit: int = 100):
        return {"items": run(task_reads.list_tasks, owned(request), limit=limit)}

    @app.get("/identity")
    def identity(request: Request):
        return {"owner_id": identity_for(request).owner_id, "auth_enabled": app.state.accounts.enabled}

    @app.get("/tasks/{task_id}")
    def get(task_id: str, request: Request):
        return run(task_reads.get_task, owned(request), task_id)

    @app.get("/operations/{operation_id}")
    def operation(operation_id: str, request: Request):
        return {"operation": task_reads.get_operation(owned(request), operation_id)}

    @app.post("/tasks")
    def create(body: CreateRequest, request: Request):
        require_approval(body)
        return run(create_task_once, owned(request), body.operation_id, body.title, body.due_at.isoformat())

    @app.patch("/tasks/{task_id}")
    def change(task_id: str, body: ChangeRequest, request: Request):
        require_approval(body)
        return run(owned(request).change_task, body.operation_id, task_id, body.expected_version,
                   body.action, title=body.title,
                   due_at=body.due_at.isoformat() if body.due_at else None)

    return app
