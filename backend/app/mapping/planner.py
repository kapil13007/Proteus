"""The router: decides, row by row, how each target column is built.

Cheapest and most trustworthy option first; the LLM is the last resort:

  1. sql_logic that calls a team UDF          -> udf        (as the analyst wrote it)
  2. sql_logic identical to a team UDF         -> udf        (reuse the reviewed implementation)
  3. any other sql_logic                       -> sql_logic  (the analyst's SQL, verbatim)
  4. "copy as-is" rule, safe conversion        -> direct     (plain column; write step casts)
  5. "copy as-is" rule, lossy conversion       -> cast       (SAFE_CAST, flagged for review)
  6. natural-language rule                     -> llm        (the only rows that cost tokens)

Every decision records which rule fired and why, so every generated line of
SQL can be traced back to one STTM row and one reason.
"""
import re
from typing import Callable

import sqlglot
from sqlglot import exp

from app.inputs.schema import TableSchema
from app.inputs.types import bigquery_type, is_lossy
from app.mapping.validator import is_direct_rule
from app.warehouse.dialect import SqlError, normalize, parse_expression, referenced_columns, sql_literal

_TEMPLATE_UDF = re.compile(r"\$\{\s*([A-Za-z_$][\w$]*)\.([A-Za-z_$][\w$]*)\s*\(")
_SQL_DEFAULT = re.compile(
    r"^(null|true|false|-?\d+(\.\d+)?|'.*'|\".*\"|current_(date|timestamp|datetime|time)(\(\))?|[a-z_][\w.]*\(.*\))$",
    re.IGNORECASE | re.DOTALL)


def default_sql(value: str, target_type: str) -> str | None:
    """STTM default_value -> SQL. Bare words become string literals ('Unknown'); SQL stays SQL."""
    v = value.strip()
    if not v or v.lower() == "null":
        return None
    if bigquery_type(target_type) == "STRING" and re.fullmatch(r"-?\d+(\.\d+)?", v):
        return sql_literal(v)
    return v if _SQL_DEFAULT.match(v) else sql_literal(v)


def new_decision(r: dict, source: TableSchema, target: TableSchema) -> dict:
    sf, tf = r["source_field"], r["target_field"]
    return {
        "row": r["_row"],
        "target_field": tf,
        "target_type": target.columns[tf].type if tf in target.columns else r["target_type"],
        "source_field": sf,
        "source_type": source.columns[sf].type if sf in source.columns else r["source_type"],
        "rule": r["transformation_rule"],
        "sql_logic": r["sql_logic"],
        "lookup": r["lookup_table"],
        "default": r["default_value"],
        "sample": r["sample_data"],
        "method": "",
        "origin": "rule",
        "udf": None,
        "sql": None,
        "rationale": "",
        "status": "pending",
        "error": None,
        "attempts": 0,
        "repaired": False,
        "template": "",
        "expression": "",
        "compiled": "",
        "output_type": None,
        "examples": [],
        "nulls_introduced": None,
        "udfs_used": [],
    }


def _plain_udf_call(sql: str, catalog: dict[str, dict]) -> tuple[str, list[str]] | None:
    """'cleanEmail(cust_email_01)' where cleanEmail is a team UDF -> ('cleanEmail', ['cust_email_01'])."""
    m = re.match(r"^\s*([A-Za-z_$][\w$]*)\s*\(", sql)
    if not m or m.group(1) not in catalog:
        return None
    try:
        tree = sqlglot.parse_one(sql, read="bigquery")
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(tree, exp.Anonymous) or tree.name != m.group(1):
        return None
    return m.group(1), [a.sql(dialect="bigquery") for a in tree.expressions]


def plan(rows: list[dict], source: TableSchema, target: TableSchema, catalog: list[dict],
         expand: Callable[[list[tuple[str, list[str]]]], list[str | None]]) -> list[dict]:
    """rows: validated active STTM rows. catalog: column-level UDFs.
    expand([(udf, args), ...]) -> the SQL each call expands to (None if it fails)."""
    udfs = {u["name"]: u for u in catalog if u["kind"] == "column"}
    decisions, equivalence_jobs = [], []

    for r in rows:
        d = new_decision(r, source, target)
        decisions.append(d)
        logic, sf, tf = r["sql_logic"].strip(), r["source_field"], r["target_field"]

        if logic:
            tm = _TEMPLATE_UDF.search(logic)
            call = _plain_udf_call(logic, udfs)
            if tm:
                d.update(method="udf", sql=logic, rationale=f"STTM sql_logic calls {tm.group(1)}.{tm.group(2)}() — used as written")
            elif call:
                d.update(method="udf", udf={"name": call[0], "args": call[1]},
                         rationale=f"STTM sql_logic calls the team UDF {call[0]}() — rendered as a Dataform include call")
            else:
                d.update(method="sql_logic", sql=logic, rationale="STTM sql_logic used verbatim")
                try:
                    cols = referenced_columns(parse_expression(logic))
                except SqlError:
                    cols = []
                target_norm = normalize(logic)
                if target_norm:
                    for name, u in udfs.items():
                        if u["arity"] <= len(cols) and u["arity"] >= 1:
                            equivalence_jobs.append((d, name, cols[:u["arity"]], target_norm))
            continue

        if is_direct_rule(r["transformation_rule"]) and sf in source.columns and tf in target.columns:
            s_type, t_type = source.columns[sf].type, target.columns[tf].type
            if is_lossy(s_type, t_type):
                d.update(method="cast", sql=f"SAFE_CAST({sf} AS {bigquery_type(t_type)})",
                         rationale=f"Straight copy, but {s_type} → {t_type} can fail on dirty data, so SAFE_CAST "
                                   "(unconvertible values become NULL)")
            else:
                note = "" if bigquery_type(s_type) == bigquery_type(t_type) else f"; the write step casts {s_type} → {t_type}"
                d.update(method="direct", sql=sf, rationale=f"Straight copy of {sf}{note}")
            continue

        d.update(method="llm", status="needs_llm", rationale="Natural-language rule — needs the LLM")

    # One V8 round trip to test whether any sql_logic is exactly a team UDF.
    if equivalence_jobs:
        expansions = expand([(name, args) for _, name, args, _ in equivalence_jobs])
        for (d, name, args, target_norm), expanded in zip(equivalence_jobs, expansions):
            if d["method"] == "sql_logic" and expanded and normalize(expanded) == target_norm:
                d.update(method="udf", udf={"name": name, "args": args}, sql=None,
                         rationale=f"STTM sql_logic is identical to the team UDF {name}({', '.join(args)}) — "
                                   "using the UDF so the logic lives in one reviewed place")
    return decisions
