"""SQLite storage for persistent evaluation history."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from .metrics import EvalReport, MetricResult


DEFAULT_DB_DIR = Path.home() / ".trajeval"
DEFAULT_DB_PATH = DEFAULT_DB_DIR / "history.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS eval_results (
    trace_id TEXT NOT NULL,
    agent_name TEXT NOT NULL DEFAULT 'unknown',
    timestamp REAL NOT NULL,
    overall_score REAL NOT NULL,
    passed INTEGER NOT NULL,
    metrics_json TEXT NOT NULL,
    PRIMARY KEY (trace_id)
);

CREATE INDEX IF NOT EXISTS idx_eval_agent_ts
    ON eval_results (agent_name, timestamp DESC);
"""


class TrajevalDB:
    """Thin wrapper around SQLite for storing evaluation results."""

    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else DEFAULT_DB_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def save_eval(self, report: EvalReport, agent_name: str = "unknown") -> None:
        ts = report.timestamp if report.timestamp is not None else time.time()
        metrics_json = json.dumps([m.model_dump() for m in report.metrics])
        self._conn.execute(
            """INSERT OR REPLACE INTO eval_results
               (trace_id, agent_name, timestamp, overall_score, passed, metrics_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (report.trace_id, agent_name, ts, report.overall_score, int(report.passed), metrics_json),
        )
        self._conn.commit()

    def load_eval(self, trace_id: str) -> EvalReport | None:
        row = self._conn.execute(
            "SELECT * FROM eval_results WHERE trace_id = ?", (trace_id,)
        ).fetchone()
        if row is None:
            return None
        return _row_to_report(row)

    def list_evals(
        self, agent_name: str | None = None, limit: int = 50
    ) -> list[EvalReport]:
        if agent_name:
            rows = self._conn.execute(
                "SELECT * FROM eval_results WHERE agent_name = ? ORDER BY timestamp DESC LIMIT ?",
                (agent_name, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM eval_results ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_row_to_report(r) for r in rows]

    def get_latest_baseline(self, agent_name: str) -> EvalReport | None:
        row = self._conn.execute(
            "SELECT * FROM eval_results WHERE agent_name = ? ORDER BY timestamp DESC LIMIT 1",
            (agent_name,),
        ).fetchone()
        if row is None:
            return None
        return _row_to_report(row)

    def delete_eval(self, trace_id: str) -> bool:
        cursor = self._conn.execute(
            "DELETE FROM eval_results WHERE trace_id = ?", (trace_id,)
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def count(self, agent_name: str | None = None) -> int:
        if agent_name:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM eval_results WHERE agent_name = ?",
                (agent_name,),
            ).fetchone()
        else:
            row = self._conn.execute("SELECT COUNT(*) FROM eval_results").fetchone()
        return row[0]


def _row_to_report(row: sqlite3.Row) -> EvalReport:
    metrics = [MetricResult(**m) for m in json.loads(row["metrics_json"])]
    return EvalReport(
        trace_id=row["trace_id"],
        metrics=metrics,
        overall_score=row["overall_score"],
        passed=bool(row["passed"]),
        timestamp=row["timestamp"],
    )
