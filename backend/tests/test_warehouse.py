"""SQL dialect handling and the local DuckDB warehouse."""
import pytest

from app.inputs.schema import parse_schema_md
from app.warehouse import get_warehouse
from app.warehouse.dialect import (
    SqlError,
    expression_to_local,
    normalize,
    parse_expression,
    referenced_columns,
    statement_to_local,
)
from app.warehouse.duckdb_wh import SANDBOX_VIEW, LocalSqlError


def test_bigquery_safe_functions_become_duckdb_try():
    assert expression_to_local("SAFE.PARSE_DATE('%Y-%m-%d', dob)").startswith("TRY(")
    assert expression_to_local("SAFE_CAST(x AS INT64)") == "TRY_CAST(x AS BIGINT)"
    assert "CURRENT_TIMESTAMP" in expression_to_local("CURRENT_DATETIME()")


@pytest.mark.parametrize("bad", ["(SELECT 1)", "x IN (SELECT a FROM t)", "DROP TABLE t", "*", "CONCAT(a,"])
def test_only_single_scalar_expressions_are_accepted(bad):
    with pytest.raises(SqlError):
        parse_expression(bad)


def test_expression_helpers():
    assert referenced_columns(parse_expression("CONCAT(a, ' ', b) || a")) == ["a", "b"]
    assert parse_expression("LOWER(x) AS y").sql() == "LOWER(x)"  # a stray alias is tolerated
    assert normalize("case  x when '1' then 'a' end") == normalize("CASE x WHEN '1' THEN 'a' END")


def test_statement_guard_rejects_smuggled_statements():
    with pytest.raises(SqlError, match="exactly one SELECT"):
        statement_to_local("SELECT 1; DROP TABLE raw.clinical_patients")


def test_demo_data_is_seeded_and_external_access_is_off():
    wh = get_warehouse()
    assert "raw.clinical_patients" in wh.list_tables()
    assert wh.row_count("raw.clinical_patients") == 15
    with pytest.raises(Exception, match="(?i)permission|disabled"):
        wh._cursor().execute("SELECT * FROM read_csv('seed/seed.sql')").fetchall()


def test_sandbox_surfaces_runtime_conversion_errors():
    wh = get_warehouse()
    types = wh.table_columns("raw.clinical_patients")
    with wh.sandbox("raw.clinical_patients", {"dob": "14/03/1985"}, 50, types) as box:
        cols, rows = box.rows(f"SELECT dob FROM {SANDBOX_VIEW}")
        assert rows[0] == ("14/03/1985",)  # the STTM sample row comes first
        assert len(rows) == 16
        with pytest.raises(LocalSqlError, match="Conversion Error"):
            box.rows(f"SELECT CAST(dob AS DATE) FROM {SANDBOX_VIEW}")


def test_contract_bootstrap_replace_table_and_audit():
    wh = get_warehouse()
    src = parse_schema_md("# Table: raw.wh_test_src\n| column | type | nullable |\n|---|---|---|\n"
                          "| id | STRING | NO |\n| amount | STRING | YES |")
    wh.create_from_contract(src, [{"id": "a", "amount": "10"}, {"id": "b", "amount": ""}])
    assert wh.table_columns("raw.wh_test_src") == {"id": "VARCHAR", "amount": "VARCHAR"}

    tgt = parse_schema_md("# Table: analytics.wh_test_tgt\n| column | type | nullable | key |\n|---|---|---|---|\n"
                          "| id | STRING | NO | PK |\n| amount | INT64 | NO | |")
    n = wh.replace_table("SELECT id, TRY_CAST(amount AS BIGINT) AS amount FROM raw.wh_test_src", tgt.table)
    audit = wh.audit(src.table, tgt)
    assert n == 2 and audit["countsMatch"]
    checks = {c["name"]: c for c in audit["checks"]}
    assert not checks["nonNull"]["ok"] and "amount (1)" in checks["nonNull"]["detail"]
    assert checks["uniqueKey"]["ok"] and checks["schema contract"]["ok"]
    assert audit["failedCheck"].startswith("nonNull")


def test_scan_bytes_follow_bigquery_sizing():
    wh = get_warehouse()
    b = wh.scan_bytes("raw.clinical_patients", {"patient_id": "STRING", "weight_kg": "FLOAT64",
                                                "raw_payload": "STRING"})
    assert b["patient_id"] == 15 * (2 + 6)           # 2 bytes + UTF-8 length per value
    assert b["weight_kg"] == 13 * 8                   # NULLs cost nothing
    assert b["raw_payload"] > 10 * b["patient_id"]    # the unused payload dominates
