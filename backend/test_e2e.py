"""E2E test: full pipeline against real local Postgres, LLM stubbed.

Attempt 1 returns .sqlx with a wrong column name -> dry-run must fail ->
retry -> attempt 2 returns the fixed .sqlx -> review -> approve -> execute -> audit.
"""
import os, sys, time
os.environ["DATABASE_URL"] = "postgresql://mapflow:mapflow@localhost:5432/mapflow"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BAD_SQLX = '''config { type: "table", schema: "analytics", tags: ["daily"] }

SELECT
  patient_id AS "patient_id",
  CONCAT(first_name, ' ', last_name) AS "full_name",
  TRIM(LOWER(customer_email)) AS "email_address", -- via cleanEmail()
  CAST(dob AS DATE) AS "date_of_birth",
  CAST(ROUND(weight_kg) AS INTEGER) AS "weight",
  CASE site_code WHEN '01' THEN 'Chennai' WHEN '02' THEN 'Mumbai' WHEN '03' THEN 'Delhi' ELSE 'Unknown' END AS "site_city",
  (enrolled_flag = 'Y') AS "is_enrolled",
  NOW() AS "_loaded_at"
FROM ${ref("clinical_patients")}'''

GOOD_SQLX = BAD_SQLX.replace("customer_email", "cust_email_01")

class FakeReply:
    def __init__(self, c): self.content = c

class FakeLLM:
    calls = 0
    def invoke(self, msgs):
        FakeLLM.calls += 1
        return FakeReply(f"```sqlx\n{BAD_SQLX if FakeLLM.calls == 1 else GOOD_SQLX}\n```")

import app.agent.graph as G
G._llm = lambda: FakeLLM()

from app.database import create_tables, SessionLocal, RunRecord
create_tables()

import uuid
run_id = f"run_{uuid.uuid4().hex[:8]}"
db = SessionLocal()
src = open("sample_inputs/source_schema.md").read()
tgt = open("sample_inputs/target_schema.md").read()
sttm = open("sample_inputs/sttm.csv","rb").read()
repo = open("sample_inputs/repo_structure.md").read()
udf = open("sample_inputs/udf_definitions.md").read()
db.add(RunRecord(id=run_id, status="running", started_at=int(time.time()*1000),
                 source_schema_md=src, target_schema_md=tgt, repo_structure_md=repo,
                 udf_definitions_md=udf, file_names=["a","b","c","d","e"], feed=[], findings=[]))
db.commit(); db.close()

state = {"run_id": run_id, "source_schema_md": src, "target_schema_md": tgt,
         "sttm_filename": "sttm.csv", "sttm_bytes": sttm,
         "repo_structure_md": repo, "udf_definitions_md": udf}
G.run_generation(state)

from app.services.runstore import get_run_snapshot
snap = get_run_snapshot(run_id)
print("STATUS AFTER GENERATION:", snap.status)
print("LLM ATTEMPTS:", snap.llm_attempts)
print("FINDINGS:", len(snap.findings or []))
for e in (snap.feed or []): print(f"  [{e['kind']:11}] {e['text']}")
assert snap.status == "awaiting_review", f"expected awaiting_review, got {snap.status}"
assert snap.llm_attempts == 2, "retry loop did not fire"

# --- approve & execute ---
from app.api.runs import _rebuild_state
exec_state = _rebuild_state(snap)
G.run_execution(exec_state, snap.started_at)

snap = get_run_snapshot(run_id)
print("\nSTATUS AFTER EXECUTION:", snap.status)
print("AUDIT:", snap.audit_rows_written, "rows | counts_match:", snap.audit_counts_match,
      "| nulls_ok:", snap.audit_nulls_check)
for e in (snap.feed or [])[-5:]: print(f"  [{e['kind']:11}] {e['text']}")
assert snap.status == "succeeded", f"expected succeeded, got {snap.status}"

# --- verify actual data landed ---
from sqlalchemy import text as sqltext
from app.database import engine
with engine.connect() as c:
    rows = c.execute(sqltext(
        "SELECT patient_id, full_name, email_address, date_of_birth, weight, site_city, is_enrolled "
        "FROM analytics.fct_clinical_patients ORDER BY patient_id LIMIT 3")).fetchall()
    for r in rows: print(" ", r)

# --- serializer matches frontend shape ---
from app.schemas import run_to_dict
d = run_to_dict(snap)
for key in ("id","targetTable","status","mappingsValidated","mappingsExcluded","costGb",
            "startedAt","durationSec","currentStep","feed","findings","sqlx","sqlxPath","audit","meta"):
    assert key in d, f"serializer missing {key}"
print("\nALL E2E CHECKS PASSED")
