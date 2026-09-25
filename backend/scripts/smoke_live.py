"""Live smoke test: the sample inputs through the real pipeline and the real Groq API.

    cd backend && python scripts/smoke_live.py

Needs GROQ_API_KEY in backend/.env. Uses throwaway databases in a temp folder,
never publishes to GitHub, and spends roughly 1-3K free-tier tokens.
"""
import os
import sys
import tempfile
import time
import uuid
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
_tmp = Path(tempfile.mkdtemp(prefix="mapflow-smoke-"))
os.environ.update({"DATABASE_URL": f"sqlite:///{(_tmp / 'app.db').as_posix()}",
                   "WAREHOUSE_PATH": str(_tmp / "warehouse.duckdb"),
                   "GITHUB_TOKEN": "", "LLM_CACHE": "false"})
sys.path.insert(0, str(BACKEND))

from app.config import settings  # noqa: E402
from app.database import RunEvent, RunRecord, SessionLocal, create_tables  # noqa: E402
from app.inputs.sttm import parse_sttm  # noqa: E402
from app.pipeline import orchestrator  # noqa: E402
from app.warehouse import reset_warehouse  # noqa: E402


def main() -> int:
    if not settings.groq_api_key:
        print("GROQ_API_KEY is empty — add it to backend/.env (free key: https://console.groq.com)")
        return 2
    samples = BACKEND / "sample_inputs"
    _, sttm_csv = parse_sttm("sttm.csv", (samples / "sttm.csv").read_bytes())
    create_tables()
    run_id = f"smoke_{uuid.uuid4().hex[:6]}"
    with SessionLocal() as db:
        db.add(RunRecord(
            id=run_id, status="running", created_by="smoke-test", started_at=int(time.time() * 1000),
            inputs={"source_schema_md": (samples / "source_schema.md").read_text(encoding="utf-8"),
                    "target_schema_md": (samples / "target_schema.md").read_text(encoding="utf-8"),
                    "sttm_csv": sttm_csv,
                    "repo_structure_md": (samples / "folder_structure.md").read_text(encoding="utf-8"),
                    "functions_js": (samples / "functions.js").read_text(encoding="utf-8"),
                    "env_vars_js": (samples / "env_vars.js").read_text(encoding="utf-8")},
            file_names=[], findings=[], decisions=[], files=[], metrics={}, revisions=[]))
        db.commit()

    started = time.perf_counter()
    orchestrator.run_generation(run_id)
    gen_ms = int((time.perf_counter() - started) * 1000)
    with SessionLocal() as db:
        run = db.get(RunRecord, run_id)
        events = db.query(RunEvent).filter(RunEvent.run_id == run_id).order_by(RunEvent.id).all()
    for e in events:
        print(f"  [{e.kind:11}] {e.text}")
    print(f"\nstatus after generation: {run.status}  ({gen_ms} ms wall clock)\n")
    for d in run.decisions:
        how = f"udf {d['udf']['name']}({', '.join(d['udf']['args'])})" if d.get("udf") else d.get("sql")
        print(f"  row {d['row']:>2} {d['target_field']:<14} {d['method']:<9} {d['status']:<6} {how}")
        if d.get("rationale"):
            print(f"         why: {d['rationale']}")
    llm = run.metrics.get("llm", {})
    print(f"\nLLM: {llm.get('calls', 0)} call(s), {llm.get('promptTokens', 0)} in / "
          f"{llm.get('completionTokens', 0)} out tokens ({llm.get('reasoningTokens', 0)} reasoning), "
          f"{llm.get('latencyMs', 0)} ms, list-price ${llm.get('costUsd', 0):.5f} (free tier: $0)")
    print(f"timings (ms): {run.metrics.get('timingsMs')}")
    print(f"scan: {run.metrics.get('scan')}")
    process = next((f for f in run.files if f["kind"] == "process"), None)
    if process:
        print(f"\n--- {process['path']}\n{process['content']}")

    if run.status != "awaiting_review" or any(d["status"] != "ok" for d in run.decisions):
        print("Some columns need a human; not executing.")
        return 1
    orchestrator.run_execution(run_id, "smoke-test")
    with SessionLocal() as db:
        run = db.get(RunRecord, run_id)
    print(f"status after execution: {run.status}")
    for c in (run.audit or {}).get("checks", []):
        print(f"  audit {'PASS' if c['ok'] else 'FAIL'}  {c['name']}: {c['detail']}")
    return 0 if run.status == "succeeded" else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        reset_warehouse()
