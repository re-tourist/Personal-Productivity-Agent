"""SQLite persistence for server-claimed thread ownership, independent of HTTP and credentials."""
import sqlite3
from contextlib import closing
from pathlib import Path


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
