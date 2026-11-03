"""Opt-in local test accounts and persistent thread ownership. No client-selected identity."""
import hashlib
import json
import os
import re
import secrets
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

LEGACY_OWNER = "__legacy__"


@dataclass(frozen=True)
class Identity:
    owner_id: str
    bearer: str = field(default="", repr=False)


class Accounts:
    def __init__(self, path=None):
        self.enabled = bool(path)
        self.users = {}
        if not path:
            return
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        users = data.get("users")
        if not isinstance(users, dict) or not users:
            raise ValueError("invalid_auth_configuration")
        for owner, item in users.items():
            digest = item.get("token_sha256", "") if isinstance(item, dict) else ""
            if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", owner)
                    or not re.fullmatch(r"[0-9a-f]{64}", digest)
                    or digest in self.users.values()):
                raise ValueError("invalid_auth_configuration")
            self.users[owner] = digest

    def authenticate(self, authorization):
        if not self.enabled:
            return Identity(LEGACY_OWNER)
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not 32 <= len(token) <= 256:
            return None
        digest = hashlib.sha256(token.encode()).hexdigest()
        for owner, expected in self.users.items():
            if secrets.compare_digest(digest, expected):
                return Identity(owner, token)
        return None


class ThreadOwnership:
    def __init__(self, path):
        self.path = Path(path)
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS thread_owners (
                kind TEXT NOT NULL, thread_id TEXT NOT NULL, owner_id TEXT NOT NULL,
                PRIMARY KEY(kind,thread_id))""")
            conn.commit()

    def claim(self, kind, thread_id, owner):
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute("INSERT INTO thread_owners VALUES (?,?,?)", (kind, str(thread_id), owner))
            conn.commit()

    def owns(self, kind, thread_id, owner):
        with closing(sqlite3.connect(self.path)) as conn:
            return conn.execute("SELECT 1 FROM thread_owners WHERE kind=? AND thread_id=? "
                                "AND owner_id=?", (kind, str(thread_id), owner)).fetchone() is not None


def install_identity(app, *, business=False):
    app.state.accounts = Accounts(os.getenv("PPA_AUTH_CONFIG"))

    @app.middleware("http")
    async def verify(request: Request, call_next):
        protected = request.url.path.startswith(("/tasks", "/operations", "/identity")) if business else request.url.path.startswith("/v1/")
        if protected:
            identity = app.state.accounts.authenticate(request.headers.get("Authorization", ""))
            if identity is None:
                return JSONResponse(status_code=401, content={"detail": "authentication_required"},
                                    headers={"WWW-Authenticate": "Bearer"})
            request.state.identity = identity
        return await call_next(request)


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
