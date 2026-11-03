"""R1 identity import compatibility; new callers use accounts or thread_ownership directly."""
from productivity_agent.infrastructure.persistence.thread_ownership import ThreadOwnership
from productivity_agent.infrastructure.security.accounts import LEGACY_OWNER, Accounts, Identity

__all__ = ["LEGACY_OWNER", "Accounts", "Identity", "ThreadOwnership"]
