"""Deterministic mapping logic: validate the STTM, then decide how each row is implemented."""
import uuid


def finding(severity: str, rows: str, message: str) -> dict:
    """severity: error (blocks the run) | warning (needs a human look) | info."""
    return {"id": f"f_{uuid.uuid4().hex[:8]}", "severity": severity, "rows": rows, "message": message}
