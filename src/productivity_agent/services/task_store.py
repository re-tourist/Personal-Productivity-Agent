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
from datetime import datetime, timezone
from pathlib import Path


class IdempotencyConflict(ValueError):
    """An operation id was reused with different business parameters."""


class TransientWriteError(ConnectionError):
    """Temporary failure before the transaction committed."""


class AmbiguousCommitError(TimeoutError):
    """The transaction committed but the caller did not receive a response."""


def validate_task_request(operation_id: str, title: str, due_at: str) -> tuple[str, str, str]:
    if not isinstance(operation_id, str) or not 0 < len(operation_id.strip()) <= 128:
        raise ValueError("operation_id must be a nonempty string up to 128 chars")
    if not isinstance(title, str) or not 0 < len(title.strip()) <= 200:
        raise ValueError("title must be a nonempty string up to 200 chars")
    try:
        due = datetime.fromisoformat(due_at)
    except (TypeError, ValueError) as exc:
        raise ValueError("due_at must be an ISO 8601 date-time") from exc
    if due.utcoffset() is None:
        raise ValueError("due_at must have a timezone offset")
    # Canonicalize the same instant to avoid false conflicts from timezone representations.
    due_utc = due.astimezone(timezone.utc).isoformat()
    return operation_id.strip(), title.strip(), due_utc


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

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _read_operation(self, conn: sqlite3.Connection, operation_id: str):
        return conn.execute("""
            SELECT o.request_hash, t.id, t.title, t.due_at
            FROM task_operations o JOIN tasks t ON t.id = o.task_id
            WHERE o.operation_id = ?
        """, (operation_id,)).fetchone()

    def lookup(self, operation_id: str, title: str, due_at: str) -> dict | None:
        operation_id, title, due_utc = validate_task_request(operation_id, title, due_at)
        digest = request_fingerprint(title, due_utc)
        with closing(self._connect()) as conn:
            row = self._read_operation(conn, operation_id)
        if row is None:
            return None
        if row[0] != digest:
            raise IdempotencyConflict("operation_id already used for different parameters")
        return {"id": row[1], "title": row[2], "due_at": row[3]}

    def create_task(
        self, operation_id: str, title: str, due_at: str, *, fault: str | None = None,
    ) -> dict:
        """Create once; fault may be 'before_commit' or 'after_commit' for tests only."""
        operation_id, title, due_utc = validate_task_request(operation_id, title, due_at)
        digest = request_fingerprint(title, due_utc)
        if fault not in (None, "before_commit", "after_commit"):
            raise ValueError("unknown fault injection mode")

        with closing(self._connect()) as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")  # serialize concurrent writers
                row = self._read_operation(conn, operation_id)
                if row is not None:
                    if row[0] != digest:
                        raise IdempotencyConflict(
                            "operation_id already used for different parameters"
                        )
                    task = {"id": row[1], "title": row[2], "due_at": row[3]}
                    conn.commit()
                    return {"status": "replayed", "task": task}

                if fault == "before_commit":
                    raise TransientWriteError("injected connection failure before commit")

                task = {"id": str(uuid.uuid4()), "title": title, "due_at": due_utc}
                conn.execute(
                    "INSERT INTO tasks (id,title,due_at) VALUES (?,?,?)",
                    (task["id"], title, due_utc),
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

    def count_tasks(self) -> int:
        with closing(self._connect()) as conn:
            return conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]

    def list_tasks(self, *, limit: int = 100) -> list[dict]:
        """Read a bounded set of local demo tasks (newest first).

        This is not a user-scoped production endpoint; it is only for the
        single-user, loopback-bound demo service.
        """
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be in 1..1000")
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT id, title, due_at FROM tasks ORDER BY rowid DESC LIMIT ?", (limit,)
            ).fetchall()
        return [{"id": row[0], "title": row[1], "due_at": row[2]} for row in rows]
