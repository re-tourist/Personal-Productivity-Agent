"""Compatible synchronous HTTP adapter; uncertain writes are reconciled, never retried here."""
import json
import logging
import time
import uuid

import httpx

from productivity_agent.services.operation_trace import trace_context
from productivity_agent.services.task_store import (
    AmbiguousCommitError,
    IdempotencyConflict,
    VersionConflict,
    request_fingerprint,
    validate_task_request,
)


class BusinessUnavailable(RuntimeError):
    """Remote outcome unknown; do not automatically resubmit."""


class HTTPTaskStore:
    def __init__(self, base_url, timeout=3.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _request(self, method, path, payload=None):
        started = time.monotonic()
        status = None
        error = None
        context = trace_context.get() or {}
        rid = context.get("request_id") or str(uuid.uuid4())
        try:
            with httpx.Client(timeout=self.timeout, trust_env=False) as client:
                response = client.request(method, self.base_url + path, json=payload,
                                          headers={"X-Request-ID": rid})
            status = response.status_code
            if status == 404:
                raise KeyError("task_not_found")
            if status == 409:
                raise VersionConflict("conflict_read_again")
            if status == 400 or status == 422:
                raise ValueError("invalid_business_request")
            if status >= 500:
                raise BusinessUnavailable("business_5xx_outcome_unknown")
            if not 200 <= status < 300:
                raise BusinessUnavailable("business_http_error")
            return response.json()
        except httpx.RequestError:
            error = "transport_unknown" if method != "GET" else "read_unavailable"
            if method != "GET":
                raise AmbiguousCommitError("http_write_outcome_unknown") from None
            raise BusinessUnavailable("business_read_unavailable") from None
        except Exception as exc:
            error = type(exc).__name__
            raise
        finally:
            logging.getLogger("ppa.http").info(json.dumps({**context, "request_id": rid, "operation_id": (payload or {}).get("operation_id") or context.get("operation_id"),
                "http_action": method, "http_status": status,
                "elapsed_ms": round((time.monotonic() - started) * 1000, 2), "error": error}))

    def list_tasks(self, *, limit=100):
        return self._request("GET", f"/tasks?limit={limit}")["items"]

    def get_task(self, task_id):
        return self._request("GET", f"/tasks/{task_id}")

    def get_operation(self, operation_id):
        return self._request("GET", f"/operations/{operation_id}")["operation"]

    def lookup(self, operation_id, title, due_at):
        _, title, due = validate_task_request(operation_id, title, due_at)
        op = self.get_operation(operation_id)
        if op is None:
            return None
        if op.get("request_hash") != request_fingerprint(title, due):
            raise IdempotencyConflict("operation_id reused")
        return self.get_task(op["task"]["id"])

    def create_task(self, operation_id, title, due_at, *, fault=None):
        try:
            return self._request("POST", "/tasks", {
                "operation_id": operation_id, "title": title, "due_at": due_at, "approved": True})
        except BusinessUnavailable:
            raise AmbiguousCommitError("http_write_outcome_unknown") from None

    def change_task(self, operation_id, task_id, expected_version, action, **patch):
        return self._request("PATCH", f"/tasks/{task_id}", dict(
            operation_id=operation_id, expected_version=expected_version,
            action=action, approved=True, **patch))
