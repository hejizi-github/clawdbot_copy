"""SQLite-backed storage for evaluation results."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from pydantic import BaseModel, Field

from .metrics import EvalReport, MetricResult


class StoredResult(BaseModel):
    id: int
    trace_id: str
    agent_name: str
    overall_score: float
    passed: bool
    metrics: list[MetricResult]
    config_json: dict
    timestamp: float
    source_file: str


class ResultStore:
    """Persistent storage for trajeval evaluation results."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None
        self._ensure_schema()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def _ensure_schema(self) -> None:
        conn = self._get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS eval_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trace_id TEXT NOT NULL,
                agent_name TEXT NOT NULL DEFAULT 'unknown',
                overall_score REAL NOT NULL,
                passed INTEGER NOT NULL,
                metrics_json TEXT NOT NULL,
                config_json TEXT NOT NULL DEFAULT '{}',
                source_file TEXT NOT NULL DEFAULT '',
                timestamp REAL NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_eval_trace_id
            ON eval_results(trace_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_eval_timestamp
            ON eval_results(timestamp)
        """)
        conn.commit()

    def store_eval(
        self,
        report: EvalReport,
        agent_name: str = "unknown",
        config: dict | None = None,
        source_file: str = "",
    ) -> int:
        conn = self._get_conn()
        ts = report.timestamp if report.timestamp is not None else time.time()
        metrics_json = json.dumps([m.model_dump() for m in report.metrics])
        config_json = json.dumps(config or {})
        cursor = conn.execute(
            """INSERT INTO eval_results
               (trace_id, agent_name, overall_score, passed, metrics_json,
                config_json, source_file, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                report.trace_id,
                agent_name,
                report.overall_score,
                int(report.passed),
                metrics_json,
                config_json,
                source_file,
                ts,
            ),
        )
        conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    def get_result(self, result_id: int) -> StoredResult | None:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM eval_results WHERE id = ?", (result_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_stored(row)

    def get_history(
        self,
        trace_id: str | None = None,
        agent_name: str | None = None,
        limit: int = 50,
    ) -> list[StoredResult]:
        conn = self._get_conn()
        clauses: list[str] = []
        params: list[object] = []
        if trace_id is not None:
            clauses.append("trace_id = ?")
            params.append(trace_id)
        if agent_name is not None:
            clauses.append("agent_name = ?")
            params.append(agent_name)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = conn.execute(
            f"SELECT * FROM eval_results {where} ORDER BY timestamp DESC LIMIT ?",
            (*params, limit),
        ).fetchall()
        return [self._row_to_stored(r) for r in rows]

    def count(self) -> int:
        conn = self._get_conn()
        row = conn.execute("SELECT COUNT(*) FROM eval_results").fetchone()
        return row[0]

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    @staticmethod
    def _row_to_stored(row: sqlite3.Row) -> StoredResult:
        metrics_raw = json.loads(row["metrics_json"])
        metrics = [MetricResult(**m) for m in metrics_raw]
        config = json.loads(row["config_json"])
        return StoredResult(
            id=row["id"],
            trace_id=row["trace_id"],
            agent_name=row["agent_name"],
            overall_score=row["overall_score"],
            passed=bool(row["passed"]),
            metrics=metrics,
            config_json=config,
            timestamp=row["timestamp"],
            source_file=row["source_file"],
        )
