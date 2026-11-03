"""M4: SQLite-backed mock task service with transactionally enforced idempotency.

This is a local simulation, NOT a real calendar/task integration.
A stable operation_id identifies ONE logical write, independent of LLM tool-call IDs.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path

from productivity_agent.domain.tasks import (
    IdempotencyConflict,
    VersionConflict,
    validate_task_request,
)
from productivity_agent.infrastructure.security.identity import LEGACY_OWNER


class TransientWriteError(ConnectionError):
    """Temporary failure before the transaction committed."""


class AmbiguousCommitError(TimeoutError):
    """The transaction committed but the caller did not receive a response."""




def request_fingerprint(title: str, due_utc: str) -> str:
    encoded = json.dumps(
        {"title": title, "due_at_utc": due_utc},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class SQLiteTaskStore:
    """Local durable mock: tasks and operation index share one SQLite transaction.

    Single-host teaching implementation. For production replace with PostgreSQL,
    proper authorization/tenant scoping, monitoring, and an API-level idempotency contract.
    """

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    due_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS task_operations (
                    operation_id TEXT PRIMARY KEY,
                    request_hash TEXT NOT NULL,
                    task_id TEXT NOT NULL REFERENCES tasks(id)
                );
            """)
            conn.commit()
            # Additive, transactional migration: preserve IDs and historical operations.
            conn.execute("BEGIN IMMEDIATE")
            columns = {r[1] for r in conn.execute("PRAGMA table_info(tasks)")}
            if "version" not in columns:
                conn.execute("ALTER TABLE tasks ADD COLUMN version INTEGER NOT NULL DEFAULT 1")
            if "owner_id" not in columns:
                conn.execute("ALTER TABLE tasks ADD COLUMN owner_id TEXT NOT NULL DEFAULT '__legacy__'")
            if "status" not in columns:
                conn.execute("ALTER TABLE tasks ADD COLUMN status TEXT NOT NULL DEFAULT 'pending'")
            conn.execute("""CREATE TABLE IF NOT EXISTS task_changes (
                operation_id TEXT PRIMARY KEY, request_json TEXT NOT NULL,
                result_json TEXT NOT NULL)""")
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _read_operation(self, conn: sqlite3.Connection, operation_id: str, owner_id=LEGACY_OWNER):
        return conn.execute("""
            SELECT o.request_hash, t.id, t.title, t.due_at
            FROM task_operations o JOIN tasks t ON t.id = o.task_id
            WHERE o.operation_id = ? AND t.owner_id = ?
        """, (operation_id, owner_id)).fetchone()

    def lookup(self, operation_id: str, title: str, due_at: str, *, owner_id=LEGACY_OWNER) -> dict | None:
        operation_id, title, due_utc = validate_task_request(operation_id, title, due_at)
        digest = request_fingerprint(title, due_utc)
        operation_id = self._operation_key(owner_id, operation_id)
        with closing(self._connect()) as conn:
            row = self._read_operation(conn, operation_id, owner_id)
        if row is None:
            return None
        if row[0] != digest:
            raise IdempotencyConflict("operation_id already used for different parameters")
        return self.get_task(row[1], owner_id=owner_id)

    def create_task(
        self, operation_id: str, title: str, due_at: str, *, fault: str | None = None, owner_id=LEGACY_OWNER,
    ) -> dict:
        """Create once; fault may be 'before_commit' or 'after_commit' for tests only."""
        operation_id, title, due_utc = validate_task_request(operation_id, title, due_at)
        digest = request_fingerprint(title, due_utc)
        operation_id = self._operation_key(owner_id, operation_id)
        if fault not in (None, "before_commit", "after_commit"):
            raise ValueError("unknown fault injection mode")

        with closing(self._connect()) as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")  # serialize concurrent writers
                if conn.execute("SELECT 1 FROM task_changes WHERE operation_id=?", (operation_id,)).fetchone():
                    raise IdempotencyConflict("operation_id reused")
                row = self._read_operation(conn, operation_id, owner_id)
                if row is not None:
                    if row[0] != digest:
                        raise IdempotencyConflict(
                            "operation_id already used for different parameters"
                        )
                    task = self.get_task(row[1], owner_id=owner_id)
                    conn.commit()
                    return {"status": "replayed", "task": task}

                if fault == "before_commit":
                    raise TransientWriteError("injected connection failure before commit")

                task = {"id": str(uuid.uuid4()), "title": title, "due_at": due_utc,
                        "version": 1, "status": "pending"}
                conn.execute(
                    "INSERT INTO tasks (id,title,due_at,owner_id) VALUES (?,?,?,?)",
                    (task["id"], title, due_utc, owner_id),
                )
                conn.execute(
                    "INSERT INTO task_operations (operation_id,request_hash,task_id) VALUES (?,?,?)",
                    (operation_id, digest, task["id"]),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

        if fault == "after_commit":
            # Deliberately AFTER the transaction has committed.
            raise AmbiguousCommitError("injected timeout after commit")
        return {"status": "created", "task": task}

    def count_tasks(self, *, owner_id=LEGACY_OWNER) -> int:
        with closing(self._connect()) as conn:
            return conn.execute("SELECT COUNT(*) FROM tasks WHERE owner_id=?", (owner_id,)).fetchone()[0]

    def list_tasks(self, *, limit: int = 100, owner_id=LEGACY_OWNER) -> list[dict]:
        """Read a bounded set of local demo tasks (newest first).

        This is not a user-scoped production endpoint; it is only for the
        single-user, loopback-bound demo service.
        """
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be in 1..1000")
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT id, title, due_at, version, status FROM tasks WHERE owner_id=? ORDER BY rowid DESC LIMIT ?", (owner_id, limit)
            ).fetchall()
        return [dict(zip(("id", "title", "due_at", "version", "status"), row)) for row in rows]

    def get_task(self, task_id, *, owner_id=LEGACY_OWNER):
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT id,title,due_at,version,status FROM tasks WHERE id=? AND owner_id=?", (task_id, owner_id)
            ).fetchone()
        if row is None:
            raise KeyError("task_not_found")
        return dict(zip(("id", "title", "due_at", "version", "status"), row))

    def change_task(self, operation_id, task_id, expected_version, action, *,
                    title=None, due_at=None, owner_id=LEGACY_OWNER):
        if action not in {"update_task", "complete_task"}:
            raise ValueError("unsupported_action")
        if type(expected_version) is not int or expected_version < 1:
            raise ValueError("invalid_version")
        if not isinstance(operation_id, str) or not 0 < len(operation_id.strip()) <= 128:
            raise ValueError("invalid_operation_id")
        if action == "complete_task" and (title is not None or due_at is not None):
            raise ValueError("completion_has_no_patch")
        if action == "update_task" and title is None and due_at is None:
            raise ValueError("empty_patch")
        if title is not None or due_at is not None:
            _, cleaned_title, cleaned_due = validate_task_request(
                operation_id, title if title is not None else "unused",
                due_at if due_at is not None else "2000-01-01T00:00:00+00:00")
            title = cleaned_title if title is not None else None
            due_at = cleaned_due if due_at is not None else None
        payload = {"task_id": task_id, "expected_version": expected_version,
                       "action": action, "title": title, "due_at": due_at}
        encoded = json.dumps(payload, sort_keys=True)
        operation_id = self._operation_key(owner_id, operation_id)
        with closing(self._connect()) as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                owned = conn.execute("SELECT 1 FROM tasks WHERE id=? AND owner_id=?", (task_id, owner_id)).fetchone()
                if owned is None:
                    raise KeyError("task_not_found")
                old = conn.execute("SELECT request_json,result_json FROM task_changes "
                                   "WHERE operation_id=?", (operation_id,)).fetchone()
                if old:
                    if old[0] != encoded:
                        raise IdempotencyConflict("operation_id reused")
                    return {"status": "replayed", "task": json.loads(old[1])}
                if conn.execute("SELECT 1 FROM task_operations WHERE operation_id=?",
                                (operation_id,)).fetchone():
                    raise IdempotencyConflict("operation_id reused")
                row = conn.execute("SELECT title,due_at,status,version FROM tasks WHERE id=?",
                                   (task_id,)).fetchone()
                if row is None:
                    raise KeyError("task_not_found")
                if row[3] != expected_version:
                    raise VersionConflict("stale_version_read_again")
                task = {"id": task_id, "title": title if title is not None else row[0],
                            "due_at": due_at if due_at is not None else row[1],
                            "status": "completed" if action == "complete_task" else row[2],
                            "version": row[3] + 1}
                conn.execute("UPDATE tasks SET title=?,due_at=?,status=?,version=? WHERE id=?",
                             (task["title"], task["due_at"], task["status"], task["version"], task_id))
                conn.execute("INSERT INTO task_changes VALUES (?,?,?)",
                             (operation_id, encoded, json.dumps(task)))
                conn.commit()
                return {"status": "updated", "task": task}
            except Exception:
                conn.rollback()
                raise

    def get_operation(self, operation_id, *, owner_id=LEGACY_OWNER):
        operation_id = self._operation_key(owner_id, operation_id)
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT request_json,result_json FROM task_changes "
                               "WHERE operation_id=?", (operation_id,)).fetchone()
            if row:
                task = json.loads(row[1])
                if not conn.execute("SELECT 1 FROM tasks WHERE id=? AND owner_id=?", (task["id"], owner_id)).fetchone():
                    return None
                return {"request": json.loads(row[0]), "task": task}
            row = self._read_operation(conn, operation_id, owner_id)
        if row:
            return {"request_hash": row[0], "task": self.get_task(row[1], owner_id=owner_id)}
        return None


    @staticmethod
    def _operation_key(owner_id, operation_id):
        # Preserve old operation rows byte-for-byte; secure users get separate namespaces.
        if owner_id == LEGACY_OWNER:
            return operation_id
        encoded = json.dumps([owner_id, operation_id], separators=(",", ":")).encode()
        return "owner:" + hashlib.sha256(encoded).hexdigest()

    def for_owner(self, owner_id, bearer=""):
        return OwnedTaskStore(self, owner_id)


class OwnedTaskStore:
    """Trusted server-side binding; never constructed from a request user_id field."""
    def __init__(self, store, owner_id):
        self.store = store
        self.owner_id = owner_id

    def __getattr__(self, name):
        if name not in {"create_task", "change_task", "get_task", "list_tasks", "count_tasks",
                        "lookup", "get_operation"}:
            raise AttributeError(name)
        def call(*args, **kwargs):
            return getattr(self.store, name)(*args, **kwargs, owner_id=self.owner_id)
        return call
