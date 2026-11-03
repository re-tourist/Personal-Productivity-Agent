"""Request-local resources: graph/store instances never carry another user's credential."""
from types import SimpleNamespace

from productivity_agent.services.identity import identity_for


def resources_for(request):
    app = request.app.state
    if not app.accounts.enabled:
        return app
    if hasattr(request.state, "resources"):
        return request.state.resources
    from productivity_agent.workflows.approval_session import build_approval_graph
    from productivity_agent.workflows.assistant import build_assistant_graph
    identity = identity_for(request)
    store = app.store.for_owner(identity.owner_id, identity.bearer)
    result = SimpleNamespace(
        store=store,
        assistant_graph=build_assistant_graph(app.session_extractor, store, app.saver, app.session_backend),
        approval_graph=build_approval_graph(store, app.saver),
    )
    request.state.resources = result
    return result
