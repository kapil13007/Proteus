"""Serialize runs for the frontend (camelCase, matching frontend/src/lib/types.ts)."""
from app.database import RunEvent, RunRecord
from app.pipeline import S_VERIFY


def _camel_key(key: str) -> str:
    head, *rest = key.split("_")
    return head + "".join(p[:1].upper() + p[1:] for p in rest)


def camel_keys(record: dict) -> dict:
    """camelCase a record's own keys only. Nested values are data — e.g. example rows keyed by
    source column name — and must keep their names."""
    return {_camel_key(k): v for k, v in record.items()}


def _meta(r: RunRecord) -> dict:
    meta = {"files": r.file_names or []}
    if r.created_by:
        meta["createdBy"] = r.created_by
    if r.approved_by:
        meta["approvedBy"] = r.approved_by
    if r.reject_feedback:
        meta["rejectFeedback"] = r.reject_feedback
    return meta


def run_summary(r: RunRecord) -> dict:
    metrics = r.metrics or {}
    return {
        "id": r.id,
        "sourceTable": r.source_table or "",
        "targetTable": r.target_table or "",
        "status": r.status,
        "mappingsValidated": r.mappings_validated or 0,
        "mappingsExcluded": r.mappings_excluded or 0,
        "startedAt": r.started_at or 0,
        "durationSec": r.duration_sec,
        "currentStep": r.current_step or 0,
        "stepFailed": bool(r.step_failed),
        "metrics": metrics,
        "meta": _meta(r),
    }


def run_to_dict(r: RunRecord, events: list[RunEvent]) -> dict:
    attempt = None
    if r.attempt_current is not None and r.attempt_max is not None:
        attempt = {"step": S_VERIFY, "current": r.attempt_current, "max": r.attempt_max}
    return {
        **run_summary(r),
        "error": r.error,
        "attempt": attempt,
        "feed": [{"id": f"e_{e.id}", "ts": e.ts, "kind": e.kind, "text": e.text} for e in events],
        "findings": [{k: v for k, v in f.items() if k != "stage"} for f in (r.findings or [])],
        "decisions": [camel_keys(d) for d in r.decisions or []],
        "files": r.files or [],
        "preview": r.preview or {},
        "conventions": camel_keys(r.conventions or {}),
        "udfCatalog": [camel_keys(u) for u in r.udf_catalog or []],
        "audit": r.audit,
        "publish": r.publish,
        "revisions": r.revisions or [],
    }
