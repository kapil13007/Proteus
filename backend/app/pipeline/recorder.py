"""RunRecorder: everything a run writes about itself.

The pipeline runs in a worker thread; the API reads the same rows while the
frontend polls. Each write is a short transaction of its own, serialised by a
process-wide lock (SQLite has a single writer). Events are appended as rows,
never by rewriting a growing JSON array.
"""
import threading
import time
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime

from app.database import RunEvent, RunRecord, SessionLocal

_write_lock = threading.Lock()


def _merge(dst: dict, delta: dict) -> dict:
    for k, v in delta.items():
        if isinstance(v, dict):
            dst[k] = _merge(dict(dst.get(k) or {}), v)
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            dst[k] = round((dst.get(k) or 0) + v, 6)
        else:
            dst[k] = v
    return dst


class RunRecorder:
    def __init__(self, run_id: str):
        self.run_id = run_id

    def load(self) -> RunRecord | None:
        with SessionLocal() as db:
            return db.get(RunRecord, self.run_id)

    def update(self, **fields) -> None:
        with _write_lock, SessionLocal() as db:
            run = db.get(RunRecord, self.run_id)
            if run is None:
                return
            for k, v in fields.items():
                setattr(run, k, v)
            db.commit()

    def event(self, kind: str, text: str) -> None:
        """kind: thought | tool_call | tool_result | tool_error"""
        with _write_lock, SessionLocal() as db:
            db.add(RunEvent(run_id=self.run_id, ts=datetime.now().strftime("%H:%M:%S"), kind=kind, text=text))
            db.commit()

    def add_findings(self, findings: list[dict]) -> None:
        if not findings:
            return
        with _write_lock, SessionLocal() as db:
            run = db.get(RunRecord, self.run_id)
            if run is not None:
                run.findings = list(run.findings or []) + findings
                db.commit()

    def add_metrics(self, delta: dict) -> None:
        """Numbers are added, nested dicts merged, anything else overwritten."""
        with _write_lock, SessionLocal() as db:
            run = db.get(RunRecord, self.run_id)
            if run is not None:
                run.metrics = _merge(deepcopy(run.metrics or {}), delta)
                db.commit()

    def set_metrics(self, **values) -> None:
        """Overwrite top-level metric groups (e.g. the latest scan estimate)."""
        with _write_lock, SessionLocal() as db:
            run = db.get(RunRecord, self.run_id)
            if run is not None:
                run.metrics = {**deepcopy(run.metrics or {}), **values}
                db.commit()

    @contextmanager
    def stage(self, step: int | None, name: str):
        """Mark the stepper position and time the stage (accumulated per stage name)."""
        if step is not None:
            self.update(current_step=step)
        started = time.perf_counter()
        try:
            yield
        finally:
            self.add_metrics({"timingsMs": {name: int((time.perf_counter() - started) * 1000)}})
