"""SQLite-backed result storage for evaluation history."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from .metrics import EvalReport
from .scorer import JudgeResult


DEFAULT_DB_PATH = Path("trajeval.db")

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS eval_results (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id    TEXT NOT NULL,
    agent_name  TEXT NOT NULL DEFAULT 'unknown',
    timestamp   REAL NOT NULL,
    overall_score REAL NOT NULL,
    passed      INTEGER NOT NULL,
    result_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS judge_results (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id    TEXT NOT NULL,
    agent_name  TEXT NOT NULL DEFAULT 'unknown',
    timestamp   REAL NOT NULL,
    overall_score REAL NOT NULL,
    passed      INTEGER NOT NULL,
    model       TEXT NOT NULL DEFAULT '',
    result_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_eval_trace ON eval_results(trace_id);
CREATE INDEX IF NOT EXISTS idx_eval_agent ON eval_results(agent_name);
CREATE INDEX IF NOT EXISTS idx_eval_ts ON eval_results(timestamp);
CREATE INDEX IF NOT EXISTS idx_judge_trace ON judge_results(trace_id);
CREATE INDEX IF NOT EXISTS idx_judge_agent ON judge_results(agent_name);
CREATE INDEX IF NOT EXISTS idx_judge_ts ON judge_results(timestamp);
"""


class StoredEval(BaseModel):
    id: int
    trace_id: str
    agent_name: str
    timestamp: float
    overall_score: float
    passed: bool
    report: EvalReport


class StoredJudge(BaseModel):
    id: int
    trace_id: str
    agent_name: str
    timestamp: float
    overall_score: float
    passed: bool
    model: str
    result: JudgeResult


class ResultStore:
    """SQLite-backed persistent storage for eval and judge results."""

    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA_SQL)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def save_eval(
        self,
        report: EvalReport,
        agent_name: str = "unknown",
    ) -> int:
        ts = report.timestamp or time.time()
        result_json = report.model_dump_json()
        cursor = self._conn.execute(
            "INSERT INTO eval_results (trace_id, agent_name, timestamp, overall_score, passed, result_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (report.trace_id, agent_name, ts, report.overall_score, int(report.passed), result_json),
        )
        self._conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    def save_judge(
        self,
        result: JudgeResult,
        agent_name: str = "unknown",
        passed: bool = False,
    ) -> int:
        ts = time.time()
        result_json = result.model_dump_json()
        cursor = self._conn.execute(
            "INSERT INTO judge_results (trace_id, agent_name, timestamp, overall_score, passed, model, result_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (result.trace_id, agent_name, ts, result.overall_score, int(passed), result.model, result_json),
        )
        self._conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    def list_evals(
        self,
        *,
        agent_name: str | None = None,
        failed_only: bool = False,
        limit: int = 50,
    ) -> list[StoredEval]:
        clauses = []
        params: list = []
        if agent_name:
            clauses.append("agent_name = ?")
            params.append(agent_name)
        if failed_only:
            clauses.append("passed = 0")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._conn.execute(
            f"SELECT * FROM eval_results {where} ORDER BY timestamp DESC LIMIT ?",
            [*params, limit],
        ).fetchall()
        return [self._row_to_stored_eval(r) for r in rows]

    def list_judges(
        self,
        *,
        agent_name: str | None = None,
        model: str | None = None,
        failed_only: bool = False,
        limit: int = 50,
    ) -> list[StoredJudge]:
        clauses = []
        params: list = []
        if agent_name:
            clauses.append("agent_name = ?")
            params.append(agent_name)
        if model:
            clauses.append("model = ?")
            params.append(model)
        if failed_only:
            clauses.append("passed = 0")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._conn.execute(
            f"SELECT * FROM judge_results {where} ORDER BY timestamp DESC LIMIT ?",
            [*params, limit],
        ).fetchall()
        return [self._row_to_stored_judge(r) for r in rows]

    def get_eval(self, result_id: int) -> StoredEval | None:
        row = self._conn.execute(
            "SELECT * FROM eval_results WHERE id = ?", (result_id,)
        ).fetchone()
        return self._row_to_stored_eval(row) if row else None

    def get_judge(self, result_id: int) -> StoredJudge | None:
        row = self._conn.execute(
            "SELECT * FROM judge_results WHERE id = ?", (result_id,)
        ).fetchone()
        return self._row_to_stored_judge(row) if row else None

    def count(self, table: Literal["eval", "judge"] = "eval") -> int:
        tbl = "eval_results" if table == "eval" else "judge_results"
        row = self._conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()
        return row[0]

    @staticmethod
    def _row_to_stored_eval(row: sqlite3.Row) -> StoredEval:
        report = EvalReport.model_validate_json(row["result_json"])
        return StoredEval(
            id=row["id"],
            trace_id=row["trace_id"],
            agent_name=row["agent_name"],
            timestamp=row["timestamp"],
            overall_score=row["overall_score"],
            passed=bool(row["passed"]),
            report=report,
        )

    @staticmethod
    def _row_to_stored_judge(row: sqlite3.Row) -> StoredJudge:
        result = JudgeResult.model_validate_json(row["result_json"])
        return StoredJudge(
            id=row["id"],
            trace_id=row["trace_id"],
            agent_name=row["agent_name"],
            timestamp=row["timestamp"],
            overall_score=row["overall_score"],
            passed=bool(row["passed"]),
            model=row["model"],
            result=result,
        )
