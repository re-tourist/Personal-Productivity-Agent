"""R1 compatibility facade. Migrate internal callers in R2; retain public startup aliases."""
from productivity_agent.infrastructure.persistence.thread_ownership import ThreadOwnership
from productivity_agent.infrastructure.security.accounts import (
    LEGACY_OWNER,
    Accounts,
    Identity,
)
from productivity_agent.interfaces.http.dependencies import (
    authorize_thread,
    claim_thread,
    identity_for,
    thread_key,
)
from productivity_agent.interfaces.http.middleware import (
    install_identity,
)

__all__ = ['LEGACY_OWNER', 'Accounts', 'Identity', 'ThreadOwnership', 'authorize_thread', 'claim_thread', 'identity_for', 'install_identity', 'thread_key']
