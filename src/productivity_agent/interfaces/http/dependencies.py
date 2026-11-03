"""HTTP identity, authorization, and request-local resource binding."""
import secrets

from fastapi import HTTPException, Request

from productivity_agent.bootstrap import bind_user_resources


def identity_for(request):
    return request.state.identity


def claim_thread(request, kind, tid):
    if request.app.state.accounts.enabled:
        request.app.state.thread_ownership.claim(kind, tid, identity_for(request).owner_id)


def authorize_thread(request, kind, tid):
    if (request.app.state.accounts.enabled and not request.app.state.thread_ownership.owns(
            kind, tid, identity_for(request).owner_id)):
        raise HTTPException(404, "resource_not_found")


def thread_key(request, kind, tid):
    if request.app.state.accounts.enabled:
        return f"{kind}:{identity_for(request).owner_id}:{tid}"
    return f"assistant:{tid}" if kind == "assistant" else str(tid)


def _check_token(request: Request) -> None:
    """Optional demo token. Authentication and ownership require a real provider in prod."""
    if request.app.state.accounts.enabled:
        identity_for(request)  # Middleware already verified the credential.
        return
    expected = getattr(request.app.state, "api_token", "")
    if expected and not secrets.compare_digest(
        request.headers.get("X-PPA-Token", ""), expected
    ):
        raise HTTPException(status_code=401, detail="invalid or missing X-PPA-Token")


def resources_for(request):
    state = request.app.state
    if not state.accounts.enabled:
        return state
    if not hasattr(request.state, "resources"):
        identity = identity_for(request)
        request.state.resources = bind_user_resources(state, identity.owner_id, identity.bearer)
    return request.state.resources
