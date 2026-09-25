"""STTM validation and the deterministic router."""
from conftest import sample_bytes, sample_text

from app.dataform.compiler import DataformProject
from app.dataform.render import udf_template
from app.inputs.schema import parse_schema_md
from app.inputs.sttm import parse_sttm
from app.mapping.planner import default_sql, plan
from app.mapping.validator import is_direct_rule, validate

SRC = parse_schema_md(sample_text("source_schema.md"))
TGT = parse_schema_md(sample_text("target_schema.md"))


def _row(n, sf, tf, rule="Copy as-is", logic="", default="", status="Validated", st="raw.clinical_patients",
         tt="analytics.fct_clinical_patients"):
    return {"_row": n, "source_table": st, "source_field": sf, "source_type": "", "nullable": "", "sample_data": "",
            "transformation_rule": rule, "sql_logic": logic, "lookup_table": "", "default_value": default,
            "target_table": tt, "target_field": tf, "target_type": "", "mapping_status": status}


def _all_required():
    return [_row(90, "patient_id", "patient_id"), _row(91, "site_code", "site_city", logic="'x'"),
            _row(92, "created_at", "_loaded_at", logic="CURRENT_TIMESTAMP()")]


def test_sample_sheet_validates_cleanly():
    rows, _ = parse_sttm("sttm.csv", sample_bytes("sttm.csv"))
    res = validate(rows, SRC, TGT)
    assert res["errors"] == []
    assert len(res["active_rows"]) == 10 and res["excluded_count"] == 1
    messages = " ".join(f["message"] for f in res["findings"])
    assert "not marked Validated" in messages
    assert "lossy conversion" in messages  # visit_count STRING -> INT64


def test_blocking_errors():
    rows = _all_required() + [
        _row(3, "nope", "full_name"),                                   # unknown source
        _row(4, "first_name", "not_a_column"),                          # unknown target
        _row(5, "first_name", "email_address"), _row(6, "last_name", "email_address"),  # duplicate target
        _row(7, "dob", "date_of_birth", st="raw.other_table"),          # multi-source
    ]
    rows[1] = _row(91, "site_code", "site_city")                        # nullable -> NOT NULL straight copy
    errors = " | ".join(e["message"] for e in validate(rows, SRC, TGT)["errors"])
    assert 'Source field "nope" does not exist' in errors
    assert 'Target field "not_a_column" does not exist' in errors
    assert "mapped more than once" in errors
    assert "Multi-source mappings" in errors
    assert "straight copy with no default" in errors


def test_unmapped_required_target_column_is_an_error():
    errors = validate([_row(2, "patient_id", "patient_id")], SRC, TGT)["errors"]
    assert {e["message"] for e in errors} >= {'Target column "site_city" is NOT NULL but has no mapping row'}


def test_direct_rule_phrases():
    for phrase in ("Copy as-is", "direct move", "1:1", "pass-through", "no transformation", "", "N/A"):
        assert is_direct_rule(phrase), phrase
    assert not is_direct_rule("Round to the nearest kilogram")


def test_default_sql():
    assert default_sql("Unknown", "STRING") == "'Unknown'"
    assert default_sql("0", "STRING") == "'0'"
    assert default_sql("0", "INT64") == "0"
    assert default_sql("CURRENT_TIMESTAMP()", "TIMESTAMP") == "CURRENT_TIMESTAMP()"
    assert default_sql("NULL", "STRING") is None


def test_router_on_the_sample_sheet():
    rows, _ = parse_sttm("sttm.csv", sample_bytes("sttm.csv"))
    active = validate(rows, SRC, TGT)["active_rows"]
    functions = sample_text("functions.js")
    with DataformProject({"includes/functions.js": functions}, {"functions": "includes/functions.js"}) as p:
        catalog = p.udf_catalog("includes/functions.js")

        def expand(calls):
            return [r["sql"] if r["ok"] else None
                    for r in p.expand([udf_template("functions", n, a) for n, a in calls])]

        decisions = {d["target_field"]: d for d in plan(active, SRC, TGT, catalog, expand)}

    assert decisions["patient_id"]["method"] == "direct"
    assert decisions["created_ts"]["method"] == "direct"
    assert decisions["visit_count"]["method"] == "cast"
    assert decisions["visit_count"]["sql"] == "SAFE_CAST(visit_count AS INT64)"
    assert decisions["is_enrolled"]["method"] == "sql_logic"
    assert decisions["_loaded_at"]["method"] == "sql_logic"
    # the sheet's CASE is character-for-character the team's siteLookup UDF -> reuse the UDF
    assert decisions["site_city"]["method"] == "udf"
    assert decisions["site_city"]["udf"] == {"name": "siteLookup", "args": ["site_code"]}
    llm_rows = sorted(t for t, d in decisions.items() if d["method"] == "llm")
    assert llm_rows == ["date_of_birth", "email_address", "full_name", "weight"]
    assert all(decisions[t]["status"] == "needs_llm" for t in llm_rows)


def test_sql_logic_calling_a_udf_is_rendered_as_an_include_call():
    rows = [_row(2, "cust_email_01", "email_address", rule="clean", logic="cleanEmail(cust_email_01)")]
    catalog = [{"name": "cleanEmail", "kind": "column", "arity": 1, "params": [{"name": "col", "default": None}],
                "example": "LOWER(TRIM(col))"}]
    d = plan(rows, SRC, TGT, catalog, lambda calls: [None] * len(calls))[0]
    assert d["method"] == "udf" and d["udf"] == {"name": "cleanEmail", "args": ["cust_email_01"]}
