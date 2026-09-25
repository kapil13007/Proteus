"""Run endpoints. Long work happens in the pipeline's worker pool; every call here returns fast."""
import io
import time
import uuid
import zipfile

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import RunEvent, RunRecord, User, get_db
from app.inputs import InputError
from app.inputs.schema import parse_schema_md
from app.inputs.sttm import parse_sttm
from app.pipeline import S_EXECUTE, S_GENERATE
from app.pipeline import orchestrator
from app.pipeline.recorder import RunRecorder
from app.schemas import run_summary, run_to_dict

router = APIRouter()
MAX_UPLOAD_BYTES = 5 * 1024 * 1024


def _read(upload: UploadFile | None, label: str) -> bytes:
    if upload is None:
        return b""
    data = upload.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"{label} is larger than 5 MB")
    return data


def _text(data: bytes) -> str:
    return data.decode("utf-8-sig", errors="replace")


def _get(db: Session, run_id: str) -> RunRecord:
    run = db.get(RunRecord, run_id)
    if not run:
        raise HTTPException(404, "run not found")
    return run


@router.get("/runs")
def list_runs(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return [run_summary(r) for r in db.query(RunRecord).order_by(RunRecord.started_at.desc()).all()]


@router.get("/runs/{run_id}")
def get_run(run_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    run = _get(db, run_id)
    events = db.query(RunEvent).filter(RunEvent.run_id == run_id).order_by(RunEvent.id).all()
    return run_to_dict(run, events)


@router.post("/runs")
def create_run(
    source: UploadFile = File(...),
    target: UploadFile = File(...),
    sttm: UploadFile = File(...),
    repo: UploadFile = File(...),
    udf: UploadFile | None = File(None),
    env: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source_md, target_md = _text(_read(source, "Source schema")), _text(_read(target, "Target schema"))
    sttm_bytes, repo_md = _read(sttm, "STTM sheet"), _text(_read(repo, "Folder structure"))
    functions_js, env_js = _text(_read(udf, "functions.js")), _text(_read(env, "env_vars.js"))

    # Fail fast on unreadable files: a 400 on the upload page beats a failed run.
    try:
        _, sttm_csv = parse_sttm(sttm.filename or "sttm.csv", sttm_bytes)
        parse_schema_md(source_md, "source schema")
        parse_schema_md(target_md, "target schema")
    except InputError as e:
        raise HTTPException(400, str(e)) from e

    run_id = f"run_{uuid.uuid4().hex[:8]}"
    db.add(RunRecord(
        id=run_id, created_by=user.email, status="running", started_at=int(time.time() * 1000),
        inputs={"source_schema_md": source_md, "target_schema_md": target_md, "sttm_csv": sttm_csv,
                "sttm_filename": sttm.filename or "", "repo_structure_md": repo_md,
                "functions_js": functions_js, "env_vars_js": env_js},
        file_names=[f.filename for f in (source, target, sttm, repo, udf, env) if f is not None and f.filename],
        findings=[], decisions=[], files=[], metrics={}, revisions=[],
    ))
    db.commit()
    orchestrator.submit(orchestrator.run_generation, run_id)
    return {"run_id": run_id}


class Override(BaseModel):
    row: int
    expression: str


class ReviseBody(BaseModel):
    overrides: list[Override] = Field(default_factory=list)
    feedback: str = ""


@router.post("/runs/{run_id}/revise")
def revise_run(run_id: str, body: ReviseBody, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    run = _get(db, run_id)
    if run.status != "awaiting_review":
        raise HTTPException(409, f"run is {run.status}, not awaiting_review")
    overrides = [o for o in body.overrides if o.expression.strip()]
    if not overrides and not body.feedback.strip():
        raise HTTPException(400, "send at least one override or some feedback")
    known = {d["row"] for d in run.decisions or []}
    unknown = [o.row for o in overrides if o.row not in known]
    if unknown:
        raise HTTPException(400, f"no mapping decision for row(s) {unknown}")
    run.status, run.current_step = "running", S_GENERATE
    db.commit()
    RunRecorder(run_id).event("thought", f"Revision requested by {user.email}"
                                         + (f': "{body.feedback.strip()}"' if body.feedback.strip() else ""))
    orchestrator.submit(orchestrator.run_revision, run_id, [o.model_dump() for o in overrides],
                        body.feedback.strip(), user.email)
    return {"ok": True}


@router.post("/runs/{run_id}/approve")
def approve_run(run_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    run = _get(db, run_id)
    if run.status != "awaiting_review":
        raise HTTPException(409, f"run is {run.status}, not awaiting_review")
    blocked = [d["row"] for d in run.decisions or [] if d["status"] != "ok"]
    if blocked:
        raise HTTPException(409, f"row(s) {', '.join(map(str, blocked))} still need attention — "
                                 "override or revise them before approving")
    if not run.pipeline_sql:
        raise HTTPException(409, "nothing verified to execute")
    run.status, run.approved_by, run.current_step = "running", user.email, S_EXECUTE
    db.commit()
    RunRecorder(run_id).event("thought", f"Approved by {user.email} — executing in the local warehouse")
    orchestrator.submit(orchestrator.run_execution, run_id, user.email)
    return {"ok": True}


class RejectBody(BaseModel):
    feedback: str = ""


@router.post("/runs/{run_id}/reject")
def reject_run(run_id: str, body: RejectBody, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    run = _get(db, run_id)
    if run.status != "awaiting_review":
        raise HTTPException(409, f"run is {run.status}, not awaiting_review")
    run.status, run.reject_feedback = "rejected", body.feedback.strip()
    run.duration_sec = round(time.time() - (run.started_at or 0) / 1000, 1)
    db.commit()
    RunRecorder(run_id).event("thought", f"Rejected by {user.email}" +
                              (f': "{body.feedback.strip()}"' if body.feedback.strip() else ""))
    return {"ok": True}


@router.get("/runs/{run_id}/bundle.zip")
def download_bundle(run_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """The generated files at their repo paths, plus a decision log, ready to drop into a Dataform repo."""
    run = _get(db, run_id)
    if not run.files:
        raise HTTPException(409, "this run has no generated files yet")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in run.files:
            z.writestr(f["path"], f["content"])
        z.writestr("MAPFLOW_DECISIONS.md", _decision_log(run))
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{run.id}.zip"'})


def _decision_log(run: RunRecord) -> str:
    lines = [f"# {run.target_table} ← {run.source_table} ({run.id})", "",
             "| STTM row | target column | method | expression | why |", "|---|---|---|---|---|"]
    for d in run.decisions or []:
        expr = (d.get("expression") or "").replace("|", "\\|").replace("\n", " ")
        why = (d.get("rationale") or "").replace("|", "\\|")
        lines.append(f"| {d['row']} | {d['target_field']} | {d['method']} ({d['origin']}) | `{expr}` | {why} |")
    return "\n".join(lines) + "\n"
