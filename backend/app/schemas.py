"""Serialize RunRecord -> the exact camelCase shape the frontend's types.ts expects."""
from app.database import RunRecord


def run_to_dict(r: RunRecord) -> dict:
    attempt = None
    if r.attempt_current is not None and r.attempt_max is not None:
        attempt = {"step": 3, "current": r.attempt_current, "max": r.attempt_max}

    audit = None
    if r.audit_rows_written is not None:
        audit = {
            "rowsWritten": r.audit_rows_written,
            "countsMatch": bool(r.audit_counts_match),
            "nullsCheck": bool(r.audit_nulls_check),
        }
        if r.audit_failed_check:
            audit["failedCheck"] = r.audit_failed_check

    meta = {
        "files": r.file_names or [],
        "llmAttempts": r.llm_attempts or 0,
        "llmPromptTokens": r.llm_prompt_tokens or 0,
        "llmCompletionTokens": r.llm_completion_tokens or 0,
        "llmCostUsd": r.llm_cost_usd or 0.0,
    }
    if r.created_by:
        meta["createdBy"] = r.created_by
    if r.approved_by:
        meta["approvedBy"] = r.approved_by
    if r.workflow_id:
        meta["workflowId"] = r.workflow_id

    return {
        "id": r.id,
        "targetTable": r.target_table or "",
        "status": r.status,
        "mappingsValidated": r.mappings_validated or 0,
        "mappingsExcluded": r.mappings_excluded or 0,
        "costGb": r.cost_gb,
        "costUsd": r.cost_usd,
        "startedAt": r.started_at or 0,
        "durationSec": r.duration_sec,
        "currentStep": r.current_step or 0,
        "stepFailed": bool(r.step_failed),
        "attempt": attempt,
        "feed": r.feed or [],
        "findings": r.findings or [],
        "sqlx": r.sqlx_code or "",
        "sqlxPath": r.sqlx_path or "",
        "audit": audit,
        "meta": meta,
    }
