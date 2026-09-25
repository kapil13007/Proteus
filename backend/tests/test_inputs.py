"""Parsers for the context files: schemas, STTM (CSV + Excel), folder structure."""
import io

import pandas as pd
import pytest
from conftest import sample_bytes, sample_text

from app.inputs import InputError
from app.inputs.repo import infer_conventions, parse_tree
from app.inputs.schema import parse_schema_md
from app.inputs.sttm import parse_sttm
from app.inputs.types import bigquery_type, family, is_lossy


def test_schema_sample_files():
    src = parse_schema_md(sample_text("source_schema.md"))
    tgt = parse_schema_md(sample_text("target_schema.md"))
    assert src.table == "raw.clinical_patients" and src.dataset == "raw"
    assert list(src.columns)[:3] == ["patient_id", "first_name", "last_name"]
    assert not src.columns["patient_id"].nullable and src.columns["dob"].nullable
    assert tgt.keys == ["patient_id"]
    assert tgt.required == ["patient_id", "site_city", "_loaded_at"]
    assert tgt.columns["weight"].family == "int"


def test_schema_accepts_bigquery_mode_and_three_part_names():
    md = """# Table: my-proj.raw.orders
| name | data_type | mode | comment |
|---|---|---|---|
| id | INT64 | REQUIRED | key |
| amount | NUMERIC(10,2) | NULLABLE | |
"""
    s = parse_schema_md(md)
    assert (s.project, s.table) == ("my-proj", "raw.orders")
    assert not s.columns["id"].nullable and s.columns["amount"].nullable
    assert s.columns["amount"].family == "numeric"


@pytest.mark.parametrize("md, message", [
    ("| column | type |\n|---|---|\n| a | STRING |", "must name its table"),
    ("# Table: orders\n| column | type |\n|---|---|\n| a | STRING |", "qualified"),
    ("# Table: raw.t\nno table here", "no markdown table"),
    ("# Table: raw.t\n| column | type |\n|---|---|\n| a | STRING |\n| a | INT64 |", "listed twice"),
])
def test_schema_errors_are_readable(md, message):
    with pytest.raises(InputError, match=message):
        parse_schema_md(md)


def test_sttm_csv_and_excel_parse_identically():
    csv_rows, csv_text = parse_sttm("sttm.csv", sample_bytes("sttm.csv"))
    xlsx_rows, _ = parse_sttm("sttm.xlsx", sample_bytes("sttm.xlsx"))
    assert csv_rows == xlsx_rows
    assert [r["_row"] for r in csv_rows] == list(range(2, 13))  # spreadsheet row numbers
    email = next(r for r in csv_rows if r["target_field"] == "email_address")
    assert email["sample_data"] == "  John.DOE@Email.com "  # whitespace in samples is kept
    assert "site_code" in csv_text


def test_sttm_header_aliases():
    df = pd.DataFrame({"Source Column": ["a"], "Business Logic": ["copy"], "Target Column": ["b"],
                       "Status": ["Validated"], "Target Table": ["x.y"]})
    rows, _ = parse_sttm("m.csv", df.to_csv(index=False).encode())
    assert rows[0]["source_field"] == "a" and rows[0]["transformation_rule"] == "copy"
    assert rows[0]["target_field"] == "b" and rows[0]["mapping_status"] == "Validated"


def test_sttm_missing_required_columns():
    with pytest.raises(InputError, match="source_field"):
        parse_sttm("m.csv", b"foo,bar\n1,2\n")


def test_types():
    assert family("VARCHAR(20)") == "string" and bigquery_type("VARCHAR") == "STRING"
    assert family("TIMESTAMP WITH TIME ZONE") == "timestamp"
    assert is_lossy("STRING", "INT64") and not is_lossy("INT64", "FLOAT64")


def test_folder_structure_sample_inference():
    conv = infer_conventions(sample_text("folder_structure.md"))
    assert conv.layer_dir == "definitions/gold"
    assert conv.step_path("process", "fct_x") == "definitions/gold/fct_x/fct_x_process.sqlx"
    assert conv.source_params_path("src") == "includes/params/source_table/src.js"
    assert conv.target_params_path("fct_x") == "includes/params/target_table/fct_x.js"
    assert conv.functions_path == "includes/functions.js" and conv.env_vars_path == "includes/env_vars.js"
    assert conv.existing_declaration("sites") == "definitions/sources/sites.sqlx"
    assert conv.existing_declaration("clinical_patients") is None
    assert any("dim_sites" in e for e in conv.evidence)  # every inference is explained


def test_folder_structure_windows_tree_and_bare_names():
    text = """
D:.
+---definitions
|   \\---gold
|       \\---orders
|               read.sqlx
|               process.sqlx
|               write.sqlx
\\---includes
        udfs.js
"""
    conv = infer_conventions(text)
    assert conv.functions_path == "includes/udfs.js"
    assert conv.step_files == {"read": "read.sqlx", "process": "process.sqlx", "write": "write.sqlx"}
    assert conv.step_path("write", "fct_y") == "definitions/gold/fct_y/write.sqlx"


def test_folder_structure_from_prose_paths_and_defaults():
    paths = parse_tree("We keep marts in `definitions/marts/` and UDFs in `includes/macros.js`.")
    assert "definitions/marts" in paths and "includes/macros.js" in paths
    conv = infer_conventions("")
    assert conv.step_path("read", "t") == "definitions/gold/t/t_read.sqlx"
    assert "default" in conv.evidence[0]


def test_excel_bytes_roundtrip_with_leading_zero_codes():
    buf = io.BytesIO()
    pd.DataFrame({"source_field": ["site_code"], "target_field": ["site"], "sample_data": ["01"]}).to_excel(
        buf, index=False)
    rows, _ = parse_sttm("x.xlsx", buf.getvalue())
    assert rows[0]["sample_data"] == "01"
