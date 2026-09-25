"""Dataform compile (V8) and file rendering."""
import pytest
from conftest import sample_text

from app.dataform import CompileError
from app.dataform.compiler import DataformProject, split_sqlx, split_template, strip_sql_comments
from app.dataform.render import RenderInput, column_expression, render_files
from app.inputs.repo import infer_conventions
from app.inputs.schema import parse_schema_md

FUNCTIONS = sample_text("functions.js")
ENV = sample_text("env_vars.js")


@pytest.fixture
def project():
    includes = {"includes/functions.js": FUNCTIONS, "includes/env_vars.js": ENV}
    with DataformProject(includes, {"functions": "includes/functions.js", "env_vars": "includes/env_vars.js"}) as p:
        yield p


def test_template_split_handles_nested_braces_strings_and_backticks():
    parts = split_template('A ${f("}")} `bq.t` \\d ${x ? `${y}` : "z"} B')
    assert parts == [("lit", "A "), ("expr", 'f("}")'), ("lit", " `bq.t` \\d "),
                     ("expr", 'x ? `${y}` : "z"'), ("lit", " B")]


def test_split_sqlx_blocks():
    p = split_sqlx('config {\n  type: "view"\n}\n\njs {\n  const a = 1;\n}\n\nSELECT ${a}\n')
    assert p.config.startswith("{") and "view" in p.config
    assert p.js == ["\n  const a = 1;\n"] and p.body == "SELECT ${a}"


def test_udf_catalog_from_sample_functions(project):
    cat = {u["name"]: u for u in project.udf_catalog("includes/functions.js")}
    assert cat["cleanEmail"]["example"] == "LOWER(TRIM(col))"
    assert cat["cleanEmail"]["description"].startswith("Standardised e-mail cleaning")
    assert cat["safeParseDate"]["arity"] == 1 and len(cat["safeParseDate"]["params"]) == 2
    assert cat["safeParseDate"]["example"] == "SAFE.PARSE_DATE('%Y-%m-%d', col)"
    assert cat["columnList"]["kind"] == "table"  # needs a params object: not a column UDF
    assert project.module_values("includes/env_vars.js")["gold_dataset"] == "analytics"


def test_expand_runs_the_teams_real_js(project):
    out = project.expand(['${functions.cleanEmail("cust_email_01")}', "${functions.nope()}",
                          "${env_vars.gold_dataset}", 'CONCAT(a, "b")'])
    assert out[0] == {"ok": True, "sql": "LOWER(TRIM(cust_email_01))"}
    assert not out[1]["ok"] and "not a function" in out[1]["error"]
    assert out[2]["sql"] == "analytics" and out[3]["sql"] == 'CONCAT(a, "b")'


def test_compile_file_with_require_ref_and_raw_sql(project):
    project.define("includes/params/source_table/t.js",
                   'module.exports = { table: "t", columns: ["a", "b"] };')
    project.set_refs({"t": "raw.t"})
    sqlx = ('config { type: "view", name: "t_read" }\n'
            'js {\n  const source = require("includes/params/source_table/t");\n}\n'
            "SELECT ${source.columns.join(\", \")}, `x` AS y, REGEXP_REPLACE(z, r'\\d+', '')\n"
            "FROM ${ref(source.table)} -- ${functions.cleanEmail(\"e\")}")
    action = project.compile_file(sqlx, "fallback")
    assert (action.name, action.type) == ("t_read", "view")
    assert action.sql == ("SELECT a, b, `x` AS y, REGEXP_REPLACE(z, r'\\d+', '')\n"
                          "FROM raw.t -- LOWER(TRIM(e))")
    assert strip_sql_comments(action.sql).endswith("FROM raw.t ")


def test_unknown_ref_and_runaway_js_are_contained(project):
    project.set_refs({})
    with pytest.raises(CompileError, match='ref\\("nope"\\)'):
        project.compile_body('SELECT 1 FROM ${ref("nope")}')
    with pytest.raises(CompileError, match="timeout"):
        project.expand(["${(function(){ while (true) {} })()}"])


def test_broken_include_reports_which_file():
    with pytest.raises(CompileError, match="includes/functions.js failed to load"):
        with DataformProject({"includes/functions.js": "module.exports = { x: ; }"},
                             {"functions": "includes/functions.js"}):
            pass


def test_provenance_labels_say_who_decided():
    from app.dataform.render import provenance
    assert provenance({"method": "udf", "origin": "rule", "udf": {"name": "siteLookup"}}) == "udf siteLookup"
    assert provenance({"method": "llm", "origin": "cache", "udfs_used": ["safeParseDate"]}) == \
        "llm → udf safeParseDate (cached)"
    assert provenance({"method": "sql_logic", "origin": "llm", "repaired": True}) == "sql_logic repaired by llm"
    assert provenance({"method": "reviewer", "origin": "reviewer"}) == "reviewer override"


def _decision(row, target, target_type, method, source="", sql=None, udf=None, default=""):
    return {"row": row, "target_field": target, "target_type": target_type, "source_field": source,
            "method": method, "origin": "rule", "sql": sql, "udf": udf, "default": default,
            "status": "ok", "error": None, "read_columns": [source] if source else []}


def test_render_layout_traceability_and_contract():
    src = parse_schema_md(sample_text("source_schema.md"))
    tgt = parse_schema_md(sample_text("target_schema.md"))
    conv = infer_conventions(sample_text("folder_structure.md"))
    decisions = [
        _decision(2, "patient_id", "STRING", "direct", "patient_id", sql="patient_id"),
        _decision(4, "email_address", "STRING", "udf", "cust_email_01",
                  udf={"name": "cleanEmail", "args": ["cust_email_01"]}),
        _decision(7, "site_city", "STRING", "udf", "site_code",
                  udf={"name": "siteLookup", "args": ["site_code"]}, default="Unknown"),
    ]
    for d in decisions:
        d["expression"] = column_expression(d, "functions")
    files = render_files(RenderInput(conv, src, tgt, decisions, ["patient_id", "cust_email_01", "site_code"],
                                     env_name="env_vars", env_values={"gold_dataset": "analytics",
                                                                      "raw_dataset": "raw"}))
    by_kind = {f["kind"]: f for f in files}
    assert by_kind["read"]["path"] == "definitions/gold/fct_clinical_patients/fct_clinical_patients_read.sqlx"
    assert by_kind["declaration"]["path"] == "definitions/sources/clinical_patients.sqlx"
    assert "schema: env_vars.raw_dataset" in by_kind["declaration"]["content"]

    process = by_kind["process"]["content"]
    assert "schema: env_vars.gold_dataset" in process
    assert "-- row 4 · udf cleanEmail · cust_email_01 → email_address" in process
    assert '${functions.cleanEmail("cust_email_01")} AS email_address' in process
    assert """COALESCE(${functions.siteLookup("site_code")}, 'Unknown') AS site_city""" in process
    assert "-- no STTM row maps weight" in process and "CAST(NULL AS INT64) AS weight" in process

    write = by_kind["write"]["content"]
    assert 'name: "fct_clinical_patients"' in write
    assert 'uniqueKey: ["patient_id"]' in write
    assert 'nonNull: ["patient_id", "site_city", "_loaded_at"]' in write
    assert "CAST(_loaded_at AS TIMESTAMP) AS _loaded_at" in write
    assert 'columns: ["patient_id", "cust_email_01", "site_code"]' in by_kind["source_params"]["content"]
    assert "lineage: {" in by_kind["target_params"]["content"]
