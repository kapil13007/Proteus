"""Thread-safe helpers the agent uses to write progress into the run record.

The agent runs in a background thread; every write opens its own short-lived
session so the API's sessions and the agent's never conflict.
"""
import threading
import uuid
from datetime import datetime

from app.database import RunRecord, SessionLocal

_lock = threading.Lock()


def _now_ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def update_run(run_id: str, **fields) -> None:
    with _lock:
        db = SessionLocal()
        try:
            run = db.get(RunRecord, run_id)
            if not run:
                return
            for k, v in fields.items():
                setattr(run, k, v)
            db.commit()
        finally:
            db.close()


def push_feed(run_id: str, kind: str, text: str) -> None:
    """kind: thought | tool_call | tool_result | tool_error"""
    with _lock:
        db = SessionLocal()
        try:
            run = db.get(RunRecord, run_id)
            if not run:
                return
            entry = {"id": f"e_{uuid.uuid4().hex[:8]}", "ts": _now_ts(), "kind": kind, "text": text}
            run.feed = (run.feed or []) + [entry]
            db.commit()
        finally:
            db.close()


def add_findings(run_id: str, findings: list[dict]) -> None:
    with _lock:
        db = SessionLocal()
        try:
            run = db.get(RunRecord, run_id)
            if not run:
                return
            run.findings = (run.findings or []) + findings
            db.commit()
        finally:
            db.close()


def get_run_snapshot(run_id: str) -> RunRecord | None:
    db = SessionLocal()
    try:
        return db.get(RunRecord, run_id)
    finally:
        db.close()
