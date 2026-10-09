import json
import sqlite3
import time
import uuid
from pathlib import Path


class Store:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, kind TEXT, query TEXT, mode TEXT, status TEXT, state TEXT, created REAL);
                CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT, type TEXT, payload TEXT, created REAL);
                CREATE TABLE IF NOT EXISTS datasets(id TEXT PRIMARY KEY, name TEXT, schema TEXT, rows INTEGER);
                CREATE TABLE IF NOT EXISTS receipts(task_id TEXT PRIMARY KEY, payload TEXT, receipt TEXT);
            """)

    def connect(self):
        c = sqlite3.connect(self.path, timeout=10)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        return c

    def create(self, kind, query, mode, state):
        tid = uuid.uuid4().hex
        with self.connect() as c:
            c.execute(
                "INSERT INTO tasks VALUES(?,?,?,?,?,?,?)",
                (
                    tid,
                    kind,
                    query,
                    mode,
                    "queued",
                    json.dumps(state, ensure_ascii=False),
                    time.time(),
                ),
            )
        self.event(tid, "queued", {"message": "任务已入队"})
        return tid

    def get(self, tid):
        with self.connect() as c:
            row = c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
        if not row:
            raise KeyError(tid)
        result = dict(row)
        result["state"] = json.loads(result["state"])
        return result

    def tasks(self, kind):
        with self.connect() as c:
            return [
                dict(r)
                for r in c.execute(
                    "SELECT id,query,mode,status,created FROM tasks WHERE kind=? ORDER BY created DESC LIMIT 100",
                    (kind,),
                )
            ]

    def checkpoint(self, tid, status, state, event_type, payload):
        # State and its event commit together; SSE readers cannot see a half-checkpoint.
        with self.connect() as c:
            c.execute(
                "UPDATE tasks SET status=?,state=? WHERE id=?",
                (status, json.dumps(state, ensure_ascii=False), tid),
            )
            c.execute(
                "INSERT INTO events(task_id,type,payload,created) VALUES(?,?,?,?)",
                (tid, event_type, json.dumps(payload, ensure_ascii=False), time.time()),
            )

    def event(self, tid, kind, payload):
        with self.connect() as c:
            c.execute(
                "INSERT INTO events(task_id,type,payload,created) VALUES(?,?,?,?)",
                (tid, kind, json.dumps(payload, ensure_ascii=False), time.time()),
            )

    def events(self, tid, after=0):
        with self.connect() as c:
            return [
                {**dict(r), "payload": json.loads(r["payload"])}
                for r in c.execute(
                    "SELECT * FROM events WHERE task_id=? AND seq>? ORDER BY seq LIMIT 500",
                    (tid, after),
                )
            ]

    def recover(self, kind):
        with self.connect() as c:
            c.execute(
                "UPDATE tasks SET status='interrupted' WHERE kind=? AND status IN ('queued','running')",
                (kind,),
            )

    def claim(self, tid, statuses):
        with self.connect() as c:
            placeholders = ",".join("?" for _ in statuses)
            return (
                c.execute(
                    f"UPDATE tasks SET status='running' WHERE id=? AND status IN ({placeholders})",
                    (tid, *statuses),
                ).rowcount
                == 1
            )
