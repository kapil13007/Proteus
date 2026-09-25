"""End-to-end: the whole pipeline on real local engines (SQLite, DuckDB, V8), LLM scripted."""
import time
import uuid

from conftest import SAMPLE_ANSWERS

from app.database import RunEvent, RunRecord, SessionLocal
from app.inputs.sttm import parse_sttm
from app.pipeline import orchestrator
from app.warehouse import get_warehouse

TARGET_COLUMNS = ["patient_id", "full_name", "email_address", "date_of_birth", "weight", "site_city",
                  "is_enrolled", "visit_count", "created_ts", "_loaded_at"]


def make_run(inputs: dict, sttm: bytes | None = None, **extra) -> str:
    _, csv_text = parse_sttm("sttm.csv", sttm if sttm is not None else inputs["sttm_csv"])
    run_id = f"run_{uuid.uuid4().hex[:8]}"
    payload = {"source_schema_md": inputs["source"], "target_schema_md": inputs["target"], "sttm_csv": csv_text,
               "repo_structure_md": inputs["repo"], "functions_js": inputs["functions"],
               "env_vars_js": inputs["env"], **extra}
    with SessionLocal() as db:
        db.add(RunRecord(id=run_id, status="running", created_by="analyst@example.com",
                         started_at=int(time.time() * 1000), inputs=payload, file_names=[], findings=[],
                         decisions=[], files=[], metrics={}, revisions=[]))
        db.commit()
    return run_id


def load(run_id: str) -> RunRecord:
    with SessionLocal() as db:
        return db.get(RunRecord, run_id)


def feed(run_id: str) -> str:
    with SessionLocal() as db:
        return "\n".join(f"[{e.kind}] {e.text}" for e in
                         db.query(RunEvent).filter(RunEvent.run_id == run_id).order_by(RunEvent.id))


def by_target(run: RunRecord) -> dict:
    return {d["target_field"]: d for d in run.decisions}


def test_full_pipeline_generate_verify_repair_execute_audit(fake_llm, empty_cache, sample_inputs):
    llm = fake_llm()
    run_id = make_run(sample_inputs)
    orchestrator.run_generation(run_id)
    run = load(run_id)
    assert run.status == "awaiting_review", feed(run_id)
    d = by_target(run)
    assert all(x["status"] == "ok" for x in run.decisions), feed(run_id)

    # routing: deterministic first, LLM only for natural-language rules
    assert {t: x["method"] for t, x in d.items()} == {
        "patient_id": "direct", "full_name": "llm", "email_address": "llm", "date_of_birth": "llm",
        "weight": "llm", "site_city": "udf", "is_enrolled": "sql_logic", "visit_count": "cast",
        "created_ts": "direct", "_loaded_at": "sql_logic"}
    assert d["email_address"]["udf"] == {"name": "cleanEmail", "args": ["cust_email_01"]}
    assert d["site_city"]["origin"] == "rule" and "identical to the team UDF siteLookup" in d["site_city"]["rationale"]

    # repair loop: the plain CAST broke on dirty dates, and ONLY that row went back to the LLM
    assert len(llm.calls) == 2
    assert llm.calls[0]["rows"] == [3, 4, 5, 6]
    assert llm.calls[1]["rows"] == [5] and "Conversion Error" in llm.calls[1]["prompt"]
    assert d["date_of_birth"]["attempts"] == 2

    # explainability: the STTM's own sample row, in -> out
    email = d["email_address"]["examples"][0]
    assert email == {"in": {"cust_email_01": "  John.DOE@Email.com "}, "out": "john.doe@email.com"}
    assert d["date_of_birth"]["examples"][0] == {"in": {"dob": "14/03/1985"}, "out": "1985-03-14"}

    # files: conventional paths, team UDFs, traceability comments
    files = {f["kind"]: f for f in run.files}
    assert files["process"]["path"] == "definitions/gold/fct_clinical_patients/fct_clinical_patients_process.sqlx"
    process = files["process"]["content"]
    assert '${functions.cleanEmail("cust_email_01")} AS email_address' in process
    assert """COALESCE(${functions.siteLookup("site_code")}, 'Unknown') AS site_city""" in process
    assert "-- row 5 · llm · dob → date_of_birth" in process
    assert "raw_payload" not in files["source_params"]["content"]  # projection: unused column never read

    # silent data loss is surfaced, not hidden: '' and 'n/a' visit counts became NULL
    assert d["visit_count"]["nulls_introduced"] == {"count": 2, "of": 16, "examples": ["", "n/a"]}
    assert d["date_of_birth"]["nulls_introduced"]["examples"] == ["unknown"]
    assert any("became NULL" in f["message"] and f["rows"] == "9" for f in run.findings)

    # verified preview (real rows only, UTC) + cost model
    assert run.preview["columns"] == TARGET_COLUMNS and len(run.preview["rows"]) == 10
    assert run.preview["rows"][0][:2] == ["P-0001", "John Doe"]
    assert run.preview["rows"][0][8] == "2026-06-01 09:15:00+00"
    scan = run.metrics["scan"]
    assert scan["readColumns"] == 10 and scan["totalColumns"] == 11
    assert scan["readBytes"] < scan["fullBytes"] / 3
    assert run.metrics["llm"]["calls"] == 2 and run.metrics["rows"]["deterministic"] == 6
    assert run.metrics["rows"]["usingUdfs"] == 3  # full_name, email_address, site_city

    # approve -> execute -> audit -> publish (skipped: no token in tests)
    orchestrator.run_execution(run_id, "reviewer@example.com")
    run = load(run_id)
    assert run.status == "succeeded", feed(run_id)
    assert run.audit["rowsWritten"] == 15 and run.audit["failedCheck"] is None
    assert {c["name"] for c in run.audit["checks"]} == {"row count", "nonNull", "uniqueKey", "schema contract"}
    assert run.publish["skipped"] is True

    rows = get_warehouse()._cursor().execute(
        "SELECT patient_id, email_address, CAST(date_of_birth AS VARCHAR), weight, site_city, visit_count "
        "FROM analytics.fct_clinical_patients ORDER BY patient_id").fetchall()
    got = {r[0]: r[1:] for r in rows}
    assert got["P-0001"] == ("john.doe@email.com", "1985-03-14", 82, "Chennai", 3)
    assert got["P-0003"][1] == "1978-07-23"               # legacy DD/MM/YYYY parsed
    assert got["P-0006"][4] is None                       # 'n/a' visit count -> NULL via SAFE_CAST
    assert got["P-0011"][3] == "Unknown"                  # unknown site code
    assert got["P-0013"][1] is None                       # 'unknown' date -> NULL, load did not fail


def test_unchanged_rerun_costs_zero_tokens(fake_llm, empty_cache, sample_inputs):
    fake_llm()
    orchestrator.run_generation(make_run(sample_inputs))
    second = fake_llm()
    run_id = make_run(sample_inputs)
    orchestrator.run_generation(run_id)
    run = load(run_id)
    assert run.status == "awaiting_review"
    assert second.calls == []
    assert {x["origin"] for x in run.decisions if x["method"] == "llm"} == {"cache"}
    assert "0 tokens" in feed(run_id)


def test_reviewer_override_is_verified_then_executed(fake_llm, empty_cache, sample_inputs):
    fake_llm()
    run_id = make_run(sample_inputs)
    orchestrator.run_generation(run_id)
    orchestrator.run_revision(run_id, [{"row": 8, "expression": '${functions.ynToBool("enrolled_flag")}'}],
                              "", "reviewer@example.com")
    run = load(run_id)
    assert run.status == "awaiting_review", feed(run_id)
    d = by_target(run)["is_enrolled"]
    assert (d["method"], d["origin"], d["status"]) == ("reviewer", "reviewer", "ok")
    assert run.revisions[0]["overrides"] == [8]
    orchestrator.run_execution(run_id, "reviewer@example.com")
    enrolled = get_warehouse()._cursor().execute(
        "SELECT is_enrolled FROM analytics.fct_clinical_patients WHERE patient_id = 'P-0004'").fetchone()[0]
    assert enrolled is True  # 'y ' now counts, thanks to the UDF


def test_feedback_revision_only_sends_the_rows_it_mentions(fake_llm, empty_cache, sample_inputs):
    llm = fake_llm({**SAMPLE_ANSWERS,
                    "is_enrolled": [{"kind": "udf", "udf": "ynToBool", "args": ["enrolled_flag"]}]})
    run_id = make_run(sample_inputs)
    orchestrator.run_generation(run_id)
    before = len(llm.calls)
    orchestrator.run_revision(run_id, [], "is_enrolled should use the ynToBool UDF so 'y ' counts", "rev@x.com")
    run = load(run_id)
    assert llm.calls[before]["rows"] == [8]
    d = by_target(run)["is_enrolled"]
    assert d["method"] == "llm" and d["udf"]["name"] == "ynToBool" and d["status"] == "ok"
    assert run.revisions[-1]["changedRows"] == [8]


def test_row_the_llm_cannot_fix_is_escalated_to_a_human(fake_llm, empty_cache, sample_inputs):
    llm = fake_llm({**SAMPLE_ANSWERS, "weight": [{"kind": "sql", "sql": "CAST(weight_kg AS DATE)"}]})
    run_id = make_run(sample_inputs)
    orchestrator.run_generation(run_id)
    run = load(run_id)
    assert run.status == "awaiting_review"
    weight = by_target(run)["weight"]
    assert weight["status"] == "failed" and weight["attempts"] == 3
    assert [c["rows"] for c in llm.calls] == [[3, 4, 5, 6], [5, 6], [6]]  # bounded, and shrinking
    assert any(f["severity"] == "error" and f["rows"] == "6" for f in run.findings)
    process = next(f for f in run.files if f["kind"] == "process")["content"]
    assert "CAST(NULL AS INT64) AS weight  /* MAPFLOW: needs a human" in process

    orchestrator.run_revision(run_id, [{"row": 6, "expression": "CAST(ROUND(weight_kg) AS INT64)"}], "", "rev@x.com")
    run = load(run_id)
    assert all(x["status"] == "ok" for x in run.decisions)
    orchestrator.run_execution(run_id, "rev@x.com")
    assert load(run_id).status == "succeeded"


def test_sheet_errors_stop_the_run_before_any_llm_call(fake_llm, sample_inputs):
    llm = fake_llm()
    bad = sample_inputs["sttm_csv"].replace(b",full_name,", b",fullname_typo,")
    run_id = make_run(sample_inputs, sttm=bad)
    orchestrator.run_generation(run_id)
    run = load(run_id)
    assert run.status == "failed" and run.current_step == 1
    assert llm.calls == []
    assert any('"fullname_typo" does not exist' in f["message"] for f in run.findings)


def test_without_an_llm_key_deterministic_rows_still_verify(monkeypatch, empty_cache, sample_inputs):
    monkeypatch.setattr("app.llm.client.get_client", lambda: None)
    run_id = make_run(sample_inputs)
    orchestrator.run_generation(run_id)
    run = load(run_id)
    assert run.status == "awaiting_review"
    statuses = {t: x["status"] for t, x in by_target(run).items()}
    assert statuses["full_name"] == "failed" and statuses["site_city"] == "ok" and statuses["visit_count"] == "ok"
    assert "GROQ_API_KEY" in by_target(run)["full_name"]["error"]


def test_missing_source_is_bootstrapped_from_its_contract(fake_llm, sample_inputs):
    llm = fake_llm({})
    inputs = {
        "source": "# Table: raw.demo_orders\n| column | type | nullable |\n|---|---|---|\n"
                  "| order_id | STRING | NO |\n| amount_txt | STRING | YES |",
        "target": "# Table: analytics.fct_orders\n| column | type | nullable | key |\n|---|---|---|---|\n"
                  "| order_id | STRING | NO | PK |\n| amount | NUMERIC | YES | |",
        "repo": "", "functions": "", "env": "",
    }
    sttm = (b"source_field,sample_data,transformation_rule,target_field,mapping_status\n"
            b"order_id,O-1,Copy as-is,order_id,Validated\n"
            b"amount_txt,12.50,Copy as-is,amount,Validated\n")
    run_id = make_run(inputs, sttm=sttm)
    orchestrator.run_generation(run_id)
    run = load(run_id)
    assert run.status == "awaiting_review", feed(run_id)
    assert llm.calls == []  # nothing needed the LLM
    assert "created it from source_schema.md" in feed(run_id)
    paths = sorted(f["path"] for f in run.files)
    assert "definitions/gold/fct_orders/fct_orders_write.sqlx" in paths  # default layout, no tree given
    orchestrator.run_execution(run_id, "rev@x.com")
    run = load(run_id)
    assert run.status == "succeeded", feed(run_id)
    assert run.audit["rowsWritten"] == 1
