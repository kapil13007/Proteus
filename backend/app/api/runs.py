"""API endpoints. JSON shapes mirror the frontend's src/lib/types.ts exactly."""
import threading
import time
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.agent.graph import AgentState, run_execution, run_generation
from app.auth import get_current_user
from app.database import RunRecord, User, get_db
from app.schemas import run_to_dict
from app.services.runstore import push_feed, update_run

router = APIRouter()


@router.get("/runs")
def list_runs(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    runs = db.query(RunRecord).order_by(RunRecord.started_at.desc()).all()
    return [run_to_dict(r) for r in runs]


@router.get("/runs/{run_id}")
def get_run(run_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    run = db.get(RunRecord, run_id)
    if not run:
        raise HTTPException(404, "run not found")
    return run_to_dict(run)


@router.post("/runs")
async def create_run(
    source: UploadFile = File(...),
    target: UploadFile = File(...),
    sttm: UploadFile = File(...),
    repo: UploadFile = File(...),
    udf: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    run_id = f"run_{uuid.uuid4().hex[:8]}"
    source_md = (await source.read()).decode("utf-8", errors="replace")
    target_md = (await target.read()).decode("utf-8", errors="replace")
    sttm_bytes = await sttm.read()
    repo_md = (await repo.read()).decode("utf-8", errors="replace")
    udf_md = (await udf.read()).decode("utf-8", errors="replace") if udf else ""

    names = [f.filename for f in (source, target, sttm, repo) if f]
    if udf:
        names.append(udf.filename)

    record = RunRecord(
        id=run_id,
        created_by=user.email,
        status="running",
        started_at=int(time.time() * 1000),
        source_schema_md=source_md,
        target_schema_md=target_md,
        repo_structure_md=repo_md,
        udf_definitions_md=udf_md,
        file_names=names,
        feed=[],
        findings=[],
    )
    db.add(record)
    db.commit()

    state: AgentState = {
        "run_id": run_id,
        "source_schema_md": source_md,
        "target_schema_md": target_md,
        "sttm_filename": sttm.filename or "sttm.csv",
        "sttm_bytes": sttm_bytes,
        "repo_structure_md": repo_md,
        "udf_definitions_md": udf_md,
    }
    threading.Thread(target=run_generation, args=(state,), daemon=True).start()
    return {"run_id": run_id}


def _rebuild_state(run: RunRecord) -> AgentState:
    """Reconstruct agent state from the persisted run for the execution phase.

    This is the 'resume from checkpoint' — Postgres is our checkpointer.
    """
    from app.tools.parsers import parse_schema_md, parse_sttm
    from app.tools.sqlx import build_insert
    from app.tools.validator import validate

    source = parse_schema_md(run.source_schema_md)
    target = parse_schema_md(run.target_schema_md)
    rows, _ = parse_sttm("sttm.csv", run.sttm_csv.encode())
    active = validate(rows, source, target)["active_rows"]
    insert_sql = build_insert(run.sqlx_code, target["table"],
                              [r["target_field"] for r in active])
    return {
        "run_id": run.id,
        "source_schema": source,
        "target_schema": target,
        "active_rows": active,
        "sqlx_code": run.sqlx_code,
        "sqlx_path": run.sqlx_path,
        "insert_sql": insert_sql,
    }


@router.post("/runs/{run_id}/approve")
def approve_run(
    run_id: str,
    body: dict | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    run = db.get(RunRecord, run_id)
    if not run:
        raise HTTPException(404, "run not found")
    if run.status != "awaiting_review":
        raise HTTPException(409, f"run is {run.status}, not awaiting_review")

    # If the reviewer edited the .sqlx in the UI, accept their version
    edited = (body or {}).get("sqlx")
    if edited and edited.strip():
        update_run(run_id, sqlx_code=edited)
        run.sqlx_code = edited

    update_run(run_id, approved_by=user.email)
    push_feed(run_id, "thought", f"Approved by {user.email} — resuming pipeline")

    try:
        state = _rebuild_state(run)
    except Exception as e:  # noqa: BLE001
        push_feed(run_id, "tool_error", f"could not resume run: {e}")
        update_run(run_id, status="failed", step_failed=True)
        raise HTTPException(500, str(e)) from e

    threading.Thread(target=run_execution, args=(state, run.started_at), daemon=True).start()
    return {"ok": True}


@router.post("/runs/{run_id}/reject")
def reject_run(
    run_id: str,
    body: dict,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    run = db.get(RunRecord, run_id)
    if not run:
        raise HTTPException(404, "run not found")
    feedback = (body or {}).get("feedback", "")
    push_feed(run_id, "thought", f'Sent back by reviewer: "{feedback}"')
    update_run(run_id, status="rejected", reject_feedback=feedback,
               duration_sec=round((time.time() * 1000 - run.started_at) / 1000, 1))
    return {"ok": True}
