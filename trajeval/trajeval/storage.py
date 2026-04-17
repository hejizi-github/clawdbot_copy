"""SQLite-backed storage for evaluation results."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from pydantic import BaseModel, Field

from .metrics import EvalReport


DEFAULT_DB_PATH = Path.home() / ".trajeval" / "history.db"

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id TEXT NOT NULL,
    timestamp REAL NOT NULL,
    overall_score REAL NOT NULL,
    passed INTEGER NOT NULL,
    metrics_json TEXT NOT NULL,
    config_json TEXT NOT NULL DEFAULT '{}',
    agent_name TEXT NOT NULL DEFAULT '',
    task TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_evaluations_trace_id ON evaluations(trace_id);
CREATE INDEX IF NOT EXISTS idx_evaluations_timestamp ON evaluations(timestamp);
"""


class EvalRecord(BaseModel):
    id: int
    trace_id: str
    timestamp: float
    overall_score: float
    passed: bool
    metrics_json: str
    config_json: str = "{}"
    agent_name: str = ""
    task: str = ""


class EvalStore:
    def __init__(self, db_path: Path | str | None = None):
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
            self._conn.executescript(_SCHEMA_SQL)
        return self._conn

    def close(self):
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def save_eval(
        self,
        report: EvalReport,
        agent_name: str = "",
        task: str = "",
        config: dict | None = None,
    ) -> int:
        conn = self._connect()
        ts = report.timestamp if report.timestamp is not None else time.time()
        metrics_json = json.dumps([m.model_dump() for m in report.metrics])
        config_json = json.dumps(config or {})
        cursor = conn.execute(
            """INSERT INTO evaluations
               (trace_id, timestamp, overall_score, passed, metrics_json, config_json, agent_name, task)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (report.trace_id, ts, report.overall_score, int(report.passed),
             metrics_json, config_json, agent_name, task),
        )
        conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    def get_eval(self, eval_id: int) -> EvalRecord | None:
        conn = self._connect()
        row = conn.execute(
            "SELECT * FROM evaluations WHERE id = ?", (eval_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def get_by_trace_id(self, trace_id: str) -> list[EvalRecord]:
        conn = self._connect()
        rows = conn.execute(
            "SELECT * FROM evaluations WHERE trace_id = ? ORDER BY timestamp DESC",
            (trace_id,),
        ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def list_evals(self, limit: int = 20, offset: int = 0) -> list[EvalRecord]:
        conn = self._connect()
        rows = conn.execute(
            "SELECT * FROM evaluations ORDER BY timestamp DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def get_latest(self, agent_name: str | None = None) -> EvalRecord | None:
        conn = self._connect()
        if agent_name:
            row = conn.execute(
                "SELECT * FROM evaluations WHERE agent_name = ? ORDER BY timestamp DESC LIMIT 1",
                (agent_name,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM evaluations ORDER BY timestamp DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def count(self) -> int:
        conn = self._connect()
        row = conn.execute("SELECT COUNT(*) FROM evaluations").fetchone()
        return row[0]

    def delete_eval(self, eval_id: int) -> bool:
        conn = self._connect()
        cursor = conn.execute("DELETE FROM evaluations WHERE id = ?", (eval_id,))
        conn.commit()
        return cursor.rowcount > 0

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> EvalRecord:
        return EvalRecord(
            id=row["id"],
            trace_id=row["trace_id"],
            timestamp=row["timestamp"],
            overall_score=row["overall_score"],
            passed=bool(row["passed"]),
            metrics_json=row["metrics_json"],
            config_json=row["config_json"],
            agent_name=row["agent_name"],
            task=row["task"],
        )

    def record_to_report(self, record: EvalRecord) -> EvalReport:
        from .metrics import MetricResult
        metrics_data = json.loads(record.metrics_json)
        metrics = [MetricResult(**m) for m in metrics_data]
        return EvalReport(
            trace_id=record.trace_id,
            metrics=metrics,
            overall_score=record.overall_score,
            passed=record.passed,
            timestamp=record.timestamp,
        )
